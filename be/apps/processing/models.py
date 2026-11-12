from django.db import models

from apps.common.models import OrgScopedModel


class ProcessingJob(OrgScopedModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class Kind(models.TextChoices):
        RESUME_PARSE = "resume_parse", "Resume parse"
        EMBED = "embed_candidate", "Embed candidate"
        JD_ANALYZE = "jd_analyze", "JD analyze"
        SAVED_SEARCH = "saved_search", "Saved search"
        RETENTION = "retention", "Retention"
        MATCH = "match", "Match"

    kind = models.CharField(max_length=32, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    target_type = models.CharField(max_length=40)
    target_id = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=180, unique=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    last_error = models.CharField(max_length=400, blank=True)
    provider = models.CharField(max_length=40, blank=True)
    celery_task_id = models.CharField(max_length=80, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["target_type", "target_id"]),
        ]
        ordering = ["-created_at"]
