import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import GlobalDataGrant, User
from apps.candidates.models import Candidate, CandidateEmail, ConsentRecord, RecruiterNote
from apps.clients.models import ClientCompany, ClientContact
from apps.jobs.models import Job, JobRequirement
from tests.conftest import PASSWORD, login

pytestmark = pytest.mark.django_db


def grant(org, *scopes):
    for scope in scopes:
        GlobalDataGrant.objects.create(organization=org, scope=scope)


def make_candidate(org, name, status=Candidate.Status.ACTIVE):
    return Candidate.objects.create(organization=org, full_name=name, current_title="Engineer", status=status)


def make_company(org, name="Beacon Freight", notes="Internal account notes"):
    return ClientCompany.objects.create(
        organization=org, name=name, industry="Logistics", notes=notes, plan=ClientCompany.Plan.PAID
    )


def make_job(org, title="Staff Data Engineer", status=Job.Status.OPEN):
    job = Job.objects.create(organization=org, title=title, status=status, location="Leeds")
    JobRequirement.objects.create(organization=org, job=job, kind="skill", label="Python", value="Python")
    return job


def platform_client(email="owner@sable.test") -> APIClient:
    User.objects.create_user(email=email, password=PASSWORD, full_name="Platform Owner", is_platform_admin=True)
    client = APIClient()
    login(client, email)
    return client


def test_other_organizations_data_stays_private_without_grants(agency):
    foreign = make_candidate(agency["other"], "Priya Nair")
    foreign_company = make_company(agency["other"])
    foreign_job = make_job(agency["other"])

    api = APIClient()
    login(api, "ada@sable.test")

    candidates = api.get("/api/v1/candidates/")
    assert candidates.status_code == 200, candidates.content
    assert candidates.json()["count"] == 0
    assert api.get(f"/api/v1/candidates/{foreign.id}/").status_code == 404
    assert api.get(f"/api/v1/candidates/{foreign.id}/notes/").status_code == 404

    clients = api.get("/api/v1/clients/")
    assert [row["name"] for row in clients.json()] == ["Harbour Labs", "Southwind"]
    assert api.get(f"/api/v1/clients/{foreign_company.id}/").status_code == 404

    jobs = api.get("/api/v1/jobs/")
    assert jobs.status_code == 200
    assert jobs.json()["count"] == 0
    assert api.get(f"/api/v1/jobs/{foreign_job.id}/").status_code == 404


def test_resume_grant_shows_active_global_candidates_read_only(agency):
    grant(agency["org"], GlobalDataGrant.Scope.RESUMES)
    active = make_candidate(agency["other"], "Priya Nair")
    CandidateEmail.objects.create(organization=agency["other"], candidate=active, email="priya@example.test")
    RecruiterNote.objects.create(
        organization=agency["other"], candidate=active, body="Do not poach", visibility="private"
    )
    ConsentRecord.objects.create(
        organization=agency["other"], candidate=active, purpose="Consider for roles", lawful_basis="consent", granted=True
    )
    archived = make_candidate(agency["other"], "Old Record", status=Candidate.Status.ARCHIVED)
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at", "updated_at"])
    make_candidate(agency["other"], "Fresh Upload", status=Candidate.Status.NEW)
    own = make_candidate(agency["org"], "Home Candidate")

    api = APIClient()
    login(api, "ada@sable.test")

    listing = api.get("/api/v1/candidates/")
    assert listing.status_code == 200, listing.content
    rows = listing.json()["results"]
    assert {row["id"] for row in rows} == {str(active.id), str(own.id)}
    global_row = next(row for row in rows if row["id"] == str(active.id))
    assert global_row["is_global"] is True
    assert global_row["owner_organization"]["name"] == "Other Desk"
    assert global_row["primary_email"] == "priya@example.test"
    own_row = next(row for row in rows if row["id"] == str(own.id))
    assert own_row["is_global"] is False
    assert own_row["owner_organization"] is None

    detail = api.get(f"/api/v1/candidates/{active.id}/")
    assert detail.status_code == 200, detail.content
    assert detail.json()["is_global"] is True
    assert detail.json()["notes"] == []
    assert detail.json()["consents"] == []
    assert detail.json()["source"] is None
    assert api.get(f"/api/v1/candidates/{active.id}/notes/").json() == []
    assert api.get(f"/api/v1/candidates/{active.id}/consents/").json() == []

    assert api.patch(f"/api/v1/candidates/{active.id}/", {"full_name": "Nope"}, format="json").status_code == 404
    assert api.post(f"/api/v1/candidates/{active.id}/notes/", {"body": "Hi"}, format="json").status_code == 404
    assert api.post(f"/api/v1/candidates/{active.id}/archive/", {}, format="json").status_code == 404

    search = api.post("/api/v1/search/structured/", {}, format="json")
    assert search.status_code == 200, search.content
    assert {row["id"] for row in search.json()["results"]} == {str(active.id), str(own.id)}

    client_api = APIClient()
    login(client_api, "client@sable.test")
    assert client_api.get("/api/v1/candidates/").json()["count"] == 0


def test_revoking_the_grant_removes_global_rows(agency):
    grant(agency["org"], GlobalDataGrant.Scope.RESUMES)
    make_candidate(agency["other"], "Priya Nair")
    api = APIClient()
    login(api, "ada@sable.test")
    assert api.get("/api/v1/candidates/").json()["count"] == 1

    GlobalDataGrant.objects.filter(organization=agency["org"], scope=GlobalDataGrant.Scope.RESUMES).delete()
    assert api.get("/api/v1/candidates/").json()["count"] == 0


def test_customer_grant_controls_contacts_on_global_clients(agency):
    company = make_company(agency["other"])
    contact = ClientContact.objects.create(organization=agency["other"], company=company, name="Ruth Owen")
    grant(agency["org"], GlobalDataGrant.Scope.CLIENTS)

    api = APIClient()
    login(api, "ada@sable.test")

    listing = api.get("/api/v1/clients/")
    assert listing.status_code == 200, listing.content
    names = [row["name"] for row in listing.json()]
    assert names == ["Harbour Labs", "Southwind", "Beacon Freight"]
    shared = next(row for row in listing.json() if row["name"] == "Beacon Freight")
    assert shared["is_global"] is True
    assert shared["owner_organization"]["name"] == "Other Desk"
    assert shared["plan"] is None
    assert shared["notes"] is None
    assert shared["distribution_enabled"] is False

    detail = api.get(f"/api/v1/clients/{company.id}/")
    assert detail.status_code == 200, detail.content
    assert detail.json()["contacts"] == []
    assert detail.json()["members"] == []

    grant(agency["org"], GlobalDataGrant.Scope.CUSTOMERS)
    detail = api.get(f"/api/v1/clients/{company.id}/")
    assert [row["name"] for row in detail.json()["contacts"]] == ["Ruth Owen"]

    assert api.patch(f"/api/v1/clients/{company.id}/", {"name": "Nope"}, format="json").status_code == 404
    assert (
        api.post(f"/api/v1/clients/{company.id}/contacts/", {"name": "Nope"}, format="json").status_code == 404
    )
    assert api.delete(f"/api/v1/clients/{company.id}/contacts/{contact.id}/").status_code == 404


def test_jd_grant_shows_open_global_jobs_read_only(agency):
    grant(agency["org"], GlobalDataGrant.Scope.JDS)
    open_job = make_job(agency["other"])
    closed_job = make_job(agency["other"], title="Old Role", status=Job.Status.CLOSED)

    api = APIClient()
    login(api, "ada@sable.test")

    listing = api.get("/api/v1/jobs/")
    assert listing.status_code == 200, listing.content
    assert [row["id"] for row in listing.json()["results"]] == [str(open_job.id)]
    row = listing.json()["results"][0]
    assert row["is_global"] is True
    assert row["owner_organization"]["name"] == "Other Desk"
    assert row["client_company"] is None
    assert row["created_by"] is None
    assert api.get(f"/api/v1/jobs/{closed_job.id}/").status_code == 404

    detail = api.get(f"/api/v1/jobs/{open_job.id}/")
    assert detail.status_code == 200, detail.content
    assert [item["label"] for item in detail.json()["requirements"]] == ["Python"]
    assert api.patch(f"/api/v1/jobs/{open_job.id}/", {"title": "Nope"}, format="json").status_code == 404
    assert (
        api.put(
            f"/api/v1/jobs/{open_job.id}/requirements/",
            {"requirements": [{"kind": "skill", "label": "Go", "priority": "must_have"}]},
            format="json",
        ).status_code
        == 404
    )
    assert api.post(f"/api/v1/jobs/{open_job.id}/match/", {}, format="json").status_code == 404
    assert api.get(f"/api/v1/jobs/{open_job.id}/matches/").status_code == 404


def test_platform_catalog_counts_active_records_across_organizations(agency):
    make_candidate(agency["other"], "Priya Nair")
    archived = make_candidate(agency["other"], "Old Record", status=Candidate.Status.ARCHIVED)
    make_company(agency["other"])
    ClientContact.objects.create(organization=agency["other"], company=make_company(agency["other"], "Second Co"), name="Ruth")
    make_job(agency["other"])
    make_job(agency["other"], title="Old Role", status=Job.Status.CLOSED)
    grant(agency["org"], GlobalDataGrant.Scope.CLIENTS)

    agency_api = APIClient()
    login(agency_api, "ada@sable.test")
    assert agency_api.get("/api/v1/admin/global-catalog/").status_code == 403

    platform = platform_client()
    response = platform.get("/api/v1/admin/global-catalog/")
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["totals"]["organizations"] == 2
    assert data["totals"]["granted_organizations"] == 1
    assert data["totals"]["active_resumes"] == 1
    assert data["totals"]["clients"] == 4
    assert data["totals"]["customers"] == 1
    assert data["totals"]["open_jds"] == 1
    assert [item["label"] for item in data["scopes"]["resumes"]["recent"]] == ["Priya Nair"]
    other = next(row for row in data["organizations"] if row["name"] == "Other Desk")
    assert other["active_resumes"] == 1
    assert other["clients"] == 2
    assert other["customers"] == 1
    assert other["open_jds"] == 1
    assert other["granted_scopes"] == []
    northwind = next(row for row in data["organizations"] if row["name"] == "Northwind Search")
    assert northwind["granted_scopes"] == ["clients"]
    assert archived.full_name == "Old Record"
