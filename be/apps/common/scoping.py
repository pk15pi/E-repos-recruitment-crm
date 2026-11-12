from apps.clients.models import ClientMembership
from apps.common.tenancy import is_client, require_org
from apps.pipeline.models import CandidateShare


def client_company_ids(request) -> list:
    org = require_org(request)
    return list(
        ClientMembership.objects.filter(user=request.user, organization=org).values_list("company_id", flat=True)
    )


def candidate_queryset(request, include_archived=None):
    from apps.candidates.models import Candidate

    org = require_org(request)
    qs = Candidate.objects.filter(organization=org, merged_into__isnull=True)
    if is_client(request):
        shared = CandidateShare.objects.filter(
            organization=org,
            client_company_id__in=client_company_ids(request),
            revoked_at__isnull=True,
        ).values("candidate_id")
        return qs.filter(id__in=shared, archived_at__isnull=True)
    if include_archived is None:
        raw = getattr(request, "query_params", {})
        include_archived = str(raw.get("include_archived", "")).lower() in {"1", "true", "yes"}
    if not include_archived:
        qs = qs.filter(archived_at__isnull=True)
    return qs


def active_shares(request, candidate_ids):
    if not is_client(request):
        return {}
    shares = CandidateShare.objects.filter(
        organization=request.organization,
        candidate_id__in=list(candidate_ids),
        client_company_id__in=client_company_ids(request),
        revoked_at__isnull=True,
    )
    grouped: dict = {}
    for share in shares:
        current = grouped.get(share.candidate_id)
        if current is None:
            grouped[share.candidate_id] = share
            continue
        current.include_compensation = current.include_compensation or share.include_compensation
        current.include_contact = current.include_contact or share.include_contact
        current.include_resume = current.include_resume or share.include_resume
    return grouped


def can_see_contact(request, candidate, share=None) -> bool:
    if not is_client(request):
        return True
    share = share or active_shares(request, [candidate.id]).get(candidate.id)
    return bool(share and share.include_contact)


def can_see_compensation(request, candidate, share=None) -> bool:
    if not is_client(request):
        return True
    share = share or active_shares(request, [candidate.id]).get(candidate.id)
    return bool(share and share.include_compensation)


def can_download_resume(request, candidate) -> bool:
    if candidate.organization_id != getattr(getattr(request, "organization", None), "id", None):
        return False
    if not is_client(request):
        return True
    share = active_shares(request, [candidate.id]).get(candidate.id)
    return bool(share and share.include_resume)
