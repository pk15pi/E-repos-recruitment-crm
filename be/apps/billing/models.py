from django.db import models

from apps.common.models import TimestampedModel, UUIDModel


class Plan(TimestampedModel):
    class Interval(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    price_cents = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="USD")
    interval = models.CharField(max_length=10, choices=Interval.choices, default=Interval.MONTHLY)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "price_cents", "name"]

    def __str__(self) -> str:
        return self.name


class PromoCode(TimestampedModel):
    class Kind(models.TextChoices):
        PERCENT = "percent", "Percent off"
        FIXED = "fixed", "Fixed amount off"

    code = models.CharField(max_length=40, unique=True)
    description = models.CharField(max_length=200, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PERCENT)
    percent_off = models.PositiveSmallIntegerField(null=True, blank=True)
    amount_off_cents = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    max_redemptions = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(kind="percent", percent_off__gte=1, percent_off__lte=100)
                    | models.Q(kind="fixed", amount_off_cents__gte=1)
                ),
                name="promo_discount_known",
            )
        ]

    def __str__(self) -> str:
        return self.code


class Subscription(TimestampedModel):
    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        CANCELED = "canceled", "Canceled"
        EXPIRED = "expired", "Expired"

    organization = models.OneToOneField(
        "accounts.Organization", on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    list_price_cents = models.PositiveIntegerField(default=0)
    discount_cents = models.PositiveIntegerField(default=0)
    amount_cents = models.PositiveIntegerField(default=0)
    promo = models.ForeignKey(
        PromoCode, null=True, blank=True, on_delete=models.SET_NULL, related_name="subscriptions"
    )
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.organization_id} on {self.plan_id}"


class PromoRedemption(UUIDModel):
    promo = models.ForeignKey(PromoCode, on_delete=models.CASCADE, related_name="redemptions")
    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="promo_redemptions"
    )
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="redemptions")
    discount_cents = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["promo", "organization"], name="uniq_promo_per_org"),
        ]
