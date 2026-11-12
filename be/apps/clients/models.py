from django.conf import settings
from django.db import models

from apps.common.models import OrgScopedModel, UUIDModel
from apps.common.roles import CLIENT_ROLES


class ClientCompany(OrgScopedModel):
    class Plan(models.TextChoices):
        NONE = "none", "No distribution plan"
        PAID = "paid", "Paid plan"
        FREE = "free", "Free access (admin grant)"

    name = models.CharField(max_length=200)
    industry = models.CharField(max_length=120, blank=True)
    website = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    plan = models.CharField(max_length=12, choices=Plan.choices, default=Plan.NONE)
    plan_reference = models.CharField(max_length=120, blank=True)
    free_access_reason = models.CharField(max_length=200, blank=True)
    free_access_granted_at = models.DateTimeField(null=True, blank=True)
    free_access_granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="free_access_grants"
    )

    @property
    def distribution_enabled(self) -> bool:
        return self.plan in {self.Plan.PAID, self.Plan.FREE}

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="uniq_client_name_per_org"),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ClientContact(OrgScopedModel):
    company = models.ForeignKey(ClientCompany, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    title = models.CharField(max_length=160, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary", "name"]


class ClientMembership(UUIDModel):
    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE)
    company = models.ForeignKey(ClientCompany, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="client_memberships")
    role = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "user"], name="uniq_client_user"),
            models.CheckConstraint(condition=models.Q(role__in=list(CLIENT_ROLES)), name="client_membership_role"),
        ]
