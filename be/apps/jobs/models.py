from django.conf import settings
from django.db import models

from apps.common.models import OrgScopedModel, UUIDModel


class Job(OrgScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPEN = "open", "Open"
        ON_HOLD = "on_hold", "On hold"
        CLOSED = "closed", "Closed"

    class AnalysisStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    client_company = models.ForeignKey(
        "clients.ClientCompany", null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs"
    )
    title = models.CharField(max_length=200, blank=True)
    original_description = models.TextField(blank=True)
    location = models.CharField(max_length=200, blank=True)
    work_mode = models.CharField(max_length=16, blank=True)
    employment_type = models.CharField(max_length=16, blank=True)
    seniority = models.CharField(max_length=80, blank=True)
    min_experience_months = models.PositiveIntegerField(null=True, blank=True)
    max_experience_months = models.PositiveIntegerField(null=True, blank=True)
    salary_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    salary_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    salary_currency = models.CharField(max_length=3, blank=True)
    salary_period = models.CharField(max_length=16, blank=True)
    notice_period_days = models.PositiveIntegerField(null=True, blank=True)
    domain = models.CharField(max_length=120, blank=True)
    interview_levels = models.PositiveSmallIntegerField(default=2)
    interview_question_count = models.PositiveSmallIntegerField(default=5)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    analysis_status = models.CharField(max_length=16, choices=AnalysisStatus.choices, default=AnalysisStatus.PENDING)
    analysis_error = models.CharField(max_length=400, blank=True)
    assigned_recruiter = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_jobs"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_jobs"
    )
    provider = models.CharField(max_length=40, blank=True)
    model = models.CharField(max_length=80, blank=True)
    prompt_version = models.CharField(max_length=40, blank=True)
    schema_version = models.CharField(max_length=40, blank=True)
    score_version = models.CharField(max_length=40, blank=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status"])]
        ordering = ["-updated_at"]


class JobRequirement(OrgScopedModel):
    class Priority(models.TextChoices):
        MUST = "must_have", "Must have"
        PREFERRED = "preferred", "Preferred"
        INFO = "informational", "Informational"

    class Kind(models.TextChoices):
        TITLE = "title", "Title"
        SENIORITY = "seniority", "Seniority"
        SKILL = "skill", "Skill"
        TOOL = "tool", "Tool"
        RESPONSIBILITY = "responsibility", "Responsibility"
        EDUCATION = "education", "Education"
        CERTIFICATION = "certification", "Certification"
        DOMAIN = "domain", "Domain"
        LOCATION = "location", "Location"
        WORK_MODE = "work_mode", "Work mode"
        EMPLOYMENT_TYPE = "employment_type", "Employment type"
        EXPERIENCE = "experience", "Experience"
        SALARY = "salary", "Salary"
        NOTICE = "notice", "Notice"
        OTHER = "other", "Other"

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="requirements")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    label = models.CharField(max_length=200)
    value = models.CharField(max_length=500, blank=True)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.PREFERRED)
    source = models.CharField(max_length=16, default="extracted")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "created_at"]


class MatchResult(OrgScopedModel):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="matches")
    candidate = models.ForeignKey("candidates.Candidate", on_delete=models.CASCADE, related_name="matches")
    score = models.DecimalField(max_digits=5, decimal_places=2)
    score_version = models.CharField(max_length=40)
    mandatory_met = models.PositiveIntegerField(default=0)
    mandatory_unknown = models.PositiveIntegerField(default=0)
    mandatory_unmet = models.PositiveIntegerField(default=0)
    preferred_matched = models.PositiveIntegerField(default=0)
    preferred_total = models.PositiveIntegerField(default=0)
    explanation = models.TextField(blank=True)
    lexical_rank = models.PositiveIntegerField(null=True, blank=True)
    semantic_rank = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "candidate"], name="uniq_job_candidate_match"),
        ]
        indexes = [models.Index(fields=["job", "-score"])]
        ordering = ["-score", "-updated_at"]


class MatchEvidence(UUIDModel):
    match = models.ForeignKey(MatchResult, on_delete=models.CASCADE, related_name="evidence")
    requirement = models.ForeignKey(JobRequirement, null=True, blank=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=32)
    status = models.CharField(max_length=20)
    detail = models.CharField(max_length=400, blank=True)
    quote = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ["kind", "status"]
