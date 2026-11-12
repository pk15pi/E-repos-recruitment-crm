from celery import shared_task
from django.utils import timezone

from apps.candidates.models import Task
from apps.common.scoping import candidate_queryset
from apps.search.models import SavedSearch, SavedSearchHit
from apps.search.services import apply_filters, boolean_queryset, hybrid_search


class _Request:
    def __init__(self, user, organization):
        self.user = user
        self.organization = organization
        self.membership = user.memberships.filter(organization=organization, is_active=True).first()
        self.query_params = {}


@shared_task
def notify_saved_searches():
    for saved in SavedSearch.objects.filter(notify_on_new_match=True).select_related("owner", "organization"):
        request = _Request(saved.owner, saved.organization)
        qs = candidate_queryset(request, include_archived=False)
        filters = {row.field: row.value for row in saved.criteria.all()}
        if saved.mode == SavedSearch.Mode.BOOLEAN and saved.boolean_query:
            rows = list(boolean_queryset(apply_filters(qs, filters, hide_unknown=saved.hide_unknown), saved.boolean_query)[:50])
        else:
            rows, _version = hybrid_search(
                qs,
                text=saved.semantic_query,
                boolean_query=saved.boolean_query if saved.mode != SavedSearch.Mode.STRUCTURED else "",
                semantic_text=saved.natural_language or saved.semantic_query,
                filters=filters,
                hide_unknown=saved.hide_unknown,
            )
            rows = list(rows)[:50]
        existing = set(SavedSearchHit.objects.filter(saved_search=saved).values_list("candidate_id", flat=True))
        for candidate in rows:
            if candidate.id in existing:
                continue
            SavedSearchHit.objects.create(saved_search=saved, candidate=candidate)
            Task.objects.get_or_create(
                organization=saved.organization,
                idempotency_key=f"saved:{saved.id}:{candidate.id}",
                defaults={
                    "assigned_to": saved.owner,
                    "created_by": saved.owner,
                    "candidate": candidate,
                    "title": f"New candidate for saved search “{saved.name}”",
                    "notes": "Opened because a saved search with notifications found someone new.",
                    "due_at": timezone.now(),
                },
            )
        saved.last_run_at = timezone.now()
        saved.save(update_fields=["last_run_at", "updated_at"])
