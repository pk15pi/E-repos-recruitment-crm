import re
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Organization
from apps.billing.models import Plan, PromoCode, PromoRedemption, Subscription
from apps.common.audit import record_audit
from apps.common.permissions import PlatformOnly, TenantMixin

CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
PLAN_CODE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROMO_CODE_RE = re.compile(r"^[A-Z0-9-]{1,40}$")

COUNTED_SUBSCRIPTIONS = {
    Subscription.Status.TRIALING,
    Subscription.Status.ACTIVE,
    Subscription.Status.PAST_DUE,
}
ORG_STATUS_FOR_SUBSCRIPTION = {
    Subscription.Status.TRIALING: (Organization.Status.ACTIVE, ""),
    Subscription.Status.ACTIVE: (Organization.Status.ACTIVE, ""),
    Subscription.Status.PAST_DUE: (Organization.Status.PAST_DUE, "Subscription payment past due"),
    Subscription.Status.CANCELED: (Organization.Status.INACTIVE, "Subscription canceled"),
    Subscription.Status.EXPIRED: (Organization.Status.INACTIVE, "Subscription expired"),
}


def _flag(data, key, default):
    if key not in data:
        return default
    value = data.get(key)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int_value(value, field, minimum=0):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError({field: "Enter a whole number."})
    if number < minimum:
        raise ValidationError({field: f"Must be {minimum} or more."})
    return number


def _currency(value):
    code = str(value or "").strip().upper()
    if not CURRENCY_RE.match(code):
        raise ValidationError({"currency": "Use a three-letter currency code."})
    return code


def _interval(value):
    if value not in Plan.Interval.values:
        raise ValidationError({"interval": "Choose monthly or yearly."})
    return value


def _optional_datetime(value, field):
    text = str(value or "").strip()
    if not text:
        return None
    parsed = parse_datetime(text)
    if parsed is None:
        day = parse_date(text)
        parsed = datetime.combine(day, time.min) if day is not None else None
    if parsed is None:
        raise ValidationError({field: "Use an ISO 8601 date and time."})
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _plan_payload(plan):
    subscribers = getattr(plan, "subscribers", None)
    if subscribers is None:
        subscribers = plan.subscriptions.filter(status__in=COUNTED_SUBSCRIPTIONS).count()
    return {
        "id": str(plan.id),
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "price_cents": plan.price_cents,
        "currency": plan.currency,
        "interval": plan.interval,
        "is_active": plan.is_active,
        "sort_order": plan.sort_order,
        "subscribers": subscribers,
    }


def _promo_payload(promo):
    redeemed = getattr(promo, "redeemed", None)
    if redeemed is None:
        redeemed = promo.redemptions.count()
    return {
        "id": str(promo.id),
        "code": promo.code,
        "description": promo.description,
        "kind": promo.kind,
        "percent_off": promo.percent_off,
        "amount_off_cents": promo.amount_off_cents,
        "currency": promo.currency,
        "valid_from": promo.valid_from,
        "valid_until": promo.valid_until,
        "max_redemptions": promo.max_redemptions,
        "is_active": promo.is_active,
        "redeemed": redeemed,
    }


def _organization_payload(org):
    return {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "status": org.status,
        "read_only": org.read_only,
        "status_reason": org.status_reason,
    }


def _subscription_payload(sub):
    return {
        "id": str(sub.id),
        "organization": _organization_payload(sub.organization),
        "plan": _plan_payload(sub.plan),
        "status": sub.status,
        "current_period_start": sub.current_period_start,
        "current_period_end": sub.current_period_end,
        "list_price_cents": sub.list_price_cents,
        "discount_cents": sub.discount_cents,
        "amount_cents": sub.amount_cents,
        "promo_code": sub.promo.code if sub.promo else None,
        "notes": sub.notes,
        "created_at": sub.created_at,
        "updated_at": sub.updated_at,
    }


def _apply_promo_fields(promo, data, creating):
    kind = data.get("kind", promo.kind or PromoCode.Kind.PERCENT)
    if kind not in PromoCode.Kind.values:
        raise ValidationError({"kind": "Choose a percent or fixed discount."})
    promo.kind = kind
    if kind == PromoCode.Kind.PERCENT:
        if "percent_off" in data or creating:
            promo.percent_off = _int_value(data.get("percent_off"), "percent_off", 1)
            if promo.percent_off > 100:
                raise ValidationError({"percent_off": "A percentage discount cannot exceed 100."})
        promo.amount_off_cents = None
        promo.currency = ""
    else:
        if "amount_off_cents" in data or creating:
            promo.amount_off_cents = _int_value(data.get("amount_off_cents"), "amount_off_cents", 1)
        if "currency" in data or creating:
            promo.currency = _currency(data.get("currency"))
        promo.percent_off = None
    if "description" in data or creating:
        promo.description = str(data.get("description") or "").strip()[:200]
    if "valid_from" in data or creating:
        promo.valid_from = _optional_datetime(data.get("valid_from"), "valid_from")
    if "valid_until" in data or creating:
        promo.valid_until = _optional_datetime(data.get("valid_until"), "valid_until")
    if "max_redemptions" in data or creating:
        raw = data.get("max_redemptions")
        promo.max_redemptions = None if raw in (None, "") else _int_value(raw, "max_redemptions", 1)
    if "is_active" in data or creating:
        promo.is_active = _flag(data, "is_active", True)
    if promo.valid_from and promo.valid_until and promo.valid_from >= promo.valid_until:
        raise ValidationError({"valid_until": "The end of the promo window must be after the start."})


def _resolve_plan(data, sub):
    raw = data.get("plan_id")
    if raw in (None, ""):
        if sub is None:
            raise ValidationError({"plan_id": "Choose a plan."})
        return sub.plan
    plan = Plan.objects.filter(id=raw).first()
    if plan is None:
        raise ValidationError({"plan_id": "Plan not found."})
    if not plan.is_active and (sub is None or sub.plan_id != plan.id):
        raise ValidationError({"plan_id": "This plan is no longer available."})
    return plan


def _resolve_promo(data, sub):
    if "promo_code" not in data:
        return sub.promo if sub else None
    raw = str(data.get("promo_code") or "").strip()
    if not raw:
        return None
    promo = PromoCode.objects.filter(code__iexact=raw).first()
    if promo is None:
        raise ValidationError({"promo_code": "This promo code does not exist."})
    return promo


def _validate_promo(promo, plan, sub, now):
    if not promo.is_active:
        raise ValidationError({"promo_code": "This promo code is not active."})
    if promo.valid_from and now < promo.valid_from:
        raise ValidationError({"promo_code": "This promo code is not active yet."})
    if promo.valid_until and now > promo.valid_until:
        raise ValidationError({"promo_code": "This promo code has expired."})
    if promo.kind == PromoCode.Kind.FIXED and promo.currency != plan.currency:
        raise ValidationError({"promo_code": "This promo code is for a different currency."})
    used = PromoRedemption.objects.filter(promo=promo)
    if sub is not None and sub.pk is not None:
        used = used.exclude(subscription_id=sub.pk)
    if promo.max_redemptions is not None and used.count() >= promo.max_redemptions:
        raise ValidationError({"promo_code": "This promo code has reached its redemption limit."})


def _discount_for(plan, promo):
    if promo is None:
        return 0
    if promo.kind == PromoCode.Kind.PERCENT:
        return min(plan.price_cents, plan.price_cents * (promo.percent_off or 0) // 100)
    return min(plan.price_cents, promo.amount_off_cents or 0)


def _sync_org_status(org, status):
    new_status, reason = ORG_STATUS_FOR_SUBSCRIPTION[status]
    if org.status == new_status and org.status_reason == reason:
        return
    org.status = new_status
    org.status_reason = reason
    org.status_changed_at = timezone.now()
    org.save(update_fields=["status", "status_reason", "status_changed_at", "updated_at"])


class PlanListView(TenantMixin, APIView):
    permission_classes = [PlatformOnly]
    allow_missing_org = True

    def get(self, request):
        plans = Plan.objects.annotate(
            subscribers=Count("subscriptions", filter=Q(subscriptions__status__in=COUNTED_SUBSCRIPTIONS))
        ).order_by("sort_order", "price_cents", "name")
        return Response([_plan_payload(plan) for plan in plans])

    def post(self, request):
        code = str(request.data.get("code") or "").strip().lower()
        if not PLAN_CODE_RE.match(code):
            raise ValidationError({"code": "Use lowercase letters, digits, and dashes."})
        if Plan.objects.filter(code=code).exists():
            raise ValidationError({"code": "A plan with this code already exists."})
        name = str(request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "Plan name is required."})
        plan = Plan(
            code=code,
            name=name[:120],
            description=str(request.data.get("description") or "").strip()[:2000],
            price_cents=_int_value(request.data.get("price_cents", 0), "price_cents"),
            currency=_currency(request.data.get("currency", "USD")),
            interval=_interval(request.data.get("interval", Plan.Interval.MONTHLY)),
            is_active=_flag(request.data, "is_active", True),
            sort_order=_int_value(request.data.get("sort_order", 0), "sort_order"),
        )
        plan.save()
        record_audit(request, "plan_create", plan, f"{plan.code} {plan.price_cents} {plan.currency}")
        return Response(_plan_payload(plan), status=201)


class PlanDetailView(TenantMixin, APIView):
    permission_classes = [PlatformOnly]
    allow_missing_org = True

    def get(self, request, plan_id):
        return Response(_plan_payload(get_object_or_404(Plan, id=plan_id)))

    def patch(self, request, plan_id):
        plan = get_object_or_404(Plan, id=plan_id)
        if "code" in request.data:
            raise ValidationError({"code": "The plan code cannot change."})
        if "name" in request.data:
            name = str(request.data.get("name") or "").strip()
            if not name:
                raise ValidationError({"name": "Plan name is required."})
            plan.name = name[:120]
        if "description" in request.data:
            plan.description = str(request.data.get("description") or "").strip()[:2000]
        if "price_cents" in request.data:
            plan.price_cents = _int_value(request.data.get("price_cents"), "price_cents")
        if "currency" in request.data:
            plan.currency = _currency(request.data.get("currency"))
        if "interval" in request.data:
            plan.interval = _interval(request.data.get("interval"))
        if "is_active" in request.data:
            plan.is_active = _flag(request.data, "is_active", True)
        if "sort_order" in request.data:
            plan.sort_order = _int_value(request.data.get("sort_order"), "sort_order")
        plan.save()
        record_audit(request, "plan_update", plan, plan.code)
        return Response(_plan_payload(plan))


class PromoCodeListView(TenantMixin, APIView):
    permission_classes = [PlatformOnly]
    allow_missing_org = True

    def get(self, request):
        promos = PromoCode.objects.annotate(redeemed=Count("redemptions")).order_by("-created_at")
        return Response([_promo_payload(promo) for promo in promos])

    def post(self, request):
        code = str(request.data.get("code") or "").strip().upper()
        if not PROMO_CODE_RE.match(code):
            raise ValidationError({"code": "Use letters, digits, and dashes, up to 40 characters."})
        if PromoCode.objects.filter(code__iexact=code).exists():
            raise ValidationError({"code": "A promo code with this code already exists."})
        promo = PromoCode(code=code)
        _apply_promo_fields(promo, request.data, creating=True)
        promo.save()
        record_audit(request, "promo_create", promo, promo.code)
        return Response(_promo_payload(promo), status=201)


class PromoCodeDetailView(TenantMixin, APIView):
    permission_classes = [PlatformOnly]
    allow_missing_org = True

    def get(self, request, promo_id):
        return Response(_promo_payload(get_object_or_404(PromoCode, id=promo_id)))

    def patch(self, request, promo_id):
        promo = get_object_or_404(PromoCode, id=promo_id)
        if "code" in request.data:
            raise ValidationError({"code": "The promo code cannot change."})
        _apply_promo_fields(promo, request.data, creating=False)
        promo.save()
        record_audit(request, "promo_update", promo, promo.code)
        return Response(_promo_payload(promo))


class OrganizationSubscriptionView(TenantMixin, APIView):
    permission_classes = [PlatformOnly]
    allow_missing_org = True

    def get(self, request, org_id):
        org = get_object_or_404(Organization, id=org_id)
        sub = Subscription.objects.filter(organization=org).select_related("plan", "promo").first()
        return Response(
            {
                "organization": _organization_payload(org),
                "subscription": _subscription_payload(sub) if sub else None,
            }
        )

    def put(self, request, org_id):
        return self._save(request, org_id)

    def patch(self, request, org_id):
        return self._save(request, org_id)

    def _save(self, request, org_id):
        org = get_object_or_404(Organization, id=org_id)
        sub = Subscription.objects.filter(organization=org).select_related("plan", "promo").first()
        plan = _resolve_plan(request.data, sub)
        status = request.data.get("status", sub.status if sub else Subscription.Status.ACTIVE)
        if status not in Subscription.Status.values:
            raise ValidationError({"status": "Unknown subscription status."})
        now = timezone.now()
        if "current_period_start" in request.data:
            start = _optional_datetime(request.data.get("current_period_start"), "current_period_start")
        else:
            start = sub.current_period_start if sub else now
        if "current_period_end" in request.data:
            end = _optional_datetime(request.data.get("current_period_end"), "current_period_end")
        elif sub:
            end = sub.current_period_end
        else:
            end = start + (timedelta(days=365) if plan.interval == Plan.Interval.YEARLY else timedelta(days=30))
        if start is None or end is None:
            raise ValidationError({"current_period_end": "Set both the start and end of the billing period."})
        if end <= start:
            raise ValidationError({"current_period_end": "The period must end after it starts."})
        promo = _resolve_promo(request.data, sub)
        notes = (
            str(request.data.get("notes") or "").strip()[:200]
            if "notes" in request.data
            else (sub.notes if sub else "")
        )
        with transaction.atomic():
            if promo is not None:
                promo = PromoCode.objects.select_for_update().get(pk=promo.pk)
                _validate_promo(promo, plan, sub, now)
            discount = _discount_for(plan, promo)
            amount = max(0, plan.price_cents - discount)
            if sub is None:
                sub = Subscription(organization=org)
            sub.plan = plan
            sub.status = status
            sub.current_period_start = start
            sub.current_period_end = end
            sub.list_price_cents = plan.price_cents
            sub.discount_cents = discount
            sub.amount_cents = amount
            sub.promo = promo
            sub.notes = notes
            sub.save()
            PromoRedemption.objects.filter(subscription=sub).delete()
            if promo is not None:
                PromoRedemption.objects.create(
                    promo=promo, organization=org, subscription=sub, discount_cents=discount
                )
            _sync_org_status(org, status)
            record_audit(
                request, "subscription_update", sub, f"{plan.code} {status} {amount}", organization=org
            )
        return Response(_subscription_payload(sub))
