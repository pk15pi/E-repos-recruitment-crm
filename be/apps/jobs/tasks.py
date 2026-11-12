import random

from celery import shared_task
from django.utils import timezone

from apps.ai.provider import ProviderError
from apps.ai.service import execute
from apps.jobs.models import Job, JobRequirement
from apps.processing.models import ProcessingJob

WORK_MODES = {"remote", "hybrid", "onsite"}
EMPLOYMENT = {"full_time", "part_time", "contract", "internship", "temporary"}


@shared_task(bind=True, max_retries=3)
def analyze_job_task(self, job_id: str):
    job = ProcessingJob.objects.get(id=job_id)
    if job.status == ProcessingJob.Status.SUCCEEDED:
        return
    job.status = ProcessingJob.Status.RUNNING
    job.attempts += 1
    job.started_at = timezone.now()
    job.save(update_fields=["status", "attempts", "started_at", "updated_at"])
    vacancy = Job.objects.get(id=job.target_id, organization=job.organization)
    try:
        result = execute(vacancy.organization, "analyze_job_description", "analyze_job_description", vacancy.original_description)
        _apply_analysis(vacancy, result)
        job.status = ProcessingJob.Status.SUCCEEDED
        job.provider = result.provider
        job.finished_at = timezone.now()
        job.last_error = ""
        job.save(update_fields=["status", "provider", "finished_at", "last_error", "updated_at"])
    except ProviderError as exc:
        if getattr(exc, "retryable", False) and job.attempts < job.max_attempts:
            job.status = ProcessingJob.Status.QUEUED
            job.save(update_fields=["status", "updated_at"])
            raise self.retry(exc=exc, countdown=min(90, 2 ** self.request.retries) + random.random())
        vacancy.analysis_status = Job.AnalysisStatus.FAILED
        vacancy.analysis_error = str(exc)[:400]
        vacancy.save(update_fields=["analysis_status", "analysis_error", "updated_at"])
        job.status = ProcessingJob.Status.FAILED
        job.last_error = str(exc)[:400]
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "last_error", "finished_at", "updated_at"])


def _apply_analysis(vacancy: Job, result) -> None:
    data = result.data or {}
    overrides = vacancy._analysis_overrides if hasattr(vacancy, "_analysis_overrides") else {}
    # Overrides are stored on the processing side via a transient attribute. Persisted overrides win below.
    if not vacancy.title:
        vacancy.title = (data.get("title") or "")[:200]
    for field in ("location", "work_mode", "employment_type", "seniority", "domain"):
        if not getattr(vacancy, field) and data.get(field):
            setattr(vacancy, field, data.get(field) or "")
    if vacancy.min_experience_months is None and data.get("min_experience_years") is not None:
        vacancy.min_experience_months = int(float(data["min_experience_years"]) * 12)
    if vacancy.max_experience_months is None and data.get("max_experience_years") is not None:
        vacancy.max_experience_months = int(float(data["max_experience_years"]) * 12)
    if vacancy.notice_period_days is None and data.get("notice_period_days") is not None:
        vacancy.notice_period_days = int(data["notice_period_days"])
    vacancy.provider = result.provider
    vacancy.model = result.model
    vacancy.prompt_version = result.prompt_version
    vacancy.schema_version = result.schema_version
    vacancy.analysis_status = Job.AnalysisStatus.READY
    vacancy.analysis_error = ""
    if vacancy.status == Job.Status.DRAFT:
        vacancy.status = Job.Status.OPEN
    vacancy.save()
    vacancy.requirements.all().delete()
    for index, item in enumerate(data.get("requirements") or []):
        kind = item.get("kind")
        priority = item.get("priority")
        if kind not in JobRequirement.Kind.values or priority not in JobRequirement.Priority.values:
            continue
        value = (item.get("value") or "")[:500]
        if kind == "work_mode" and value not in WORK_MODES:
            continue
        if kind == "employment_type" and value not in EMPLOYMENT:
            continue
        JobRequirement.objects.create(
            organization=vacancy.organization,
            job=vacancy,
            kind=kind,
            label=(item.get("label") or value or kind)[:200],
            value=value,
            priority=priority,
            source="extracted",
            sort_order=index,
        )


@shared_task(bind=True, max_retries=2)
def match_job_task(self, job_id: str):
    from apps.jobs.matching import match_job

    job = ProcessingJob.objects.get(id=job_id)
    if job.status == ProcessingJob.Status.RUNNING:
        return
    job.status = ProcessingJob.Status.RUNNING
    job.attempts += 1
    job.started_at = timezone.now()
    job.save(update_fields=["status", "attempts", "started_at", "updated_at"])
    try:
        vacancy = Job.objects.get(id=job.target_id, organization=job.organization)
        match_job(vacancy)
        job.status = ProcessingJob.Status.SUCCEEDED
        job.finished_at = timezone.now()
        job.last_error = ""
        job.save(update_fields=["status", "finished_at", "last_error", "updated_at"])
    except Exception as exc:
        job.status = ProcessingJob.Status.FAILED
        job.last_error = "Matching failed." if not isinstance(exc, ProviderError) else str(exc)[:400]
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "last_error", "finished_at", "updated_at"])
        if isinstance(exc, ProviderError) and getattr(exc, "retryable", False) and self.request.retries < 2:
            job.status = ProcessingJob.Status.QUEUED
            job.save(update_fields=["status", "updated_at"])
            raise self.retry(exc=exc, countdown=5 + random.random())
