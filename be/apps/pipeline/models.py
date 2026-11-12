from django.conf import settings
from django.db import models

from apps.common.models import OrgScopedModel, UUIDModel


class Shortlist(OrgScopedModel):
    name = models.CharField(max_length=160)
    job = models.ForeignKey("jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="shortlists")
    client_company = models.ForeignKey(
        "clients.ClientCompany", null=True, blank=True, on_delete=models.SET_NULL, related_name="shortlists"
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-updated_at"]


class ShortlistItem(UUIDModel):
    shortlist = models.ForeignKey(Shortlist, on_delete=models.CASCADE, related_name="items")
    candidate = models.ForeignKey("candidates.Candidate", on_delete=models.CASCADE, related_name="shortlist_items")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=400, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["shortlist", "candidate"], name="uniq_shortlist_candidate"),
        ]


class CandidateShare(OrgScopedModel):
    candidate = models.ForeignKey("candidates.Candidate", on_delete=models.CASCADE, related_name="shares")
    client_company = models.ForeignKey("clients.ClientCompany", on_delete=models.CASCADE, related_name="shares")
    shared_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="shares_made")
    include_compensation = models.BooleanField(default=False)
    include_contact = models.BooleanField(default=False)
    include_resume = models.BooleanField(default=False)
    note = models.CharField(max_length=400, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="shares_revoked"
    )

    class Meta:
        indexes = [
            models.Index(fields=["organization", "client_company", "revoked_at"]),
            models.Index(fields=["candidate", "revoked_at"]),
        ]


class CandidateSubmission(OrgScopedModel):
    class Stage(models.TextChoices):
        SOURCED = "sourced", "Sourced"
        SCREENED = "screened", "Screened"
        SHORTLISTED = "shortlisted", "Shortlisted"
        SUBMITTED = "submitted", "Submitted"
        INTERVIEW = "interview", "Interview"
        OFFER = "offer", "Offer"
        HIRED = "hired", "Hired"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"
        ON_HOLD = "on_hold", "On hold"
        CLOSED = "closed", "Closed"

    candidate = models.ForeignKey("candidates.Candidate", on_delete=models.CASCADE, related_name="submissions")
    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, related_name="submissions")
    client_company = models.ForeignKey("clients.ClientCompany", on_delete=models.CASCADE, related_name="submissions")
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.SOURCED)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    offer_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    offer_currency = models.CharField(max_length=3, blank=True)
    joining_date = models.DateField(null=True, blank=True)
    placement_notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "candidate"], name="uniq_submission_job_candidate"),
        ]
        indexes = [models.Index(fields=["organization", "stage"])]
        ordering = ["-updated_at"]


class Interview(OrgScopedModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No show"

    class Kind(models.TextChoices):
        MANUAL = "manual", "Manual interview"
        AI = "ai", "AI interview"

    class QuestionSource(models.TextChoices):
        RANDOM = "random", "Generated from the requisition"
        MANUAL = "manual", "Written by the recruiter"

    class Level(models.TextChoices):
        SCREENING = "screening", "Screening"
        L1 = "l1", "L1"
        L2 = "l2", "L2"
        L3 = "l3", "L3"
        L4 = "l4", "L4"
        L5 = "l5", "L5"

    class Outcome(models.TextChoices):
        PENDING = "pending", "Pending"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"

    submission = models.ForeignKey(CandidateSubmission, on_delete=models.CASCADE, related_name="interviews")
    candidate = models.ForeignKey("candidates.Candidate", on_delete=models.CASCADE, related_name="interviews")
    level = models.CharField(max_length=12, choices=Level.choices, default=Level.SCREENING)
    outcome = models.CharField(max_length=12, choices=Outcome.choices, default=Outcome.PENDING)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    mode = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SCHEDULED)
    interviewer_name = models.CharField(max_length=200, blank=True)
    feedback = models.TextField(blank=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    feedback_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="interview_feedback"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="interviews_created"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.MANUAL)
    question_source = models.CharField(max_length=12, choices=QuestionSource.choices, blank=True)
    question_count = models.PositiveSmallIntegerField(default=5)
    meeting_provider = models.CharField(max_length=20, blank=True)
    meeting_url = models.URLField(max_length=500, blank=True)
    invited_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    ai_status = models.CharField(max_length=16, blank=True)
    ai_feedback = models.TextField(blank=True)
    ai_recommendation = models.CharField(max_length=20, blank=True)
    ai_score = models.PositiveSmallIntegerField(null=True, blank=True)
    ai_generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-scheduled_at", "-created_at"]


class InterviewQuestion(UUIDModel):
    interview = models.ForeignKey(Interview, on_delete=models.CASCADE, related_name="questions")
    prompt = models.TextField()
    focus = models.CharField(max_length=120, blank=True)
    source = models.CharField(max_length=12, default="manual")
    sort_order = models.PositiveSmallIntegerField(default=0)
    answer = models.TextField(blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "created_at"]
