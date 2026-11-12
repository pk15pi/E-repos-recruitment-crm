"""Read-only views of the global catalog for organizations the platform granted."""

from apps.accounts.models import GlobalDataGrant
from apps.common.tenancy import is_client


def is_foreign(request, row) -> bool:
    organization = getattr(request, "organization", None)
    return bool(organization and row.organization_id != organization.id)


def owner_organization(row) -> dict:
    return {"id": str(row.organization_id), "name": row.organization.name}


def can_read_global(request, scope: str) -> bool:
    organization = getattr(request, "organization", None)
    if organization is None or is_client(request):
        return False
    return GlobalDataGrant.objects.filter(organization=organization, scope=scope).exists()


def global_candidates(organization):
    from apps.candidates.models import Candidate

    return Candidate.objects.filter(
        status=Candidate.Status.ACTIVE,
        archived_at__isnull=True,
        merged_into__isnull=True,
    ).exclude(organization=organization)


def global_clients(organization):
    from apps.clients.models import ClientCompany

    return ClientCompany.objects.exclude(organization=organization)


def global_contacts(organization):
    from apps.clients.models import ClientContact

    return ClientContact.objects.exclude(organization=organization)


def global_jobs(organization):
    from apps.jobs.models import Job

    return Job.objects.filter(status=Job.Status.OPEN).exclude(organization=organization)


def candidates_visible_to(request):
    from apps.common.scoping import candidate_queryset

    qs = candidate_queryset(request)
    organization = getattr(request, "organization", None)
    if not can_read_global(request, GlobalDataGrant.Scope.RESUMES):
        return qs
    return (qs | global_candidates(organization)).distinct().select_related("organization")
