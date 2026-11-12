"""Authorized candidate search. Filters are structured; boolean queries become SearchQuery objects."""

from __future__ import annotations

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Count, F, Q, QuerySet
from pgvector.django import CosineDistance

from apps.ai.service import execute
from apps.candidates.models import CandidateSkill
from apps.candidates.skills import skill_key
from apps.jobs.scoring import reciprocal_rank_fusion
from apps.search.boolean import BooleanSyntaxError, parse_boolean, to_search_query

HYBRID_VERSION = "sable-hybrid-v1"


def apply_filters(qs: QuerySet, filters: dict, *, hide_unknown: bool = False) -> QuerySet:
    filters = filters or {}
    text_fields = {
        "location": "location",
        "title": "current_title",
        "employer": "current_employer",
        "industry": "industry",
    }
    for key, field in text_fields.items():
        value = (filters.get(key) or "").strip()
        if not value:
            continue
        lookup = {f"{field}__icontains": value}
        if hide_unknown:
            qs = qs.filter(**lookup)
        else:
            qs = qs.filter(Q(**lookup) | Q(**{field: ""}))
    for key, field in {"work_mode": "work_mode", "employment_type": "employment_type", "status": "status", "verification_status": "verification_status", "source": "source"}.items():
        value = (filters.get(key) or "").strip()
        if not value:
            continue
        if key in {"work_mode", "employment_type"} and not hide_unknown:
            qs = qs.filter(Q(**{field: value}) | Q(**{field: ""}))
        else:
            qs = qs.filter(**{field: value})
    if filters.get("experience_min_months") not in (None, ""):
        minimum = int(filters["experience_min_months"])
        qs = qs.filter(total_experience_months__gte=minimum) if hide_unknown else qs.filter(
            Q(total_experience_months__gte=minimum) | Q(total_experience_months__isnull=True)
        )
    if filters.get("experience_max_months") not in (None, ""):
        maximum = int(filters["experience_max_months"])
        qs = qs.filter(total_experience_months__lte=maximum) if hide_unknown else qs.filter(
            Q(total_experience_months__lte=maximum) | Q(total_experience_months__isnull=True)
        )
    if filters.get("notice_max_days") not in (None, ""):
        limit = int(filters["notice_max_days"])
        qs = qs.filter(notice_period_days__lte=limit) if hide_unknown else qs.filter(
            Q(notice_period_days__lte=limit) | Q(notice_period_days__isnull=True)
        )
    skills = filters.get("skills") or ([] if not filters.get("skill") else [filters.get("skill")])
    if isinstance(skills, str):
        skills = [skills]
    for skill in skills:
        if not skill:
            continue
        key = skill_key(str(skill))
        having = CandidateSkill.objects.filter(
            Q(skill__normalized_name=key) | Q(skill__aliases__alias=key) | Q(skill__name__iexact=str(skill))
        ).values("candidate_id")
        if hide_unknown:
            qs = qs.filter(id__in=having)
        else:
            qs = qs.annotate(**{f"skill_count_{key[:12]}": Count("candidate_skills", distinct=True)}).filter(
                Q(id__in=having) | Q(**{f"skill_count_{key[:12]}": 0})
            )
    tag = (filters.get("tag") or "").strip()
    if tag:
        qs = qs.filter(candidate_tags__tag__name__iexact=tag)
    return qs.distinct()


def boolean_queryset(qs: QuerySet, expression: str) -> QuerySet:
    node = parse_boolean(expression)
    query = to_search_query(node)
    return qs.filter(search_vector=query).annotate(rank=SearchRank(F("search_vector"), query)).order_by("-rank")


def hybrid_search(qs: QuerySet, *, text: str = "", boolean_query: str = "", semantic_text: str = "", filters: dict | None = None, hide_unknown: bool = False):
    filtered = apply_filters(qs, filters or {}, hide_unknown=hide_unknown)
    lexical_ids: list = []
    if boolean_query:
        try:
            lexical_ids = list(boolean_queryset(filtered, boolean_query).values_list("id", flat=True)[:80])
        except BooleanSyntaxError:
            raise
    elif text:
        query = SearchQuery(text, search_type="websearch", config="english")
        lexical_ids = list(
            filtered.filter(Q(search_vector=query) | Q(full_name__icontains=text) | Q(current_title__icontains=text))
            .annotate(rank=SearchRank(F("search_vector"), query))
            .order_by("-rank")
            .values_list("id", flat=True)[:80]
        )
    semantic_ids: list = []
    if semantic_text:
        embedding = execute(None, "generate_embedding", "generate_embedding", semantic_text)
        vector = (embedding.data or {}).get("embedding")
        if vector:
            semantic_ids = list(
                filtered.exclude(embedding__isnull=True).order_by(CosineDistance("embedding", vector)).values_list("id", flat=True)[:80]
            )
    fused = reciprocal_rank_fusion([lexical_ids, semantic_ids])
    if not fused and not text and not boolean_query and not semantic_text:
        return filtered.order_by("-updated_at"), HYBRID_VERSION
    if not fused:
        ids = lexical_ids or semantic_ids
        if not ids:
            return filtered.none(), HYBRID_VERSION
        ordering = {value: index for index, value in enumerate(ids)}
        rows = list(filtered.filter(id__in=ids))
        rows.sort(key=lambda row: ordering.get(row.id, 10_000))
        return rows, HYBRID_VERSION
    ordered = sorted(fused, key=fused.get, reverse=True)
    rows = list(filtered.filter(id__in=ordered))
    rows.sort(key=lambda row: fused.get(row.id, 0), reverse=True)
    for row in rows:
        row.hybrid_score = round(100 * fused[row.id] / max(fused.values()), 2)
    return rows, HYBRID_VERSION
