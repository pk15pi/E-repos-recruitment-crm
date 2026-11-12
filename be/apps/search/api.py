from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.candidates.present import candidate_card
from apps.common.global_access import candidates_visible_to
from apps.common.permissions import AgencyOnly, TenantMixin
from apps.common.scoping import active_shares
from apps.common.tenancy import is_client, require_org
from apps.search.boolean import BooleanSyntaxError
from apps.search.models import SavedSearch, SavedSearchCriterion, SearchHistory
from apps.search.services import HYBRID_VERSION, apply_filters, boolean_queryset, hybrid_search

ALLOWED_FIELDS = {
    "location",
    "title",
    "employer",
    "skill",
    "skills",
    "work_mode",
    "employment_type",
    "industry",
    "experience_min_months",
    "experience_max_months",
    "notice_max_days",
    "status",
    "tag",
    "verification_status",
    "source",
}


class StructuredSearchView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request):
        filters = _filters(request.data.get("filters") or request.data)
        hide_unknown = bool(request.data.get("hide_unknown"))
        qs = apply_filters(candidates_visible_to(request), filters, hide_unknown=hide_unknown).order_by("-updated_at")
        _remember(request, "structured", str(filters)[:500])
        return _respond(qs, request)


class BooleanSearchView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request):
        expression = request.data.get("query") or ""
        filters = _filters(request.data.get("filters") or {})
        hide_unknown = bool(request.data.get("hide_unknown"))
        qs = apply_filters(candidates_visible_to(request), filters, hide_unknown=hide_unknown)
        try:
            qs = boolean_queryset(qs, expression)
        except BooleanSyntaxError as exc:
            raise ValidationError({"query": f"{exc} (position {exc.position})"}) from exc
        _remember(request, "boolean", expression[:500])
        return _respond(qs, request)


class InterpretView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request):
        text = (request.data.get("text") or "").strip()
        if len(text) < 3:
            raise ValidationError({"text": "Describe who you are looking for."})
        if len(text) > 4000:
            raise ValidationError({"text": "That request is too long."})
        from apps.ai.provider import ProviderError
        from apps.ai.service import execute
        from apps.search.boolean import parse_boolean

        try:
            result = execute(request.organization, "interpret_search", "interpret_search", text)
        except ProviderError as exc:
            return Response({"error": {"code": exc.code, "message": str(exc), "details": {}}}, status=503)
        plan = result.data
        if plan.get("boolean_query"):
            try:
                parse_boolean(plan["boolean_query"])
            except BooleanSyntaxError as exc:
                return Response(
                    {
                        "error": {
                            "code": "invalid_plan",
                            "message": "The interpreted query is not valid boolean syntax. Edit it before running.",
                            "details": {"position": exc.position},
                        }
                    },
                    status=422,
                )
        for item in plan.get("filters") or []:
            if item.get("field") not in ALLOWED_FIELDS:
                return Response(
                    {"error": {"code": "invalid_plan", "message": "The plan used a filter that is not allowed.", "details": item}},
                    status=422,
                )
        _remember(request, "natural", text[:500])
        return Response(
            {
                "plan": plan,
                "provider": result.provider,
                "provider_label": result.label,
                "executed": False,
            }
        )


class HybridSearchView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request):
        filters = _filters(request.data.get("filters") or {})
        try:
            rows, version = hybrid_search(
                candidates_visible_to(request),
                text=request.data.get("query") or "",
                boolean_query=request.data.get("boolean_query") or "",
                semantic_text=request.data.get("semantic_query") or request.data.get("query") or "",
                filters=filters,
                hide_unknown=bool(request.data.get("hide_unknown")),
            )
        except BooleanSyntaxError as exc:
            raise ValidationError({"boolean_query": str(exc)}) from exc
        _remember(request, "hybrid", (request.data.get("query") or request.data.get("boolean_query") or "")[:500])
        return _respond(rows, request, score_version=version)


class SavedSearchView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def get(self, request):
        rows = SavedSearch.objects.filter(organization=require_org(request), owner=request.user).prefetch_related("criteria")
        return Response([_saved(row) for row in rows])

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "Name this search."})
        mode = request.data.get("mode") or "structured"
        if mode not in SavedSearch.Mode.values:
            raise ValidationError({"mode": "Unknown search mode."})
        boolean_query = request.data.get("boolean_query") or ""
        if boolean_query:
            from apps.search.boolean import parse_boolean

            try:
                parse_boolean(boolean_query)
            except BooleanSyntaxError as exc:
                raise ValidationError({"boolean_query": str(exc)}) from exc
        saved = SavedSearch.objects.create(
            organization=request.organization,
            owner=request.user,
            name=name[:160],
            mode=mode,
            boolean_query=boolean_query,
            natural_language=(request.data.get("natural_language") or "")[:4000],
            semantic_query=(request.data.get("semantic_query") or "")[:2000],
            notify_on_new_match=bool(request.data.get("notify_on_new_match")),
            hide_unknown=bool(request.data.get("hide_unknown")),
        )
        for item in _filter_rows(request.data.get("filters") or {}):
            SavedSearchCriterion.objects.create(saved_search=saved, field=item["field"], operator="eq", value=str(item["value"])[:300])
        return Response(_saved(saved), status=201)


class SavedSearchDetailView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def get(self, request, search_id):
        return Response(_saved(_own(request, search_id)))

    def patch(self, request, search_id):
        saved = _own(request, search_id)
        if "name" in request.data:
            saved.name = str(request.data["name"])[:160]
        if "notify_on_new_match" in request.data:
            saved.notify_on_new_match = bool(request.data["notify_on_new_match"])
        saved.save()
        return Response(_saved(saved))

    def delete(self, request, search_id):
        _own(request, search_id).delete()
        return Response(status=204)


class SavedSearchRunView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request, search_id):
        saved = _own(request, search_id)
        filters = {row.field: row.value for row in saved.criteria.all()}
        qs = candidates_visible_to(request)
        if saved.mode == SavedSearch.Mode.BOOLEAN and saved.boolean_query:
            try:
                rows = boolean_queryset(apply_filters(qs, filters, hide_unknown=saved.hide_unknown), saved.boolean_query)
            except BooleanSyntaxError as exc:
                raise ValidationError({"boolean_query": str(exc)}) from exc
            version = None
        else:
            rows, version = hybrid_search(
                qs,
                text=saved.semantic_query,
                boolean_query=saved.boolean_query,
                semantic_text=saved.natural_language or saved.semantic_query,
                filters=filters,
                hide_unknown=saved.hide_unknown,
            )
        saved.last_run_at = timezone.now()
        saved.save(update_fields=["last_run_at", "updated_at"])
        return _respond(rows, request, score_version=version)


class SearchHistoryView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def get(self, request):
        rows = SearchHistory.objects.filter(organization=require_org(request), user=request.user)[:50]
        return Response(
            [{"id": str(row.id), "mode": row.mode, "query_text": row.query_text, "created_at": row.created_at} for row in rows]
        )


def _filters(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError({"filters": "Filters must be an object."})
    unknown = set(payload) - ALLOWED_FIELDS - {"hide_unknown"}
    if unknown:
        raise ValidationError({"filters": f"Unknown filters: {', '.join(sorted(unknown))}."})
    return payload


def _filter_rows(filters: dict) -> list[dict]:
    rows = []
    for key, value in _filters(filters).items():
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            for item in value:
                rows.append({"field": key, "value": item})
        else:
            rows.append({"field": key, "value": value})
    return rows


def _remember(request, mode, text):
    if is_client(request):
        raise PermissionDenied()
    SearchHistory.objects.create(organization=request.organization, user=request.user, mode=mode, query_text=text[:500])


def _respond(rows, request, score_version=None):
    if hasattr(rows, "count") and not isinstance(rows, list):
        from apps.jobs.api import _paginate

        data = _paginate(rows, request)
        items = data["rows"]
        count = data["count"]
        nxt, prev = data["next"], data["previous"]
    else:
        items = list(rows)
        count = len(items)
        try:
            page = max(1, int(request.query_params.get("page") or 1))
            size = min(100, max(1, int(request.query_params.get("page_size") or 25)))
        except ValueError as exc:
            raise ValidationError("Page parameters must be numbers.") from exc
        start = (page - 1) * size
        items = items[start : start + size]
        nxt = prev = None
    shares = active_shares(request, [row.id for row in items])
    results = []
    for row in items:
        card = candidate_card(row, request, shares.get(row.id))
        if hasattr(row, "hybrid_score"):
            card["score"] = row.hybrid_score
            card["score_version"] = score_version or HYBRID_VERSION
        results.append(card)
    return Response({"count": count, "next": nxt, "previous": prev, "results": results, "score_version": score_version})


def _saved(row: SavedSearch) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "mode": row.mode,
        "boolean_query": row.boolean_query,
        "natural_language": row.natural_language,
        "semantic_query": row.semantic_query,
        "notify_on_new_match": row.notify_on_new_match,
        "hide_unknown": row.hide_unknown,
        "filters": {item.field: item.value for item in row.criteria.all()},
        "last_run_at": row.last_run_at,
        "created_at": row.created_at,
    }


def _own(request, search_id) -> SavedSearch:
    row = SavedSearch.objects.filter(organization=require_org(request), owner=request.user, id=search_id).first()
    if row is None:
        from rest_framework.exceptions import NotFound

        raise NotFound()
    return row
