from django.db import models

from apps.common.models import UUIDModel


class AIUsageRecord(UUIDModel):
    organization = models.ForeignKey(
        "accounts.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="ai_usage"
    )
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=80, blank=True)
    operation = models.CharField(max_length=40)
    prompt_version = models.CharField(max_length=40, blank=True)
    schema_version = models.CharField(max_length=40, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=16, default="ok")
    error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "created_at"])]
        ordering = ["-created_at"]
