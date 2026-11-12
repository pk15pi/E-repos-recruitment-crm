"""Resume pipeline: store, scan, extract, call the AI adapter, and leave a review draft."""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.ai.provider import ProviderConfigError, ProviderError, ProviderRateLimitError, ProviderTimeoutError
from apps.ai.service import RetryableError, execute
from apps.common.storage import get_storage
from apps.processing.models import ProcessingJob
from apps.resumes.extract_text import TextExtractError, chunk_text, extract_document
from apps.resumes.files import scan_bytes
from apps.resumes.models import CandidateFieldEvidence, ResumeDocument, ResumeExtraction, ResumeTextChunk
from apps.resumes.normalize import normalize_resume

logger = logging.getLogger(__name__)


def run_resume_job(job_id: str) -> None:
    with transaction.atomic():
        job = ProcessingJob.objects.select_for_update().get(id=job_id)
        if job.status in {ProcessingJob.Status.SUCCEEDED, ProcessingJob.Status.RUNNING}:
            return
        job.status = ProcessingJob.Status.RUNNING
        job.attempts += 1
        job.started_at = timezone.now()
        job.save(update_fields=["status", "attempts", "started_at", "updated_at"])
    try:
        _process(job)
    except RetryableError:
        raise
    except Exception as exc:
        message = str(exc)[:400] if isinstance(exc, (TextExtractError, ProviderConfigError, ProviderError)) else "Resume processing failed."
        _fail(job, message)


def _process(job: ProcessingJob) -> None:
    resume = ResumeDocument.objects.get(id=job.target_id, organization=job.organization)
    storage = get_storage()
    key = resume.quarantine_key or resume.storage_key
    data = storage.open(key)
    resume.status = ResumeDocument.Status.SCANNING
    resume.save(update_fields=["status", "updated_at"])
    scan_status, scan_message = scan_bytes(data)
    resume.scan_status = scan_status
    if scan_status == "infected":
        resume.status = ResumeDocument.Status.REJECTED
        resume.error_message = scan_message
        resume.save(update_fields=["scan_status", "status", "error_message", "updated_at"])
        _succeed(job)
        return
    if scan_status == "error":
        resume.status = ResumeDocument.Status.REJECTED
        resume.error_message = scan_message
        resume.save(update_fields=["scan_status", "status", "error_message", "updated_at"])
        _succeed(job)
        return
    private_key = f"org/{resume.organization_id}/resumes/{resume.id}"
    if resume.storage_key != private_key:
        storage.save(private_key, data, resume.content_type or "application/octet-stream")
        if resume.quarantine_key and resume.quarantine_key != private_key:
            storage.delete(resume.quarantine_key)
        resume.storage_key = private_key
        resume.quarantine_key = ""
    resume.status = ResumeDocument.Status.EXTRACTING
    resume.save(update_fields=["storage_key", "quarantine_key", "status", "scan_status", "updated_at"])
    try:
        text, pages, page_count = extract_document(resume.detected_type, data)
    except TextExtractError as exc:
        raise TextExtractError(str(exc)) from exc
    resume.extracted_text = text
    resume.page_count = page_count
    resume.save(update_fields=["extracted_text", "page_count", "updated_at"])
    ResumeTextChunk.objects.filter(resume=resume).delete()
    for index, chunk in enumerate(chunk_text(pages)):
        ResumeTextChunk.objects.create(
            organization=resume.organization,
            resume=resume,
            chunk_index=index,
            page_number=chunk.get("page"),
            text=chunk["text"],
        )
    try:
        result = execute(resume.organization, "extract_resume_fields", "extract_resume_fields", text, pages)
    except (ProviderTimeoutError, ProviderRateLimitError) as exc:
        raise RetryableError(str(exc)) from exc
    except ProviderConfigError:
        raise
    normalized = normalize_resume(result.data, text, pages)
    from apps.candidates.services import find_duplicates

    duplicates = find_duplicates(resume.organization, normalized["profile"], exclude_id=resume.candidate_id)
    extraction = ResumeExtraction.objects.create(
        organization=resume.organization,
        resume=resume,
        candidate=resume.candidate,
        status=ResumeExtraction.Status.DRAFT,
        schema_version=result.schema_version,
        prompt_version=result.prompt_version,
        provider=result.provider,
        model=result.model,
        normalized=normalized["profile"],
        warnings=list(result.warnings) + normalized["warnings"],
        usage=result.usage,
        raw_output=result.data,
        duplicates=duplicates,
    )
    CandidateFieldEvidence.objects.filter(extraction__resume=resume, candidate__isnull=True).delete()
    CandidateFieldEvidence.objects.bulk_create(
        [
            CandidateFieldEvidence(
                organization=resume.organization,
                extraction=extraction,
                candidate=resume.candidate,
                field_path=field["path"],
                value_text="" if field["value"] is None else str(field["value"])[:2000],
                quote=field["quote"],
                page_number=field["page"],
                confidence=field["confidence"],
                status=field["status"],
            )
            for field in normalized["fields"]
        ]
    )
    resume.status = ResumeDocument.Status.NEEDS_REVIEW
    resume.error_message = ""
    resume.save(update_fields=["status", "error_message", "updated_at"])
    job.provider = result.provider
    _succeed(job)


def _succeed(job: ProcessingJob) -> None:
    job.status = ProcessingJob.Status.SUCCEEDED
    job.finished_at = timezone.now()
    job.last_error = ""
    job.save(update_fields=["status", "finished_at", "last_error", "provider", "updated_at"])


def _fail(job: ProcessingJob, message: str) -> None:
    logger.error("resume processing failed job=%s", job.id)
    job.last_error = message[:400]
    job.finished_at = timezone.now()
    if job.attempts < job.max_attempts and message in {"Resume processing failed."}:
        job.status = ProcessingJob.Status.QUEUED
    else:
        job.status = ProcessingJob.Status.FAILED
        ResumeDocument.objects.filter(id=job.target_id).update(status=ResumeDocument.Status.FAILED, error_message=message[:400])
    job.save(update_fields=["status", "last_error", "finished_at", "updated_at"])
