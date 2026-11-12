from django.conf import settings
from django.db import models

from apps.common.models import UUIDModel


class AuditEvent(UUIDModel):
    organization = models.ForeignKey(
        "accounts.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events"
    )
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    ip_address = models.CharField(max_length=64, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["action"]),
        ]
        ordering = ["-created_at"]
