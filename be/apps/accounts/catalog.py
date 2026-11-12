"""Platform view of the centralised active-record catalog."""

from django.db.models import Count
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import GlobalDataGrant, Organization
from apps.candidates.models import Candidate
from apps.clients.models import ClientCompany, ClientContact
from apps.common.permissions import PlatformOnly, TenantMixin
from apps.jobs.models import Job

RECENT_LIMIT = 6


def _by_organization(qs) -> dict:
    rows = qs.values("organization_id").annotate(total=Count("id"))
    return {row["organization_id"]: row["total"] for row in rows}


def _recent(qs, label) -> list:
    items = []
    for row in qs.select_related("organization").order_by("-updated_at")[:RECENT_LIMIT]:
        item = {
            "id": str(row.id),
            "organization": {"id": str(row.organization_id), "name": row.organization.name},
            "updated_at": row.updated_at,
        }
        item.update(label(row))
        items.append(item)
    return items


class GlobalCatalogView(TenantMixin, APIView):
    permission_classes = [PlatformOnly]
    allow_missing_org = True

    def get(self, request):
        resumes = Candidate.objects.filter(
            status=Candidate.Status.ACTIVE,
            archived_at__isnull=True,
            merged_into__isnull=True,
        )
        clients = ClientCompany.objects.all()
        contacts = ClientContact.objects.all()
        jobs = Job.objects.filter(status=Job.Status.OPEN)

        resume_counts = _by_organization(resumes)
        client_counts = _by_organization(clients)
        contact_counts = _by_organization(contacts)
        job_counts = _by_organization(jobs)

        organizations = []
        for org in Organization.objects.prefetch_related("global_grants").order_by("name"):
            organizations.append(
                {
                    "id": str(org.id),
                    "name": org.name,
                    "status": org.status,
                    "read_only": org.read_only,
                    "granted_scopes": sorted(grant.scope for grant in org.global_grants.all()),
                    "active_resumes": resume_counts.get(org.id, 0),
                    "clients": client_counts.get(org.id, 0),
                    "customers": contact_counts.get(org.id, 0),
                    "open_jds": job_counts.get(org.id, 0),
                }
            )

        return Response(
            {
                "generated_at": timezone.now(),
                "totals": {
                    "organizations": len(organizations),
                    "granted_organizations": sum(1 for row in organizations if row["granted_scopes"]),
                    "active_resumes": resumes.count(),
                    "clients": clients.count(),
                    "customers": contacts.count(),
                    "open_jds": jobs.count(),
                },
                "scopes": {
                    "resumes": {
                        "key": "resumes",
                        "label": "Active resumes",
                        "count": resumes.count(),
                        "recent": _recent(
                            resumes,
                            lambda row: {
                                "label": row.full_name or "Unnamed candidate",
                                "detail": row.current_title or row.location or "",
                            },
                        ),
                    },
                    "clients": {
                        "key": "clients",
                        "label": "Clients",
                        "count": clients.count(),
                        "recent": _recent(clients, lambda row: {"label": row.name, "detail": row.industry or ""}),
                    },
                    "customers": {
                        "key": "customers",
                        "label": "Client contacts",
                        "count": contacts.count(),
                        "recent": _recent(
                            contacts,
                            lambda row: {"label": row.name, "detail": row.company.name if row.company else ""},
                        ),
                    },
                    "jds": {
                        "key": "jds",
                        "label": "Open job descriptions",
                        "count": jobs.count(),
                        "recent": _recent(
                            jobs,
                            lambda row: {"label": row.title or "Untitled requisition", "detail": row.location or ""},
                        ),
                    },
                },
                "organizations": organizations,
            }
        )
