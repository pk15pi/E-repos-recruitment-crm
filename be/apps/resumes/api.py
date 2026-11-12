import mimetypes
import re

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.ai.constants import DETERMINISTIC_LABEL
from apps.candidates.models import Candidate
from apps.candidates.services import apply_profile, find_duplicates
from apps.candidates.validate import clean_profile
from apps.common.audit import record_audit
from apps.common.exceptions import Conflict
from apps.common.permissions import AgencyOnly, IsAuthenticatedInOrg, TenantMixin
from apps.common.scoping import can_download_resume, candidate_queryset
from apps.common.storage import get_storage
from apps.common.tenancy import attach_tenant, is_client, require_org
from apps.processing.models import ProcessingJob
from apps.processing.services import enqueue
from apps.resumes.files import expand_zip, scan_bytes, sha256, sniff
from apps.resumes.models import ResumeDocument, ResumeExtraction
from apps.resumes.tasks import embed_candidate_task, process_resume_task

signer = TimestampSigner(salt="sable-resume-download")


class UploadThrottle(UserRateThrottle):
    scope = "upload"


def _provider_label(name: str) -> str:
    if name == "deterministic":
        return DETERMINISTIC_LABEL
    if name == "hosted":
        return "Hosted model API"
    return name or "Unknown provider"


class ResumeUploadView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [UploadThrottle]

    def post(self, request):
        uploads = request.FILES.getlist("files") or request.FILES.getlist("file")
        if not uploads:
            raise ValidationError({"file": "Choose at least one file."})
        items = []
        for upload in uploads:
            data = upload.read()
            items.extend(_accept_upload(request, upload.name, data))
        record_audit(request, "resume_upload", request.organization, f"{len(items)} file(s)")
        return Response({"items": items}, status=201)


def _accept_upload(request, filename: str, data: bytes) -> list[dict]:
    try:
        kind = sniff(data, filename)
    except ValidationError as exc:
        return [{"filename": filename, "status": "rejected", "error": _error_text(exc), "resume_id": None}]
    scan_status, scan_message = scan_bytes(data)
    if scan_status == "infected":
        return [{"filename": filename, "status": "rejected", "error": scan_message, "resume_id": None}]
    if kind == "zip":
        if scan_status == "error":
            return [{"filename": filename, "status": "rejected", "error": scan_message, "resume_id": None}]
        try:
            members = expand_zip(data)
        except ValidationError as exc:
            return [{"filename": filename, "status": "rejected", "error": _error_text(exc), "resume_id": None}]
        items = []
        for member_name, member_data in members:
            items.extend(_accept_upload(request, member_name, member_data))
        return items
    if scan_status == "error":
        return [{"filename": filename, "status": "rejected", "error": scan_message, "resume_id": None}]
    digest = sha256(data)
    duplicate = (
        ResumeDocument.objects.filter(organization=request.organization, sha256=digest)
        .exclude(status=ResumeDocument.Status.REJECTED)
        .order_by("created_at")
        .first()
    )
    resume = ResumeDocument.objects.create(
        organization=request.organization,
        uploaded_by=request.user,
        original_filename=filename[:255],
        content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        byte_size=len(data),
        sha256=digest,
        detected_type=kind,
        status=ResumeDocument.Status.QUARANTINED,
        scan_status=ResumeDocument.ScanStatus.PENDING,
    )
    key = f"org/{request.organization.id}/quarantine/{resume.id}"
    get_storage().save(key, data, resume.content_type)
    resume.quarantine_key = key
    resume.save(update_fields=["quarantine_key", "updated_at"])
    enqueue(
        process_resume_task,
        organization=request.organization,
        kind=ProcessingJob.Kind.RESUME_PARSE,
        target_type="resume",
        target_id=str(resume.id),
        idempotency_key=f"resume:{resume.id}:parse:{resume.parse_generation}",
        provider=settings.AI_PROVIDER,
    )
    resume.refresh_from_db()
    return [
        {
            "filename": filename,
            "resume_id": str(resume.id),
            "status": resume.status,
            "scan_status": resume.scan_status,
            "error": resume.error_message,
            "duplicate_of": str(duplicate.id) if duplicate else None,
            "duplicate_warning": "A file with the same contents is already on file." if duplicate else None,
        }
    ]


def _error_text(exc: ValidationError) -> str:
    detail = exc.detail
    if isinstance(detail, list):
        return str(detail[0])
    if isinstance(detail, dict):
        first = next(iter(detail.values()))
        return str(first[0] if isinstance(first, list) else first)
    return str(detail)


class ResumeDetailView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request, resume_id):
        resume = _authorized_resume(request, resume_id)
        return Response(_resume_payload(resume))


class ResumeStatusView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request, resume_id):
        resume = _authorized_resume(request, resume_id)
        job = ProcessingJob.objects.filter(target_id=str(resume.id), kind=ProcessingJob.Kind.RESUME_PARSE).order_by("-created_at").first()
        return Response(
            {
                "resume_id": str(resume.id),
                "status": resume.status,
                "scan_status": resume.scan_status,
                "error_message": resume.error_message,
                "processing": None
                if job is None
                else {"id": str(job.id), "status": job.status, "attempts": job.attempts, "last_error": job.last_error},
            }
        )


class ResumeDraftView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def get(self, request, resume_id):
        resume = _authorized_resume(request, resume_id)
        return Response(_draft_payload(resume))

    def patch(self, request, resume_id):
        resume = _authorized_resume(request, resume_id)
        extraction = _latest_draft(resume)
        if extraction is None:
            raise ValidationError("There is no extraction draft to correct yet.")
        profile = clean_profile(request.data.get("profile") or request.data, partial=True)
        merged = {**extraction.normalized, **profile}
        extraction.normalized = merged
        extraction.save(update_fields=["normalized", "updated_at"])
        _replace_evidence(extraction, merged)
        return Response(_draft_payload(resume))


class ResumeConfirmView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request, resume_id):
        resume = _authorized_resume(request, resume_id)
        extraction = _latest_draft(resume)
        if extraction is None:
            raise ValidationError("Nothing is ready to confirm. Wait for parsing to finish or retry it.")
        incoming = request.data.get("profile") or extraction.normalized
        profile = clean_profile(incoming, partial=True)
        merged = {**extraction.normalized, **profile}
        target = resume.candidate
        if request.data.get("candidate_id"):
            target = get_object_or_404(candidate_queryset(request), pk=request.data["candidate_id"])
        duplicates = find_duplicates(request.organization, merged, exclude_id=getattr(target, "id", None))
        blocking = [item for item in duplicates if item["blocking"]]
        if blocking and not request.data.get("acknowledge_duplicates"):
            return Response(
                {
                    "error": {
                        "code": "conflict",
                        "message": "A possible duplicate needs a person to review it before saving.",
                        "details": {"duplicates": blocking},
                    }
                },
                status=409,
            )
        overwrite = request.data.get("overwrite_verified") or []
        if not isinstance(overwrite, list):
            raise ValidationError({"overwrite_verified": "Provide a list of fields to overwrite."})
        if target is None:
            target = Candidate(organization=request.organization, created_by=request.user, status=Candidate.Status.ACTIVE)
            skipped = apply_profile(target, merged, request.user, mark_verified=True)
        else:
            skipped = apply_profile(
                target,
                merged,
                request.user,
                overwrite_verified=overwrite,
                lock_verified=True,
                mark_verified=True,
            )
        extraction.status = ResumeExtraction.Status.CONFIRMED
        extraction.candidate = target
        extraction.normalized = merged
        extraction.duplicates = duplicates
        extraction.save(update_fields=["status", "candidate", "normalized", "duplicates", "updated_at"])
        resume.candidate = target
        resume.status = ResumeDocument.Status.CONFIRMED
        resume.save(update_fields=["candidate", "status", "updated_at"])
        enqueue(
            embed_candidate_task,
            organization=request.organization,
            kind=ProcessingJob.Kind.EMBED,
            target_type="candidate",
            target_id=str(target.id),
            idempotency_key=f"candidate:{target.id}:embed:{resume.id}",
            provider=settings.AI_PROVIDER,
        )
        record_audit(request, "resume_confirm", target, "Extraction confirmed by a recruiter")
        return Response(
            {
                "candidate_id": str(target.id),
                "skipped_verified": skipped,
                "duplicates": duplicates,
                "provider": extraction.provider,
                "provider_label": _provider_label(extraction.provider),
            }
        )


class ResumeRetryView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request, resume_id):
        resume = _authorized_resume(request, resume_id)
        resume.parse_generation += 1
        resume.status = ResumeDocument.Status.STORED
        resume.error_message = ""
        resume.save(update_fields=["parse_generation", "status", "error_message", "updated_at"])
        job = enqueue(
            process_resume_task,
            organization=request.organization,
            kind=ProcessingJob.Kind.RESUME_PARSE,
            target_type="resume",
            target_id=str(resume.id),
            idempotency_key=f"resume:{resume.id}:parse:{resume.parse_generation}",
            provider=settings.AI_PROVIDER,
        )
        record_audit(request, "resume_retry", resume, "Manual retry")
        return Response({"processing_job_id": str(job.id), "status": job.status})


class ResumeDownloadView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def post(self, request, resume_id):
        resume = _authorized_resume(request, resume_id, download=True)
        disposition = request.data.get("disposition") or "attachment"
        if disposition not in {"attachment", "inline"}:
            raise ValidationError({"disposition": "Use attachment or inline."})
        storage = get_storage()
        filename = _safe_name(resume.original_filename)
        if settings.STORAGE_BACKEND in {"s3", "minio"} and hasattr(storage, "presigned_url"):
            url = storage.presigned_url(
                resume.storage_key,
                settings.DOWNLOAD_URL_TTL_SECONDS,
                filename,
                inline=disposition == "inline",
                content_type=resume.content_type,
            )
            mode = "presigned"
        else:
            token = signer.sign(f"{resume.id}:{request.user.id}")
            url = request.build_absolute_uri(f"/api/v1/resumes/signed/{token}/")
            if disposition == "inline":
                url += "?disposition=inline"
            mode = "proxy"
        record_audit(request, "resume_download", resume, "Download link issued")
        return Response({"url": url, "expires_in": settings.DOWNLOAD_URL_TTL_SECONDS, "mode": mode})


class SignedDownloadView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            raw = signer.unsign(token, max_age=settings.DOWNLOAD_URL_TTL_SECONDS)
        except SignatureExpired:
            return Response({"error": {"code": "expired", "message": "This download link has expired.", "details": {}}}, status=403)
        except BadSignature:
            return Response({"error": {"code": "invalid_token", "message": "This download link is not valid.", "details": {}}}, status=403)
        resume_id, user_id = raw.split(":", 1)
        from apps.accounts.models import User

        user = User.objects.filter(id=user_id, is_active=True).first()
        resume = ResumeDocument.objects.filter(id=resume_id).first()
        if user is None or resume is None or not resume.storage_key:
            raise NotFound()
        request.user = user
        attach_tenant(request)
        if not _can_access(request, resume, download=True):
            raise PermissionDenied("You cannot download this file.")
        data = get_storage().open(resume.storage_key)
        disposition = "inline" if request.query_params.get("disposition") == "inline" else "attachment"
        filename = _safe_name(resume.original_filename)
        response = HttpResponse(data, content_type=resume.content_type or "application/octet-stream")
        response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
        response["Cache-Control"] = "private, max-age=0, no-store"
        record_audit(request, "resume_download", resume, "File transferred")
        return response


class ResumeTextView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request, resume_id):
        resume = _authorized_resume(request, resume_id, download=True)
        record_audit(request, "resume_text_view", resume, "Text preview")
        pages = [{"page": chunk.page_number, "text": chunk.text} for chunk in resume.chunks.all()]
        if not pages and resume.extracted_text:
            pages = [{"page": 1, "text": resume.extracted_text}]
        return Response({"pages": pages})


def _authorized_resume(request, resume_id, download=False):
    resume = ResumeDocument.objects.filter(organization=require_org(request), id=resume_id).first()
    if resume is None or not _can_access(request, resume, download=download):
        raise NotFound()
    return resume


def _can_access(request, resume, download=False) -> bool:
    if getattr(request, "organization", None) is None or resume.organization_id != request.organization.id:
        return False
    if not is_client(request):
        return True
    if not resume.candidate_id:
        return False
    if download:
        return can_download_resume(request, resume.candidate)
    return candidate_queryset(request).filter(id=resume.candidate_id).exists()


def _latest_draft(resume: ResumeDocument):
    return resume.extractions.filter(status=ResumeExtraction.Status.DRAFT).order_by("-created_at").first() or resume.extractions.order_by("-created_at").first()


def _resume_payload(resume: ResumeDocument) -> dict:
    return {
        "id": str(resume.id),
        "filename": resume.original_filename,
        "detected_type": resume.detected_type,
        "status": resume.status,
        "scan_status": resume.scan_status,
        "error_message": resume.error_message,
        "page_count": resume.page_count,
        "byte_size": resume.byte_size,
        "candidate_id": str(resume.candidate_id) if resume.candidate_id else None,
        "created_at": resume.created_at,
    }


def _draft_payload(resume: ResumeDocument) -> dict:
    extraction = resume.extractions.order_by("-created_at").first()
    fields = []
    if extraction:
        fields = [
            {
                "path": row.field_path,
                "label": row.field_path.replace("_", " ").title(),
                "value": row.value_text,
                "status": row.status,
                "confidence": row.confidence,
                "quote": row.quote,
                "page": row.page_number,
                "low_confidence": bool(row.confidence is not None and row.confidence < 0.65),
            }
            for row in extraction.evidence.all()
        ]
    provider = extraction.provider if extraction else settings.AI_PROVIDER
    return {
        "resume": _resume_payload(resume),
        "ready": bool(extraction and resume.status in {ResumeDocument.Status.NEEDS_REVIEW, ResumeDocument.Status.CONFIRMED}),
        "provider": provider,
        "provider_label": _provider_label(provider),
        "model": extraction.model if extraction else "",
        "prompt_version": extraction.prompt_version if extraction else "",
        "schema_version": extraction.schema_version if extraction else "",
        "warnings": extraction.warnings if extraction else [],
        "duplicates": extraction.duplicates if extraction else [],
        "profile": extraction.normalized if extraction else None,
        "fields": fields,
    }


def _replace_evidence(extraction, profile: dict) -> None:
    from apps.resumes.models import CandidateFieldEvidence

    extraction.evidence.all().delete()
    rows = []
    for key, value in profile.items():
        if isinstance(value, (list, dict)):
            text = "" if not value else f"{len(value)} items" if isinstance(value, list) else "provided"
        else:
            text = "" if value is None else str(value)
        rows.append(
            CandidateFieldEvidence(
                organization=extraction.organization,
                extraction=extraction,
                candidate=extraction.candidate,
                field_path=str(key)[:120],
                value_text=text[:2000],
                status=CandidateFieldEvidence.Status.MISSING if text == "" else CandidateFieldEvidence.Status.EXTRACTED,
                confidence=None if text == "" else 1,
            )
        )
    CandidateFieldEvidence.objects.bulk_create(rows)


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name or "resume")
    return cleaned[:180] or "resume"
