from django.conf import settings
from django.db import models

from apps.common.models import OrgScopedModel, UUIDModel


class SavedSearch(OrgScopedModel):
    class Mode(models.TextChoices):
        STRUCTURED = "structured", "Structured"
        BOOLEAN = "boolean", "Boolean"
        NATURAL = "natural", "Natural language"
        HYBRID = "hybrid", "Hybrid"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_searches")
    name = models.CharField(max_length=160)
    mode = models.CharField(max_length=20, choices=Mode.choices)
    boolean_query = models.TextField(blank=True)
    natural_language = models.TextField(blank=True)
    semantic_query = models.TextField(blank=True)
    notify_on_new_match = models.BooleanField(default=False)
    last_run_at = models.DateTimeField(null=True, blank=True)
    hide_unknown = models.BooleanField(default=False)

    class Meta:
        ordering = ["-updated_at"]


class SavedSearchCriterion(UUIDModel):
    saved_search = models.ForeignKey(SavedSearch, on_delete=models.CASCADE, related_name="criteria")
    field = models.CharField(max_length=40)
    operator = models.CharField(max_length=20, default="eq")
    value = models.CharField(max_length=300)


class SavedSearchHit(UUIDModel):
    saved_search = models.ForeignKey(SavedSearch, on_delete=models.CASCADE, related_name="hits")
    candidate = models.ForeignKey("candidates.Candidate", on_delete=models.CASCADE)
    first_seen = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["saved_search", "candidate"], name="uniq_saved_search_hit"),
        ]


class SearchHistory(UUIDModel):
    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="search_history")
    mode = models.CharField(max_length=20)
    query_text = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "user", "created_at"])]
