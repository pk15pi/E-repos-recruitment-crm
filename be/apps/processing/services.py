from django.conf import settings
from django.db import transaction

from apps.processing.models import ProcessingJob


def enqueue(task, *, organization, kind: str, target_type: str, target_id: str, idempotency_key: str, provider: str = ""):
    job, created = ProcessingJob.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "organization": organization,
            "kind": kind,
            "target_type": target_type,
            "target_id": str(target_id),
            "provider": provider,
            "status": ProcessingJob.Status.QUEUED,
        },
    )
    if not created and job.status in {ProcessingJob.Status.QUEUED, ProcessingJob.Status.RUNNING, ProcessingJob.Status.SUCCEEDED}:
        return job
    if not created:
        job.status = ProcessingJob.Status.QUEUED
        job.last_error = ""
        job.finished_at = None
        job.save(update_fields=["status", "last_error", "finished_at", "updated_at"])

    def _send(job_id=str(job.id)):
        async_result = task.delay(job_id)
        ProcessingJob.objects.filter(pk=job_id).update(celery_task_id=async_result.id)

    if settings.CELERY_TASK_ALWAYS_EAGER:
        task.apply(args=[str(job.id)])
        job.refresh_from_db()
    else:
        transaction.on_commit(_send)
    return job


def requeue(job):
    """Manual retry. A new idempotency generation is not required; the row is reset."""
    from apps.jobs.tasks import analyze_job_task, match_job_task
    from apps.resumes.tasks import embed_candidate_task, process_resume_task

    task = {
        "resume_parse": process_resume_task,
        "embed_candidate": embed_candidate_task,
        "jd_analyze": analyze_job_task,
        "match": match_job_task,
    }.get(job.kind)
    if task is None:
        raise ValueError("This job type cannot be retried from the queue.")
    job.status = ProcessingJob.Status.QUEUED
    job.last_error = ""
    job.finished_at = None
    job.attempts = 0
    job.save(update_fields=["status", "last_error", "finished_at", "attempts", "updated_at"])
    if settings.CELERY_TASK_ALWAYS_EAGER:
        task.apply(args=[str(job.id)])
        job.refresh_from_db()
    else:
        transaction.on_commit(lambda: task.delay(str(job.id)))
    return job
