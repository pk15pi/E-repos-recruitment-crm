from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Organization, User
from apps.billing.models import Plan, PromoCode, PromoRedemption, Subscription
from tests.conftest import PASSWORD, login

pytestmark = pytest.mark.django_db


def _platform():
    user, created = User.objects.get_or_create(
        email="owner@sable.test",
        defaults={"full_name": "Platform Owner", "is_platform_admin": True},
    )
    if created:
        user.set_password(PASSWORD)
    user.is_platform_admin = True
    user.save()
    api = APIClient()
    login(api, "owner@sable.test")
    return api


def _create_plan(api, code="studio", price_cents=19900, interval="monthly", **extra):
    payload = {"code": code, "name": code.title(), "price_cents": price_cents, "currency": "USD", "interval": interval}
    payload.update(extra)
    response = api.post("/api/v1/admin/plans/", payload, format="json")
    assert response.status_code == 201, response.content
    return response.json()


def _create_promo(api, code="LAUNCH20", **extra):
    payload = {"code": code, "kind": "percent", "percent_off": 20}
    payload.update(extra)
    response = api.post("/api/v1/admin/promo-codes/", payload, format="json")
    assert response.status_code == 201, response.content
    return response.json()


def test_non_platform_user_cannot_manage_billing(agency):
    api = APIClient()
    login(api, "ada@sable.test")
    assert api.get("/api/v1/admin/plans/").status_code == 403
    assert api.post("/api/v1/admin/plans/", {"code": "x", "name": "X"}, format="json").status_code == 403
    assert api.get("/api/v1/admin/promo-codes/").status_code == 403
    denied = api.put(
        f"/api/v1/admin/organizations/{agency['org'].id}/subscription/",
        {"status": "active"},
        format="json",
    )
    assert denied.status_code == 403


def test_plan_crud_and_validation(agency):
    api = _platform()
    plan = _create_plan(api, code="studio", price_cents=19900)
    assert plan["currency"] == "USD"
    assert plan["subscribers"] == 0

    duplicate = api.post(
        "/api/v1/admin/plans/",
        {"code": "studio", "name": "Duplicate", "price_cents": 100, "currency": "USD"},
        format="json",
    )
    assert duplicate.status_code == 400
    assert "already exists" in str(duplicate.json()["error"]["details"])

    bad_code = api.post(
        "/api/v1/admin/plans/", {"code": "Bad Code", "name": "Bad", "currency": "USD"}, format="json"
    )
    assert bad_code.status_code == 400

    updated = api.patch(
        f"/api/v1/admin/plans/{plan['id']}/",
        {"price_cents": 24900, "is_active": False},
        format="json",
    )
    assert updated.status_code == 200, updated.content
    assert updated.json()["price_cents"] == 24900
    assert updated.json()["is_active"] is False

    rename = api.patch(f"/api/v1/admin/plans/{plan['id']}/", {"code": "other"}, format="json")
    assert rename.status_code == 400
    assert api.get(f"/api/v1/admin/plans/{plan['id']}/").status_code == 200
    assert len(api.get("/api/v1/admin/plans/").json()) == 1


def test_subscription_with_percent_promo_and_redemption_limit(agency):
    api = _platform()
    plan = _create_plan(api, price_cents=19900)
    promo = _create_promo(api, max_redemptions=1, valid_until=(timezone.now() + timedelta(days=30)).isoformat())

    created = api.put(
        f"/api/v1/admin/organizations/{agency['org'].id}/subscription/",
        {"plan_id": plan["id"], "status": "active", "promo_code": "launch20"},
        format="json",
    )
    assert created.status_code == 200, created.content
    body = created.json()
    assert body["plan"]["code"] == "studio"
    assert body["list_price_cents"] == 19900
    assert body["discount_cents"] == 3980
    assert body["amount_cents"] == 15920
    assert body["promo_code"] == "LAUNCH20"
    assert body["current_period_end"] > body["current_period_start"]
    assert body["organization"]["read_only"] is False

    subscription = Subscription.objects.get(organization=agency["org"])
    assert subscription.amount_cents == 15920
    assert PromoRedemption.objects.filter(promo_id=promo["id"]).count() == 1
    agency["org"].refresh_from_db()
    assert agency["org"].status == Organization.Status.ACTIVE

    fetched = api.get(f"/api/v1/admin/organizations/{agency['org'].id}/subscription/")
    assert fetched.status_code == 200
    assert fetched.json()["subscription"]["promo_code"] == "LAUNCH20"

    exhausted = api.put(
        f"/api/v1/admin/organizations/{agency['other'].id}/subscription/",
        {"plan_id": plan["id"], "promo_code": "LAUNCH20"},
        format="json",
    )
    assert exhausted.status_code == 400
    assert "redemption limit" in str(exhausted.json()["error"]["details"])

    promo_list = api.get("/api/v1/admin/promo-codes/").json()
    assert promo_list[0]["redeemed"] == 1


def test_fixed_promo_caps_at_plan_price_and_checks_currency(agency):
    api = _platform()
    plan = _create_plan(api, code="solo", price_cents=5000)
    promo = _create_promo(
        api, code="BIGSAVE", kind="fixed", percent_off=None, amount_off_cents=8000, currency="USD"
    )
    assert promo["kind"] == "fixed"

    response = api.put(
        f"/api/v1/admin/organizations/{agency['org'].id}/subscription/",
        {"plan_id": plan["id"], "promo_code": "BIGSAVE"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["discount_cents"] == 5000
    assert response.json()["amount_cents"] == 0

    wrong_currency = api.post(
        "/api/v1/admin/promo-codes/",
        {"code": "EURO10", "kind": "fixed", "amount_off_cents": 1000, "currency": "EUR"},
        format="json",
    )
    assert wrong_currency.status_code == 201
    rejected = api.patch(
        f"/api/v1/admin/organizations/{agency['org'].id}/subscription/",
        {"promo_code": "EURO10"},
        format="json",
    )
    assert rejected.status_code == 400
    assert "different currency" in str(rejected.json()["error"]["details"])


def test_expired_inactive_unknown_and_invalid_promos_are_rejected(agency):
    api = _platform()
    plan = _create_plan(api)
    _create_promo(api, code="EXPIRED", valid_until=(timezone.now() - timedelta(days=1)).isoformat())
    _create_promo(api, code="NOTYET", valid_from=(timezone.now() + timedelta(days=1)).isoformat())
    _create_promo(api, code="OFF", is_active=False)

    def apply(code):
        return api.put(
            f"/api/v1/admin/organizations/{agency['org'].id}/subscription/",
            {"plan_id": plan["id"], "promo_code": code},
            format="json",
        )

    assert apply("EXPIRED").status_code == 400
    assert apply("NOTYET").status_code == 400
    assert apply("OFF").status_code == 400
    assert apply("MISSING").status_code == 400

    bad_percent = api.post(
        "/api/v1/admin/promo-codes/",
        {"code": "ZERO", "kind": "percent", "percent_off": 0},
        format="json",
    )
    assert bad_percent.status_code == 400
    bad_window = api.post(
        "/api/v1/admin/promo-codes/",
        {
            "code": "BACKWARDS",
            "kind": "percent",
            "percent_off": 10,
            "valid_from": (timezone.now() + timedelta(days=2)).isoformat(),
            "valid_until": (timezone.now() + timedelta(days=1)).isoformat(),
        },
        format="json",
    )
    assert bad_window.status_code == 400


def test_subscription_status_drives_read_only_and_restores_writes(agency):
    api = _platform()
    plan = _create_plan(api)
    org = agency["org"]
    url = f"/api/v1/admin/organizations/{org.id}/subscription/"

    past_due = api.put(url, {"plan_id": plan["id"], "status": "past_due"}, format="json")
    assert past_due.status_code == 200, past_due.content
    org.refresh_from_db()
    assert org.status == Organization.Status.PAST_DUE
    assert org.read_only is True
    assert "past due" in org.status_reason.lower()

    recruiter = APIClient()
    login(recruiter, "ravi@sable.test")
    blocked = recruiter.post(
        "/api/v1/jobs/",
        {"title": "Blocked by billing", "client_company_id": str(agency["company"].id), "interview_levels": 1},
        format="json",
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "organization_read_only"
    assert recruiter.get("/api/v1/jobs/").status_code == 200

    restored = api.patch(url, {"status": "active"}, format="json")
    assert restored.status_code == 200, restored.content
    org.refresh_from_db()
    assert org.status == Organization.Status.ACTIVE

    allowed = recruiter.post(
        "/api/v1/jobs/",
        {"title": "Allowed after payment", "client_company_id": str(agency["company"].id), "interview_levels": 1},
        format="json",
    )
    assert allowed.status_code == 201, allowed.content

    canceled = api.patch(url, {"status": "canceled"}, format="json")
    assert canceled.status_code == 200
    org.refresh_from_db()
    assert org.status == Organization.Status.INACTIVE
    assert "canceled" in org.status_reason.lower()


def test_subscription_requires_an_available_plan_and_sane_period(agency):
    api = _platform()
    org = agency["org"]
    url = f"/api/v1/admin/organizations/{org.id}/subscription/"

    assert api.put(url, {"status": "active"}, format="json").status_code == 400

    retired = _create_plan(api, code="retired", is_active=False)
    unavailable = api.put(url, {"plan_id": retired["id"]}, format="json")
    assert unavailable.status_code == 400

    plan = _create_plan(api, code="starter")
    now = timezone.now()
    backwards = api.put(
        url,
        {
            "plan_id": plan["id"],
            "current_period_start": (now + timedelta(days=5)).isoformat(),
            "current_period_end": now.isoformat(),
        },
        format="json",
    )
    assert backwards.status_code == 400

    unknown_status = api.put(url, {"plan_id": plan["id"], "status": "paused"}, format="json")
    assert unknown_status.status_code == 400

    yearly = _create_plan(api, code="annual", price_cents=199000, interval="yearly")
    annual = api.put(url, {"plan_id": yearly["id"]}, format="json")
    assert annual.status_code == 200, annual.content
    subscription = Subscription.objects.get(organization=org)
    assert (subscription.current_period_end - subscription.current_period_start).days == 365
    assert Plan.objects.get(code="annual").subscriptions.count() == 1
