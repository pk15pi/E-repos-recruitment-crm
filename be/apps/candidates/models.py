from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from pgvector.django import HnswIndex, VectorField

from apps.common.models import OrgScopedModel, UUIDModel


class Candidate(OrgScopedModel):
    class Status(models.TextChoices):
        NEW = "new", "New"
        ACTIVE = "active", "Active"
        PASSIVE = "passive", "Passive"
        PLACED = "placed", "Placed"
        DO_NOT_CONTACT = "do_not_contact", "Do not contact"
        ARCHIVED = "archived", "Archived"

    class Verification(models.TextChoices):
        UNVERIFIED = "unverified", "Unverified"
        PARTIAL = "partial", "Partial"
        VERIFIED = "verified", "Verified"

    class WorkMode(models.TextChoices):
        REMOTE = "remote", "Remote"
        HYBRID = "hybrid", "Hybrid"
        ONSITE = "onsite", "On-site"

    class EmploymentType(models.TextChoices):
        FULL_TIME = "full_time", "Full-time"
        PART_TIME = "part_time", "Part-time"
        CONTRACT = "contract", "Contract"
        INTERNSHIP = "internship", "Internship"
        TEMPORARY = "temporary", "Temporary"

    class SalaryPeriod(models.TextChoices):
        ANNUAL = "annual", "Annual"
        MONTHLY = "monthly", "Monthly"
        DAILY = "daily", "Daily"
        HOURLY = "hourly", "Hourly"

    full_name = models.CharField(max_length=200, blank=True)
    summary = models.TextField(blank=True)
    current_title = models.CharField(max_length=200, blank=True)
    normalized_title = models.CharField(max_length=200, blank=True)
    current_employer = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=200, blank=True)
    linkedin_url = models.URLField(blank=True)
    github_url = models.URLField(blank=True)
    portfolio_url = models.URLField(blank=True)
    industry = models.CharField(max_length=120, blank=True)
    total_experience_months = models.PositiveIntegerField(null=True, blank=True)
    relevant_experience_months = models.PositiveIntegerField(null=True, blank=True)
    current_salary_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    current_salary_currency = models.CharField(max_length=3, blank=True)
    current_salary_period = models.CharField(max_length=16, choices=SalaryPeriod.choices, blank=True)
    expected_salary_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    expected_salary_currency = models.CharField(max_length=3, blank=True)
    expected_salary_period = models.CharField(max_length=16, choices=SalaryPeriod.choices, blank=True)
    notice_period_days = models.PositiveIntegerField(null=True, blank=True)
    availability_date = models.DateField(null=True, blank=True)
    work_mode = models.CharField(max_length=16, choices=WorkMode.choices, blank=True)
    employment_type = models.CharField(max_length=16, choices=EmploymentType.choices, blank=True)
    willing_to_relocate = models.BooleanField(null=True, blank=True)
    assigned_recruiter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_candidates",
    )
    source = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.NEW)
    verification_status = models.CharField(
        max_length=16, choices=Verification.choices, default=Verification.UNVERIFIED
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    deletion_requested_at = models.DateTimeField(null=True, blank=True)
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="merged_from"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_candidates",
    )
    search_document = models.TextField(blank=True)
    search_vector = SearchVectorField(null=True, editable=False)
    embedding = VectorField(dimensions=1536, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "updated_at"]),
            models.Index(fields=["organization", "archived_at"]),
            models.Index(fields=["linkedin_url"]),
            GinIndex(fields=["search_vector"], name="cand_search_gin"),
            GinIndex(name="cand_name_trgm", fields=["full_name"], opclasses=["gin_trgm_ops"]),
            HnswIndex(
                name="cand_embed_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.full_name or "Unnamed candidate"


class CandidateEmail(OrgScopedModel):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="emails")
    email = models.EmailField()
    label = models.CharField(max_length=40, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["organization", "email"])]
        constraints = [
            models.UniqueConstraint(fields=["candidate", "email"], name="uniq_candidate_email"),
        ]


class CandidatePhone(OrgScopedModel):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="phones")
    raw = models.CharField(max_length=40)
    digits = models.CharField(max_length=20, blank=True, db_index=True)
    label = models.CharField(max_length=40, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["organization", "digits"])]


class CandidatePreferredLocation(OrgScopedModel):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="preferred_locations")
    location = models.CharField(max_length=200)


class Tag(OrgScopedModel):
    class Kind(models.TextChoices):
        TAG = "tag", "Tag"
        POOL = "pool", "Talent pool"

    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.TAG)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "kind", "name"], name="uniq_tag_name"),
        ]


class CandidateTag(UUIDModel):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="candidate_tags")
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="candidate_tags")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["candidate", "tag"], name="uniq_candidate_tag")]


class CandidateExperience(OrgScopedModel):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="experiences")
    employer = models.CharField(max_length=200, blank=True)
    title = models.CharField(max_length=200, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    start_granularity = models.CharField(max_length=8, blank=True)
    end_granularity = models.CharField(max_length=8, blank=True)
    is_current = models.BooleanField(default=False)
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "-is_current", "-start_date"]


class Skill(OrgScopedModel):
    name = models.CharField(max_length=120)
    normalized_name = models.CharField(max_length=120)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "normalized_name"], name="uniq_skill_norm"),
        ]
        indexes = [models.Index(fields=["organization", "normalized_name"])]


class SkillAlias(OrgScopedModel):
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField(max_length=120)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "alias"], name="uniq_skill_alias"),
        ]


class CandidateSkill(OrgScopedModel):
    class Source(models.TextChoices):
        EXTRACTED = "extracted", "Extracted"
        VERIFIED = "verified", "Verified"
        USER = "user", "User"

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="candidate_skills")
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="candidate_skills")
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.USER)
    confidence = models.FloatField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["candidate", "skill"], name="uniq_candidate_skill"),
        ]


class CandidateEducation(OrgScopedModel):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="education")
    institution = models.CharField(max_length=200, blank=True)
    degree = models.CharField(max_length=200, blank=True)
    field_of_study = models.CharField(max_length=200, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)


class CandidateCertification(OrgScopedModel):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="certifications")
    name = models.CharField(max_length=200)
    issuer = models.CharField(max_length=200, blank=True)
    issued_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)


class CandidateProject(OrgScopedModel):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    url = models.URLField(blank=True)
    technologies = models.CharField(max_length=400, blank=True)


class CandidateLanguage(OrgScopedModel):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="languages")
    language = models.CharField(max_length=80)
    proficiency = models.CharField(max_length=80, blank=True)


class RecruiterNote(OrgScopedModel):
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Recruiter private"
        CLIENT = "client", "Client visible"

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    body = models.TextField()
    visibility = models.CharField(max_length=16, choices=Visibility.choices, default=Visibility.PRIVATE)

    class Meta:
        ordering = ["-created_at"]


class Task(OrgScopedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        DONE = "done", "Done"
        CANCELLED = "cancelled", "Cancelled"

    candidate = models.ForeignKey(Candidate, null=True, blank=True, on_delete=models.CASCADE, related_name="tasks")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_tasks"
    )
    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    idempotency_key = models.CharField(max_length=160, blank=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status", "due_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uniq_task_idempotency",
            )
        ]


class ConsentRecord(OrgScopedModel):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="consents")
    purpose = models.CharField(max_length=200)
    lawful_basis = models.CharField(max_length=80)
    granted = models.BooleanField()
    source = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created_at"]
