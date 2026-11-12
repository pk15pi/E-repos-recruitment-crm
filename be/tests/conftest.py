import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import Organization, OrganizationMembership, User
from apps.clients.models import ClientCompany, ClientMembership

PASSWORD = "Harbor-Desk-19"


@pytest.fixture(autouse=True)
def _test_environment(settings):
    settings.SABLE_TESTING = True
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.ALLOW_UNSCANNED_UPLOADS = True
    settings.AI_PROVIDER = "deterministic"
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def agency(db):
    org = Organization.objects.create(
        name="Northwind Search",
        slug="northwind",
        privacy_notice="We process candidate data to introduce people to client roles.",
    )
    other = Organization.objects.create(name="Other Desk", slug="other-desk")
    admin = User.objects.create_user(email="ada@sable.test", password=PASSWORD, full_name="Ada Menon")
    recruiter = User.objects.create_user(email="ravi@sable.test", password=PASSWORD, full_name="Ravi Iyer")
    client_user = User.objects.create_user(email="client@sable.test", password=PASSWORD, full_name="Meera Shah")
    outsider = User.objects.create_user(email="outsider@sable.test", password=PASSWORD, full_name="Outsider")
    other_client = User.objects.create_user(email="otherclient@sable.test", password=PASSWORD, full_name="Other Client")
    OrganizationMembership.objects.create(organization=org, user=admin, role="agency_admin")
    OrganizationMembership.objects.create(organization=org, user=recruiter, role="recruiter")
    OrganizationMembership.objects.create(organization=org, user=client_user, role="client_admin")
    OrganizationMembership.objects.create(organization=org, user=other_client, role="client_admin")
    OrganizationMembership.objects.create(organization=other, user=outsider, role="recruiter")
    company = ClientCompany.objects.create(
        organization=org, name="Harbour Labs", industry="Payments", plan=ClientCompany.Plan.PAID
    )
    second = ClientCompany.objects.create(organization=org, name="Southwind", industry="Logistics")
    ClientMembership.objects.create(organization=org, company=company, user=client_user, role="client_admin")
    ClientMembership.objects.create(organization=org, company=second, user=other_client, role="client_admin")
    return {
        "org": org,
        "other": other,
        "admin": admin,
        "recruiter": recruiter,
        "client": client_user,
        "other_client": other_client,
        "outsider": outsider,
        "company": company,
        "second": second,
        "password": PASSWORD,
    }


def login(api, email, password=PASSWORD, organization=None):
    response = api.post("/api/v1/auth/login/", {"email": email, "password": password}, format="json")
    assert response.status_code == 200, response.content
    token = response.json()["access"]
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    if organization is not None:
        headers["HTTP_X_ORGANIZATION_ID"] = str(organization)
    api.credentials(**headers)
    return response.json()
