import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Avg, Count, Sum
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import (
    EmailOTP,
    GlobalDataGrant,
    Organization,
    OrganizationMembership,
    PasswordResetToken,
    User,
)
from apps.accounts.otp import issue_otp, verify_otp
from apps.ai.models import AIUsageRecord
from apps.audit.models import AuditEvent
from apps.candidates.services import purge_candidate
from apps.candidates.tasks import retention_sweep
from apps.clients.models import ClientCompany, ClientMembership
from apps.common.audit import record_audit
from apps.common.pagination import StandardPagination
from apps.common.permissions import AgencyAdminOnly, AgencyOnly, IsAuthenticatedInOrg, PlatformOnly, TenantMixin
from apps.common.roles import AGENCY_ADMIN, AGENCY_ROLES, CLIENT_ROLES
from apps.common.tenancy import attach_tenant, require_org
from apps.processing.models import ProcessingJob


class LoginThrottle(AnonRateThrottle):
    scope = "login"


def user_payload(user: User, organization=None) -> dict:
    membership = None
    if organization is not None:
        membership = (
            OrganizationMembership.objects.filter(user=user, organization=organization, is_active=True)
            .select_related("organization")
            .first()
        )
    if membership is None and not user.is_platform_admin:
        membership = (
            OrganizationMembership.objects.filter(user=user, is_active=True).select_related("organization").first()
        )
    companies = []
    if membership:
        companies = [
            {"id": str(row.company_id), "name": row.company.name, "role": row.role}
            for row in ClientMembership.objects.filter(user=user, organization=membership.organization).select_related("company")
        ]
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "is_platform_admin": user.is_platform_admin,
        "membership": None
        if membership is None
        else {
            "role": membership.role,
            "organization": {
                "id": str(membership.organization_id),
                "name": membership.organization.name,
                "status": membership.organization.status,
                "read_only": membership.organization.read_only,
                "status_reason": membership.organization.status_reason,
            },
        },
        "client_companies": companies,
    }


def organization_payload(org: Organization) -> dict:
    cached_grants = getattr(org, "_prefetched_objects_cache", {}).get("global_grants")
    if cached_grants is not None:
        scopes = sorted(row.scope for row in cached_grants)
    else:
        scopes = sorted(org.global_grants.values_list("scope", flat=True))
    payload = {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "contact_email": org.contact_email,
        "status": org.status,
        "read_only": org.read_only,
        "status_reason": org.status_reason,
        "status_changed_at": org.status_changed_at,
        "global_access": scopes,
    }
    counts = {}
    for key, attribute in (
        ("members", "member_count"),
        ("candidates", "candidate_count"),
        ("jobs", "job_count"),
        ("submissions", "submission_count"),
    ):
        value = getattr(org, attribute, None)
        if value is not None:
            counts[key] = value
    if counts:
        payload["counts"] = counts
    return payload


def _clean_email(value, field: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    try:
        validate_email(text)
    except DjangoValidationError:
        raise ValidationError({field: "Enter a valid email address."})
    return text


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        password = request.data.get("password") or ""
        user = User.objects.filter(email__iexact=email).first()
        if user is None or not user.is_active or not user.check_password(password):
            return Response(
                {"error": {"code": "invalid_credentials", "message": "Email or password is incorrect.", "details": {}}},
                status=401,
            )
        refresh = RefreshToken.for_user(user)
        payload = user_payload(user)
        request.user = user
        attach_tenant(request)
        record_audit(request, "login", user, "Login succeeded")
        return Response({"access": str(refresh.access_token), "refresh": str(refresh), "user": payload})


class LogoutView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]
    allow_missing_org = True

    def post(self, request):
        raw = request.data.get("refresh") or ""
        try:
            token = RefreshToken(raw)
            token.blacklist()
        except TokenError:
            return Response(
                {"error": {"code": "invalid_token", "message": "Refresh token is invalid or expired.", "details": {}}},
                status=400,
            )
        record_audit(request, "logout", request.user, "Logout")
        return Response({"status": "signed_out"})


class RefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            token = RefreshToken(request.data.get("refresh") or "")
        except TokenError:
            return Response(
                {"error": {"code": "invalid_token", "message": "Refresh token is invalid or expired.", "details": {}}},
                status=401,
            )
        return Response({"access": str(token.access_token), "refresh": str(token)})


class MeView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]
    allow_missing_org = True

    def get(self, request):
        return Response(user_payload(request.user, getattr(request, "organization", None)))

    def patch(self, request):
        user = request.user
        if "full_name" in request.data:
            name = str(request.data.get("full_name") or "").strip()
            if len(name) > 200:
                raise ValidationError({"full_name": "Must be 200 characters or fewer."})
            user.full_name = name
            user.save(update_fields=["full_name", "updated_at"])
        return Response(user_payload(user, getattr(request, "organization", None)))


class ChangePasswordView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]
    allow_missing_org = True

    def post(self, request):
        current = request.data.get("current_password") or ""
        new = request.data.get("new_password") or ""
        if not request.user.check_password(current):
            raise ValidationError({"current_password": "Current password is incorrect."})
        validate_password(new, request.user)
        request.user.set_password(new)
        request.user.save(update_fields=["password", "updated_at"])
        record_audit(request, "password_change", request.user, "Password changed")
        return Response({"status": "password_updated"})


class PasswordResetView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        debug_token = None
        if user:
            raw = secrets.token_urlsafe(32)
            PasswordResetToken.objects.create(
                user=user,
                token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                expires_at=timezone.now() + timedelta(hours=2),
            )
            send_mail(
                "Reset your Sable password",
                f"Use this link to choose a new password:\n{settings.PASSWORD_RESET_URL}?token={raw}\n\nThe link expires in two hours.",
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=True,
            )
            if settings.DEBUG:
                debug_token = raw
        body = {"message": "If an account exists for that email, a reset message was sent."}
        if debug_token:
            body["debug_reset_token"] = debug_token
        return Response(body)


class PasswordResetConfirmView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        raw = request.data.get("token") or ""
        password = request.data.get("password") or ""
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        row = PasswordResetToken.objects.filter(token_hash=token_hash, used_at__isnull=True).select_related("user").first()
        if row is None or row.expires_at < timezone.now():
            return Response(
                {"error": {"code": "invalid_token", "message": "This reset link is invalid or expired.", "details": {}}},
                status=400,
            )
        validate_password(password, row.user)
        row.user.set_password(password)
        row.user.save(update_fields=["password", "updated_at"])
        row.used_at = timezone.now()
        row.save(update_fields=["used_at"])
        return Response({"status": "password_updated"})


OTP_SENT_MESSAGE = "If an account exists for that email, a one-time code was sent."
OTP_INVALID_RESPONSE = {
    "error": {
        "code": "invalid_otp",
        "message": "That code is invalid or has expired. Request a new one.",
        "details": {},
    }
}


class OTPRequestView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        email = str(request.data.get("email") or "").strip()
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None:
            issue_otp(user, EmailOTP.Purpose.LOGIN)
        return Response({"message": OTP_SENT_MESSAGE})


class OTPLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        email = str(request.data.get("email") or "").strip()
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is None or not verify_otp(user, EmailOTP.Purpose.LOGIN, request.data.get("code")):
            return Response(OTP_INVALID_RESPONSE, status=400)
        refresh = RefreshToken.for_user(user)
        payload = user_payload(user)
        request.user = user
        attach_tenant(request)
        record_audit(request, "login_otp", user, "Login with email code")
        return Response({"access": str(refresh.access_token), "refresh": str(refresh), "user": payload})


class PasswordResetOTPView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        email = str(request.data.get("email") or "").strip()
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None:
            issue_otp(user, EmailOTP.Purpose.PASSWORD_RESET)
        return Response({"message": OTP_SENT_MESSAGE})


class PasswordResetOTPConfirmView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        email = str(request.data.get("email") or "").strip()
        password = request.data.get("password") or ""
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is None:
            return Response(OTP_INVALID_RESPONSE, status=400)
        try:
            validate_password(password, user)
        except DjangoValidationError as exc:
            return Response(
                {"error": {"code": "weak_password", "message": " ".join(exc.messages), "details": {}}},
                status=400,
            )
        if not verify_otp(user, EmailOTP.Purpose.PASSWORD_RESET, request.data.get("code")):
            return Response(OTP_INVALID_RESPONSE, status=400)
        user.set_password(password)
        user.save(update_fields=["password", "updated_at"])
        request.user = user
        record_audit(request, "password_reset", user, "Password reset with email code")
        return Response({"status": "password_updated"})


class OrganizationListView(TenantMixin, APIView):
    permission_classes = [PlatformOnly]
    allow_missing_org = True

    def get(self, request):
        rows = (
            Organization.objects.annotate(
                member_count=Count("memberships", distinct=True),
                candidate_count=Count("candidate", distinct=True),
                job_count=Count("job", distinct=True),
                submission_count=Count("candidatesubmission", distinct=True),
            )
            .prefetch_related("global_grants")
            .order_by("name")
        )
        return Response([organization_payload(org) for org in rows])

    def post(self, request):
        name = str(request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "Organization name is required."})
        if len(name) > 200:
            raise ValidationError({"name": "Must be 200 characters or fewer."})
        slug = str(request.data.get("slug") or "").strip().lower() or slugify(name)
        if not slug:
            raise ValidationError({"slug": "Provide a slug for this organization."})
        if Organization.objects.filter(slug=slug).exists():
            raise ValidationError({"slug": "That organization slug is already in use."})
        contact_email = _clean_email(request.data.get("contact_email"), "contact_email")

        admin_email = str(request.data.get("admin_email") or "").strip().lower()
        admin_name = str(request.data.get("admin_full_name") or "").strip()
        admin_password = request.data.get("admin_password") or ""
        if admin_email or admin_name or admin_password:
            if not admin_email or not admin_name or not admin_password:
                raise ValidationError(
                    "The first agency admin needs an email, full name, and temporary password."
                )
            admin_email = _clean_email(admin_email, "admin_email")
            if User.objects.filter(email__iexact=admin_email).exists():
                raise ValidationError({"admin_email": "A user with this email already exists."})
            validate_password(admin_password)

        with transaction.atomic():
            org = Organization.objects.create(name=name, slug=slug, contact_email=contact_email)
            detail = f"Created {org.name}"
            if admin_email:
                admin = User.objects.create_user(
                    email=admin_email, password=admin_password, full_name=admin_name
                )
                OrganizationMembership.objects.create(organization=org, user=admin, role=AGENCY_ADMIN)
                detail += f" with agency admin {admin_email}"
            record_audit(request, "organization_create", org, detail)
        return Response(organization_payload(org), status=201)


class OrganizationDetailView(TenantMixin, APIView):
    permission_classes = [PlatformOnly]
    allow_missing_org = True

    def get(self, request, org_id):
        org = Organization.objects.filter(id=org_id).prefetch_related("global_grants").first()
        if org is None:
            return Response(
                {"error": {"code": "not_found", "message": "Organization not found.", "details": {}}}, status=404
            )
        return Response(organization_payload(org))

    def patch(self, request, org_id):
        org = Organization.objects.filter(id=org_id).first()
        if org is None:
            return Response(
                {"error": {"code": "not_found", "message": "Organization not found.", "details": {}}}, status=404
            )
        details = []
        if "name" in request.data:
            name = str(request.data.get("name") or "").strip()
            if not name or len(name) > 200:
                raise ValidationError({"name": "Name must be between 1 and 200 characters."})
            org.name = name
            details.append(f"name {name}")
        if "slug" in request.data:
            slug = str(request.data.get("slug") or "").strip().lower() or slugify(org.name)
            if not slug:
                raise ValidationError({"slug": "Provide a slug for this organization."})
            if Organization.objects.filter(slug=slug).exclude(id=org.id).exists():
                raise ValidationError({"slug": "That organization slug is already in use."})
            org.slug = slug
            details.append(f"slug {slug}")
        if "contact_email" in request.data:
            org.contact_email = _clean_email(request.data.get("contact_email"), "contact_email")
            details.append(f"contact {org.contact_email or 'cleared'}")
        if "retention_days" in request.data:
            try:
                days = int(request.data["retention_days"])
            except (TypeError, ValueError):
                raise ValidationError({"retention_days": "Enter a whole number of days."})
            if days < 30 or days > 3650:
                raise ValidationError({"retention_days": "Retention must be between 30 and 3650 days."})
            org.retention_days = days
            details.append(f"retention {days}d")
        if "privacy_notice" in request.data:
            org.privacy_notice = str(request.data["privacy_notice"])[:5000]
            details.append("privacy notice")
        if "allow_client_see_compensation" in request.data:
            org.allow_client_see_compensation = bool(request.data["allow_client_see_compensation"])
            details.append(f"client compensation {org.allow_client_see_compensation}")
        if "status" in request.data:
            status = request.data.get("status")
            if status not in Organization.Status.values:
                raise ValidationError({"status": "Unknown organization status."})
            previous = org.status
            org.status = status
            org.status_reason = str(request.data.get("status_reason") or "").strip()[:200]
            if status != previous:
                org.status_changed_at = timezone.now()
            details.append(
                f"status {previous} to {status}"
                + (f": {org.status_reason}" if org.status_reason else "")
            )
        org.save()
        record_audit(request, "organization_update", org, ", ".join(details) or "No changes", organization=org)
        return Response(organization_payload(org))


class GlobalAccessView(TenantMixin, APIView):
    permission_classes = [PlatformOnly]
    allow_missing_org = True

    def _organization(self, org_id):
        return Organization.objects.filter(id=org_id).first()

    def get(self, request, org_id):
        org = self._organization(org_id)
        if org is None:
            return Response(
                {"error": {"code": "not_found", "message": "Organization not found.", "details": {}}}, status=404
            )
        return Response({"scopes": sorted(org.global_grants.values_list("scope", flat=True))})

    def put(self, request, org_id):
        org = self._organization(org_id)
        if org is None:
            return Response(
                {"error": {"code": "not_found", "message": "Organization not found.", "details": {}}}, status=404
            )
        raw = request.data.get("scopes")
        if not isinstance(raw, list):
            raise ValidationError({"scopes": "Send a list of scopes."})
        known = set(GlobalDataGrant.Scope.values)
        scopes: list[str] = []
        for item in raw:
            scope = str(item)
            if scope not in known:
                raise ValidationError({"scopes": f"Unknown scope: {scope}."})
            if scope not in scopes:
                scopes.append(scope)
        with transaction.atomic():
            org.global_grants.exclude(scope__in=scopes).delete()
            existing = set(org.global_grants.values_list("scope", flat=True))
            GlobalDataGrant.objects.bulk_create(
                [
                    GlobalDataGrant(organization=org, scope=scope, granted_by=request.user)
                    for scope in scopes
                    if scope not in existing
                ]
            )
        record_audit(
            request,
            "global_access",
            org,
            ", ".join(scopes) or "none",
            organization=org,
        )
        return Response({"scopes": sorted(scopes)})


class UserAdminView(TenantMixin, APIView):
    permission_classes = [AgencyAdminOnly]

    def get(self, request):
        org = require_org(request)
        memberships = OrganizationMembership.objects.filter(organization=org).select_related("user")
        return Response(
            [
                {
                    "id": str(row.user_id),
                    "email": row.user.email,
                    "full_name": row.user.full_name,
                    "role": row.role,
                    "is_active": row.is_active and row.user.is_active,
                    "client_companies": [
                        str(item.company_id)
                        for item in ClientMembership.objects.filter(user=row.user, organization=org)
                    ],
                }
                for row in memberships
            ]
        )

    def post(self, request):
        org = require_org(request)
        email = (request.data.get("email") or "").strip().lower()
        full_name = (request.data.get("full_name") or "").strip()
        role = request.data.get("role") or ""
        password = request.data.get("password") or ""
        if role not in {choice for choice, _label in OrganizationMembership.Role.choices}:
            raise ValidationError({"role": "Unknown role."})
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError({"email": "A user with this email already exists."})
        if not email or not full_name:
            raise ValidationError("Email and full name are required.")
        validate_password(password)
        user = User.objects.create_user(email=email, password=password, full_name=full_name)
        OrganizationMembership.objects.create(organization=org, user=user, role=role)
        if role in CLIENT_ROLES:
            company_id = request.data.get("client_company_id")
            company = ClientCompany.objects.filter(organization=org, id=company_id).first()
            if company is None:
                raise ValidationError({"client_company_id": "Choose a client company for this user."})
            ClientMembership.objects.create(organization=org, company=company, user=user, role=role)
        record_audit(request, "user_create", user, f"Role {role}")
        return Response(user_payload(user, org), status=201)


class UserRoleView(TenantMixin, APIView):
    permission_classes = [AgencyAdminOnly]

    def patch(self, request, user_id):
        org = require_org(request)
        membership = OrganizationMembership.objects.filter(organization=org, user_id=user_id).select_related("user").first()
        if membership is None:
            return Response({"error": {"code": "not_found", "message": "User not found.", "details": {}}}, status=404)
        role = request.data.get("role")
        if role:
            if role not in {choice for choice, _label in OrganizationMembership.Role.choices}:
                raise ValidationError({"role": "Unknown role."})
            if membership.role == AGENCY_ADMIN and role != AGENCY_ADMIN:
                admins = OrganizationMembership.objects.filter(organization=org, role=AGENCY_ADMIN, is_active=True).count()
                if admins <= 1:
                    raise ValidationError("The organization needs at least one agency admin.")
            membership.role = role
        if "is_active" in request.data:
            membership.is_active = bool(request.data["is_active"])
            if membership.user_id == request.user.id and not membership.is_active:
                raise ValidationError("You cannot deactivate your own account.")
        membership.save()
        record_audit(request, "role_change", membership.user, membership.role)
        return Response(user_payload(membership.user, org))


class RecruiterTrackRecordView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def get(self, request):
        org = require_org(request)
        is_admin = request.user.is_platform_admin or (
            request.membership is not None and request.membership.role == AGENCY_ADMIN
        )
        requested = request.query_params.get("user_id")
        if requested and not is_admin and str(request.user.id) != str(requested):
            raise PermissionDenied("You can only open your own track record.")
        memberships = (
            OrganizationMembership.objects.filter(organization=org, is_active=True, role__in=AGENCY_ROLES)
            .select_related("user")
            .order_by("user__full_name")
        )
        if not is_admin:
            memberships = memberships.filter(user=request.user)
        elif requested:
            memberships = memberships.filter(user_id=requested)
        results = [_track_record(org, membership.user) for membership in memberships]
        return Response({"scope": "team" if is_admin else "self", "results": results})


def _track_record(org, user) -> dict:
    from apps.audit.models import AuditEvent
    from apps.candidates.models import Candidate
    from apps.jobs.models import Job
    from apps.pipeline.models import CandidateShare, CandidateSubmission, Interview
    from apps.resumes.models import ResumeDocument

    jobs_posted = Job.objects.filter(organization=org, created_by=user).count()
    jobs_assigned = Job.objects.filter(organization=org, assigned_recruiter=user).count()
    resumes_uploaded = ResumeDocument.objects.filter(organization=org, uploaded_by=user).count()
    candidates_created = Candidate.objects.filter(
        organization=org, created_by=user, merged_into__isnull=True
    ).count()
    submissions = CandidateSubmission.objects.filter(organization=org, submitted_by=user)
    shares = CandidateShare.objects.filter(
        organization=org, shared_by=user, revoked_at__isnull=True
    ).count()
    scheduled = Interview.objects.filter(organization=org, created_by=user).count()
    completed = Interview.objects.filter(
        organization=org, feedback_by=user, status=Interview.Status.COMPLETED
    )
    screening_passed = completed.filter(
        level=Interview.Level.SCREENING, outcome=Interview.Outcome.PASSED
    ).count()
    levels_passed = completed.filter(
        outcome=Interview.Outcome.PASSED, level__in=[Interview.Level.L1, Interview.Level.L2, Interview.Level.L3, Interview.Level.L4, Interview.Level.L5]
    ).count()
    feedback_count = completed.count()
    passed_count = completed.filter(outcome=Interview.Outcome.PASSED).count()
    offers = submissions.filter(
        stage__in=[CandidateSubmission.Stage.OFFER, CandidateSubmission.Stage.HIRED]
    ).count()
    placements = submissions.filter(stage=CandidateSubmission.Stage.HIRED).count()
    average_rating = completed.aggregate(value=Avg("rating"))["value"]
    activity = AuditEvent.objects.filter(organization=org, actor=user).order_by("-created_at")[:20]
    effort_points = (
        jobs_posted * 3 + resumes_uploaded + submissions.count() * 2 + completed.count() * 2 + placements * 10
    )
    return {
        "user": {"id": str(user.id), "full_name": user.full_name, "email": user.email},
        "effort": {
            "jobs_posted": jobs_posted,
            "jobs_assigned": jobs_assigned,
            "resumes_uploaded": resumes_uploaded,
            "candidates_created": candidates_created,
            "submissions": submissions.count(),
            "shares": shares,
            "interviews_scheduled": scheduled,
            "interviews_completed": feedback_count,
            "effort_points": effort_points,
        },
        "achievement": {
            "screening_passed": screening_passed,
            "levels_passed": levels_passed,
            "offers": offers,
            "placements": placements,
            "average_interview_rating": round(float(average_rating), 2) if average_rating is not None else None,
            "pass_rate": round((passed_count / feedback_count) * 100, 1) if feedback_count else None,
            "feedback_count": feedback_count,
        },
        "activity": [
            {
                "action": row.action,
                "object_type": row.object_type,
                "object_id": row.object_id,
                "detail": row.detail,
                "created_at": row.created_at,
            }
            for row in activity
        ],
    }


class ProcessingJobListView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def get(self, request):
        org = require_org(request)
        qs = ProcessingJob.objects.filter(organization=org)
        status = request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([_job(row) for row in page])


class ProcessingJobRetryView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request, job_id):
        org = require_org(request)
        job = ProcessingJob.objects.filter(organization=org, id=job_id).first()
        if job is None:
            return Response({"error": {"code": "not_found", "message": "Processing job not found.", "details": {}}}, status=404)
        if job.status not in {ProcessingJob.Status.FAILED, ProcessingJob.Status.CANCELLED}:
            raise ValidationError("Only failed jobs can be retried.")
        from apps.processing.services import requeue

        requeue(job)
        record_audit(request, "processing_retry", job, job.kind)
        job.refresh_from_db()
        return Response(_job(job))


class AIUsageView(TenantMixin, APIView):
    permission_classes = [AgencyAdminOnly]

    def get(self, request):
        org = require_org(request)
        rows = AIUsageRecord.objects.filter(organization=org)
        totals = rows.aggregate(input_tokens=Sum("input_tokens"), output_tokens=Sum("output_tokens"), cost=Sum("cost_usd"))
        recent = [
            {
                "id": str(row.id),
                "operation": row.operation,
                "provider": row.provider,
                "model": row.model,
                "prompt_version": row.prompt_version,
                "schema_version": row.schema_version,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "cost_usd": row.cost_usd,
                "status": row.status,
                "error_code": row.error_code,
                "created_at": row.created_at,
            }
            for row in rows[:50]
        ]
        return Response(
            {"totals": totals, "results": recent, "live_provider_tested": _live_ai_tested(org)}
        )


class AIProviderTestView(TenantMixin, APIView):
    permission_classes = [AgencyAdminOnly]

    def post(self, request):
        from django.conf import settings as dj_settings
        from django.core.cache import cache

        from apps.ai.provider import ProviderError
        from apps.ai.service import execute

        org = require_org(request)
        if dj_settings.AI_PROVIDER == "deterministic":
            return Response(
                {
                    "status": "deterministic_dev",
                    "live": False,
                    "message": "The desk is using the deterministic dev provider. Set AI_PROVIDER=hosted and AI_API_KEY to test a live model.",
                }
            )
        try:
            result = execute(org, "provider_check", "generate_embedding", "sable provider check")
        except ProviderError as exc:
            record_audit(request, "ai_provider_test", org, getattr(exc, "code", "provider_error"))
            return Response(
                {
                    "status": "failed",
                    "live": False,
                    "code": getattr(exc, "code", "provider_error"),
                    "message": str(exc),
                },
                status=400,
            )
        cache.set(_live_ai_cache_key(org), timezone.now().isoformat(), 60 * 60 * 24 * 30)
        record_audit(request, "ai_provider_test", org, f"{result.provider} {result.model} ok")
        return Response(
            {
                "status": "ok",
                "live": True,
                "provider": result.provider,
                "model": result.model,
                "latency_ms": (result.usage or {}).get("latency_ms"),
            }
        )


def _live_ai_cache_key(org) -> str:
    return f"sable:ai-live-test:{org.id}"


def _live_ai_tested(org) -> bool:
    from django.core.cache import cache

    return bool(cache.get(_live_ai_cache_key(org)))


class AuditListView(TenantMixin, APIView):
    permission_classes = [AgencyAdminOnly]

    def get(self, request):
        org = require_org(request)
        qs = AuditEvent.objects.filter(organization=org)
        action = request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)
        object_id = request.query_params.get("object_id")
        if object_id:
            qs = qs.filter(object_id=object_id)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs.select_related("actor"), request, view=self)
        return paginator.get_paginated_response(
            [
                {
                    "id": str(row.id),
                    "action": row.action,
                    "object_type": row.object_type,
                    "object_id": row.object_id,
                    "detail": row.detail,
                    "actor": row.actor.email if row.actor_id else None,
                    "created_at": row.created_at,
                }
                for row in page
            ]
        )


class RetentionView(TenantMixin, APIView):
    permission_classes = [AgencyAdminOnly]

    def post(self, request):
        org = require_org(request)
        dry_run = bool(request.data.get("dry_run", True))
        cutoff = timezone.now() - timezone.timedelta(days=org.retention_days)
        from apps.candidates.models import Candidate

        qs = Candidate.objects.filter(organization=org, deletion_requested_at__isnull=False, deletion_requested_at__lte=cutoff)
        ids = [str(item) for item in qs.values_list("id", flat=True)[:200]]
        if dry_run:
            return Response({"dry_run": True, "count": qs.count(), "candidate_ids": ids})
        retention_sweep.delay()
        record_audit(request, "retention_run", org, f"Queued purge for {len(ids)} candidates")
        return Response({"dry_run": False, "queued": True, "count": len(ids)})


def _job(row: ProcessingJob) -> dict:
    return {
        "id": str(row.id),
        "kind": row.kind,
        "status": row.status,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "last_error": row.last_error,
        "provider": row.provider,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }
