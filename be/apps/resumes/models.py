from django.conf import settings
from django.db import models
from pgvector.django import VectorField

from apps.common.models import OrgScopedModel


class ResumeDocument(OrgScopedModel):
    class Status(models.TextChoices):
        QUARANTINED = "quarantined", "Quarantined"
        SCANNING = "scanning", "Scanning"
        STORED = "stored", "Stored"
        EXTRACTING = "extracting", "Extracting"
        NEEDS_REVIEW = "needs_review", "Needs review"
        CONFIRMED = "confirmed", "Confirmed"
        FAILED = "failed", "Failed"
        REJECTED = "rejected", "Rejected"

    class ScanStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        CLEAN = "clean", "Clean"
        INFECTED = "infected", "Infected"
        SKIPPED = "skipped_unconfigured", "Scanner not configured"

    candidate = models.ForeignKey(
        "candidates.Candidate", null=True, blank=True, on_delete=models.SET_NULL, related_name="resumes"
    )
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True)
    byte_size = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, db_index=True)
    storage_key = models.CharField(max_length=300, blank=True)
    quarantine_key = models.CharField(max_length=300, blank=True)
    detected_type = models.CharField(max_length=16, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.QUARANTINED)
    scan_status = models.CharField(max_length=32, choices=ScanStatus.choices, default=ScanStatus.PENDING)
    # Full text stays in the database for review and reprocessing. Do not log it.
    extracted_text = models.TextField(blank=True)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    parse_generation = models.PositiveIntegerField(default=1)
    error_message = models.CharField(max_length=400, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "sha256"]),
        ]
        ordering = ["-created_at"]


class ResumeExtraction(OrgScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        DISCARDED = "discarded", "Discarded"

    resume = models.ForeignKey(ResumeDocument, on_delete=models.CASCADE, related_name="extractions")
    candidate = models.ForeignKey(
        "candidates.Candidate", null=True, blank=True, on_delete=models.SET_NULL, related_name="extractions"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    schema_version = models.CharField(max_length=40)
    prompt_version = models.CharField(max_length=40)
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=80)
    normalized = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)
    usage = models.JSONField(default=dict)
    raw_output = models.JSONField(default=dict)
    duplicates = models.JSONField(default=list)
    confidence_avg = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class CandidateFieldEvidence(OrgScopedModel):
    class Status(models.TextChoices):
        EXTRACTED = "extracted", "Extracted"
        VERIFIED = "verified", "Verified"
        NEEDS_REVIEW = "needs_review", "Needs review"
        MISSING = "missing", "Missing"
        CONFLICTING = "conflicting", "Conflicting"

    candidate = models.ForeignKey(
        "candidates.Candidate", null=True, blank=True, on_delete=models.CASCADE, related_name="evidence"
    )
    extraction = models.ForeignKey(
        ResumeExtraction, null=True, blank=True, on_delete=models.CASCADE, related_name="evidence"
    )
    field_path = models.CharField(max_length=120)
    value_text = models.TextField(blank=True)
    quote = models.TextField(blank=True)
    page_number = models.PositiveIntegerField(null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.EXTRACTED)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["candidate", "field_path"]),
            models.Index(fields=["extraction", "field_path"]),
        ]


class ResumeTextChunk(OrgScopedModel):
    resume = models.ForeignKey(ResumeDocument, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    page_number = models.PositiveIntegerField(null=True, blank=True)
    text = models.TextField()
    embedding = VectorField(dimensions=1536, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["resume", "chunk_index"], name="uniq_resume_chunk"),
        ]
        ordering = ["chunk_index"]
