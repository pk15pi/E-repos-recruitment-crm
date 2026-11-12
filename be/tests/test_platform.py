import pytest
from rest_framework.test import APIClient

from apps.accounts.models import GlobalDataGrant, Organization, OrganizationMembership, User
from tests.conftest import PASSWORD, login

pytestmark = pytest.mark.django_db


def platform_client(email="owner@sable.test") -> APIClient:
    User.objects.create_user(email=email, password=PASSWORD, full_name="Platform Owner", is_platform_admin=True)
    client = APIClient()
    login(client, email)
    return client


def test_only_platform_owners_manage_organizations(agency):
    api = APIClient()
    login(api, "ada@sable.test")
    assert api.post("/api/v1/admin/organizations/", {"name": "Nope"}, format="json").status_code == 403
    assert (
        api.patch(f"/api/v1/admin/organizations/{agency['org'].id}/", {"name": "Nope"}, format="json").status_code
        == 403
    )
    assert (
        api.put(
            f"/api/v1/admin/organizations/{agency['org'].id}/global-access/",
            {"scopes": ["resumes"]},
            format="json",
        ).status_code
        == 403
    )


def test_create_organization_registers_first_agency_admin(agency):
    platform = platform_client()
    response = platform.post(
        "/api/v1/admin/organizations/",
        {
            "name": "Blue Harbor Talent",
            "contact_email": "Desk@BlueHarbor.test",
            "admin_full_name": "Nadia Rao",
            "admin_email": "Nadia@BlueHarbor.test",
            "admin_password": "Blue-Harbor-27",
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    payload = response.json()
    assert payload["slug"] == "blue-harbor-talent"
    assert payload["contact_email"] == "desk@blueharbor.test"
    assert payload["status"] == "active"
    assert payload["global_access"] == []

    organization = Organization.objects.get(id=payload["id"])
    admin = User.objects.get(email="nadia@blueharbor.test")
    membership = OrganizationMembership.objects.get(user=admin, organization=organization)
    assert membership.role == "agency_admin"

    desk = APIClient()
    session = login(desk, "nadia@blueharbor.test", password="Blue-Harbor-27")
    assert session["user"]["membership"]["organization"]["id"] == str(organization.id)

    created = desk.post(
        "/api/v1/admin/users/",
        {
            "email": "recruiter@blueharbor.test",
            "full_name": "Sam Lee",
            "role": "recruiter",
            "password": "Blue-Harbor-28",
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    listed = desk.get("/api/v1/admin/users/").json()
    assert {row["email"] for row in listed} == {"nadia@blueharbor.test", "recruiter@blueharbor.test"}


def test_create_organization_validation(agency):
    platform = platform_client()
    assert platform.post("/api/v1/admin/organizations/", {"name": ""}, format="json").status_code == 400
    assert (
        platform.post(
            "/api/v1/admin/organizations/", {"name": "Dup", "slug": agency["org"].slug}, format="json"
        ).status_code
        == 400
    )
    assert (
        platform.post(
            "/api/v1/admin/organizations/", {"name": "Bad Mail", "contact_email": "not-an-email"}, format="json"
        ).status_code
        == 400
    )
    partial = platform.post(
        "/api/v1/admin/organizations/",
        {"name": "Partial Desk", "admin_email": "someone@example.test"},
        format="json",
    )
    assert partial.status_code == 400
    assert not Organization.objects.filter(name="Partial Desk").exists()

    duplicate = platform.post(
        "/api/v1/admin/organizations/",
        {
            "name": "Another Desk",
            "admin_full_name": "Existing User",
            "admin_email": "ada@sable.test",
            "admin_password": "Harbor-Desk-19",
        },
        format="json",
    )
    assert duplicate.status_code == 400
    assert not Organization.objects.filter(name="Another Desk").exists()


def test_platform_edits_profile_status_and_global_access(agency):
    platform = platform_client()
    organization = agency["org"]
    url = f"/api/v1/admin/organizations/{organization.id}/"

    edited = platform.patch(
        url,
        {
            "name": "Northwind Talent",
            "contact_email": "ops@northwind.test",
            "retention_days": 400,
            "allow_client_see_compensation": True,
        },
        format="json",
    )
    assert edited.status_code == 200, edited.content
    assert edited.json()["name"] == "Northwind Talent"
    assert edited.json()["contact_email"] == "ops@northwind.test"
    organization.refresh_from_db()
    assert organization.retention_days == 400
    assert organization.allow_client_see_compensation is True

    too_short = platform.patch(url, {"retention_days": 5}, format="json")
    assert too_short.status_code == 400

    granted = platform.put(
        f"/api/v1/admin/organizations/{organization.id}/global-access/",
        {"scopes": ["jds", "resumes"]},
        format="json",
    )
    assert granted.status_code == 200, granted.content
    assert granted.json()["scopes"] == ["jds", "resumes"]
    assert sorted(
        GlobalDataGrant.objects.filter(organization=organization).values_list("scope", flat=True)
    ) == ["jds", "resumes"]

    invalid = platform.put(
        f"/api/v1/admin/organizations/{organization.id}/global-access/",
        {"scopes": ["payroll"]},
        format="json",
    )
    assert invalid.status_code == 400
    assert GlobalDataGrant.objects.filter(organization=organization).count() == 2

    replaced = platform.put(
        f"/api/v1/admin/organizations/{organization.id}/global-access/",
        {"scopes": ["clients"]},
        format="json",
    )
    assert replaced.json()["scopes"] == ["clients"]
    assert list(
        GlobalDataGrant.objects.filter(organization=organization).values_list("scope", flat=True)
    ) == ["clients"]

    detail = platform.get(url).json()
    assert detail["global_access"] == ["clients"]

    paused = platform.patch(
        url, {"status": "inactive", "status_reason": "Payment lapsed"}, format="json"
    )
    assert paused.status_code == 200
    assert paused.json()["read_only"] is True
    organization.refresh_from_db()
    assert organization.status == Organization.Status.INACTIVE
    assert organization.status_changed_at is not None

    others = Organization.objects.get(id=agency["other"].id)
    assert others.global_grants.count() == 0


def test_platform_org_list_summaries_and_picker_scope(agency):
    platform = platform_client()
    listing = platform.get("/api/v1/admin/organizations/")
    assert listing.status_code == 200, listing.content
    row = next(item for item in listing.json() if item["id"] == str(agency["org"].id))
    assert row["contact_email"] == ""
    assert row["counts"]["members"] == 4
    assert row["global_access"] == []

    assert platform.get("/api/v1/dashboard/").status_code == 403
    assert platform.get("/api/v1/jobs/").status_code == 403

    login(platform, "owner@sable.test", organization=agency["org"].id)
    dashboard = platform.get("/api/v1/dashboard/")
    assert dashboard.status_code == 200, dashboard.content
    assert dashboard.json()["role_scope"] == "agency"

    members = platform.get("/api/v1/admin/users/").json()
    assert {item["email"] for item in members} == {
        "ada@sable.test",
        "ravi@sable.test",
        "client@sable.test",
        "otherclient@sable.test",
    }

    login(platform, "owner@sable.test", organization=agency["other"].id)
    other_members = platform.get("/api/v1/admin/users/").json()
    assert {item["email"] for item in other_members} == {"outsider@sable.test"}
