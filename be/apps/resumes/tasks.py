import random

from celery import shared_task
from django.utils import timezone

from apps.ai.provider import ProviderError
from apps.ai.service import RetryableError, execute
from apps.candidates.models import Candidate
from apps.processing.models import ProcessingJob
from apps.resumes.pipeline import run_resume_job


@shared_task(bind=True, max_retries=3)
def process_resume_task(self, job_id: str):
    try:
        run_resume_job(job_id)
    except RetryableError as exc:
        job = ProcessingJob.objects.get(id=job_id)
        if job.attempts >= job.max_attempts:
            job.status = ProcessingJob.Status.FAILED
            job.last_error = str(exc)[:400]
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "last_error", "finished_at", "updated_at"])
            return
        job.status = ProcessingJob.Status.QUEUED
        job.save(update_fields=["status", "updated_at"])
        countdown = min(120, 2**self.request.retries) + random.random()
        raise self.retry(exc=exc, countdown=countdown)


@shared_task(bind=True, max_retries=3)
def embed_candidate_task(self, job_id: str):
    job = ProcessingJob.objects.get(id=job_id)
    if job.status == ProcessingJob.Status.SUCCEEDED:
        return
    job.status = ProcessingJob.Status.RUNNING
    job.attempts += 1
    job.started_at = timezone.now()
    job.save(update_fields=["status", "attempts", "started_at", "updated_at"])
    try:
        candidate = Candidate.objects.get(id=job.target_id, organization=job.organization)
        document = candidate.search_document or candidate.full_name
        result = execute(job.organization, "generate_embedding", "generate_embedding", document)
        vector = (result.data or {}).get("embedding")
        if vector:
            candidate.embedding = vector
            candidate.save(update_fields=["embedding", "updated_at"])
        job.status = ProcessingJob.Status.SUCCEEDED
        job.provider = result.provider
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "provider", "finished_at", "updated_at"])
    except ProviderError as exc:
        if getattr(exc, "retryable", False) and job.attempts < job.max_attempts:
            job.status = ProcessingJob.Status.QUEUED
            job.save(update_fields=["status", "updated_at"])
            raise self.retry(exc=exc, countdown=min(120, 2**self.request.retries) + random.random())
        job.status = ProcessingJob.Status.FAILED
        job.last_error = str(exc)[:400]
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "last_error", "finished_at", "updated_at"])
