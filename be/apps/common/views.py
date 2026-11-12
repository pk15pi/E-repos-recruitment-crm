from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.candidates.models import Candidate
from apps.common.permissions import AgencyAdminOnly, AgencyOnly, IsAuthenticatedInOrg, TenantMixin
from apps.common.scoping import candidate_queryset
from apps.common.tenancy import is_client, require_org
from apps.jobs.models import Job, MatchResult
from apps.pipeline.models import CandidateSubmission, Interview
from apps.processing.models import ProcessingJob
from apps.resumes.models import ResumeDocument


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        checks = {"database": "ok", "cache": "ok", "storage": "ok", "ai": "not_configured"}
        try:
            from django.db import connection

            connection.ensure_connection()
        except Exception:
            checks["database"] = "error"
        try:
            from django.core.cache import cache

            cache.set("sable-health", "1", 5)
            if cache.get("sable-health") != "1":
                checks["cache"] = "error"
        except Exception:
            checks["cache"] = "error"
        try:
            from apps.common.storage import get_storage

            checks["storage"] = "ok" if get_storage().check() else "error"
        except Exception:
            checks["storage"] = "error"
        from django.conf import settings

        if settings.AI_PROVIDER == "hosted" and settings.AI_API_KEY:
            checks["ai"] = "configured_untested"
        elif settings.AI_PROVIDER == "deterministic":
            checks["ai"] = "deterministic_dev"
        status_code = 200 if checks["database"] == "ok" else 503
        return Response({"status": "ok" if status_code == 200 else "degraded", "checks": checks}, status=status_code)


class DashboardView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request):
        org = require_org(request)
        now = timezone.now()
        candidates = candidate_queryset(request, include_archived=False)
        submissions = CandidateSubmission.objects.filter(organization=org)
        interviews = Interview.objects.filter(organization=org)
        if is_client(request):
            from apps.common.scoping import client_company_ids

            company_ids = client_company_ids(request)
            submissions = submissions.filter(client_company_id__in=company_ids)
            interviews = interviews.filter(submission__client_company_id__in=company_ids)
            jobs = Job.objects.filter(organization=org, client_company_id__in=company_ids, status=Job.Status.OPEN)
            return Response(
                {
                    "role_scope": "client",
                    "shared_candidates": candidates.count(),
                    "open_vacancies": jobs.count(),
                    "interviews": interviews.filter(status=Interview.Status.SCHEDULED, scheduled_at__gte=now).count(),
                    "pending_feedback": interviews.filter(status=Interview.Status.COMPLETED, feedback="").count(),
                }
            )
        from apps.candidates.models import Task

        tasks = Task.objects.filter(organization=org, status=Task.Status.OPEN)
        if not request.user.is_platform_admin and request.membership and request.membership.role != "agency_admin":
            tasks = tasks.filter(Q(assigned_to=request.user) | Q(assigned_to__isnull=True))
        data = {
            "role_scope": "agency",
            "candidates_on_file": candidates.count(),
            "awaiting_review": ResumeDocument.objects.filter(
                organization=org, status=ResumeDocument.Status.NEEDS_REVIEW
            ).count(),
            "failed_jobs": ProcessingJob.objects.filter(organization=org, status=ProcessingJob.Status.FAILED).count(),
            "open_vacancies": Job.objects.filter(organization=org, status=Job.Status.OPEN).count(),
            "matches": MatchResult.objects.filter(organization=org).count(),
            "interviews": interviews.filter(status=Interview.Status.SCHEDULED, scheduled_at__gte=now).count(),
            "pending_feedback": interviews.filter(status=Interview.Status.COMPLETED, feedback="").count(),
            "follow_ups": tasks.filter(Q(due_at__isnull=True) | Q(due_at__lte=now + timezone.timedelta(days=7))).count(),
            "pipeline": list(
                submissions.values("stage").annotate(count=Count("id")).order_by("stage")
            ),
        }
        return Response(data)


class ReportsView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request):
        org = require_org(request)
        submissions = CandidateSubmission.objects.filter(organization=org)
        candidates = Candidate.objects.filter(organization=org, merged_into__isnull=True)
        if is_client(request):
            from apps.common.scoping import client_company_ids

            company_ids = client_company_ids(request)
            submissions = submissions.filter(client_company_id__in=company_ids)
            shared = candidate_queryset(request)
            return Response(
                {
                    "pipeline": list(submissions.values("stage").annotate(count=Count("id")).order_by("stage")),
                    "shared_candidates": shared.count(),
                }
            )
        return Response(
            {
                "pipeline": list(submissions.values("stage").annotate(count=Count("id")).order_by("stage")),
                "sources": list(
                    candidates.exclude(source="").values("source").annotate(count=Count("id")).order_by("-count")[:20]
                ),
                "verification": list(
                    candidates.values("verification_status").annotate(count=Count("id")).order_by("verification_status")
                ),
                "open_jobs": Job.objects.filter(organization=org, status=Job.Status.OPEN).count(),
            }
        )


class OrganizationSettingsView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request):
        org = require_org(request)
        return Response(_org_settings(org))

    def patch(self, request):
        self.permission_classes = [AgencyAdminOnly]
        # Re-check admin for writes.
        if not AgencyAdminOnly().has_permission(request, self):
            return Response(
                {"error": {"code": "permission_denied", "message": "Only an agency admin can change these settings.", "details": {}}},
                status=403,
            )
        org = require_org(request)
        if "retention_days" in request.data:
            days = int(request.data["retention_days"])
            if days < 30 or days > 3650:
                return Response(
                    {"error": {"code": "validation_error", "message": "Retention must be between 30 and 3650 days.", "details": {}}},
                    status=400,
                )
            org.retention_days = days
        if "privacy_notice" in request.data:
            org.privacy_notice = str(request.data["privacy_notice"])[:5000]
        if "allow_client_see_compensation" in request.data:
            org.allow_client_see_compensation = bool(request.data["allow_client_see_compensation"])
        org.save()
        from apps.common.audit import record_audit

        record_audit(request, "settings_update", org, "Organization settings updated")
        return Response(_org_settings(org))


def _org_settings(org):
    from django.conf import settings as dj_settings
    from django.core.cache import cache

    provider = dj_settings.AI_PROVIDER
    tested_at = cache.get(f"sable:ai-live-test:{org.id}")
    return {
        "id": str(org.id),
        "name": org.name,
        "retention_days": org.retention_days,
        "privacy_notice": org.privacy_notice,
        "allow_client_see_compensation": org.allow_client_see_compensation,
        "status": org.status,
        "read_only": org.read_only,
        "status_reason": org.status_reason,
        "ai_provider": provider,
        "ai_provider_label": (
            "Deterministic dev provider (not a hosted model)"
            if provider == "deterministic"
            else "Hosted model API"
        ),
        "ai_live_calls_tested": bool(tested_at),
        "ai_live_tested_at": tested_at,
        "scan_status_policy": "skipped_unconfigured" if dj_settings.ALLOW_UNSCANNED_UPLOADS and not dj_settings.CLAMAV_HOST else "enforced",
    }
