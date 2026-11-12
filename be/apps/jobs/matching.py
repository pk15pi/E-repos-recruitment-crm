"""Hard filters run in SQL before any model is asked to explain a candidate."""

from __future__ import annotations

import re

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Count, F, Q
from pgvector.django import CosineDistance

from apps.ai.service import execute
from apps.candidates.models import Candidate, CandidateSkill
from apps.candidates.skills import skill_key
from apps.jobs.models import Job, JobRequirement, MatchEvidence, MatchResult
from apps.jobs.scoring import WEIGHTS, SCORE_VERSION, component_ratio, finalize_score, reciprocal_rank_fusion


def hard_filter(qs, requirements: list[JobRequirement]):
    must = [item for item in requirements if item.priority == JobRequirement.Priority.MUST]
    skill_must = [item for item in must if item.kind in {JobRequirement.Kind.SKILL, JobRequirement.Kind.TOOL}]
    if skill_must:
        qs = qs.annotate(skill_count=Count("candidate_skills", distinct=True))
        for requirement in skill_must:
            keys = _requirement_keys(requirement.value)
            having = CandidateSkill.objects.filter(skill__normalized_name__in=keys).values("candidate_id")
            qs = qs.filter(Q(skill_count=0) | Q(id__in=having))
    for requirement in must:
        if requirement.kind == JobRequirement.Kind.LOCATION and requirement.value:
            loc = requirement.value.strip()
            qs = qs.annotate(
                pref_count=Count("preferred_locations", distinct=True),
                loc_hit=Count(
                    "preferred_locations",
                    filter=Q(preferred_locations__location__icontains=loc),
                    distinct=True,
                ),
            ).filter(
                Q(location__icontains=loc)
                | Q(loc_hit__gt=0)
                | (Q(location="") & Q(pref_count=0))
            )
        elif requirement.kind == JobRequirement.Kind.WORK_MODE and requirement.value:
            qs = qs.filter(Q(work_mode=requirement.value) | Q(work_mode=""))
        elif requirement.kind == JobRequirement.Kind.EMPLOYMENT_TYPE and requirement.value:
            qs = qs.filter(Q(employment_type=requirement.value) | Q(employment_type=""))
        elif requirement.kind == JobRequirement.Kind.EXPERIENCE:
            minimum, maximum = _experience_bounds(requirement)
            if minimum is not None:
                qs = qs.filter(Q(total_experience_months__gte=minimum) | Q(total_experience_months__isnull=True))
            if maximum is not None:
                qs = qs.filter(Q(total_experience_months__lte=maximum) | Q(total_experience_months__isnull=True))
        elif requirement.kind == JobRequirement.Kind.NOTICE and requirement.value.isdigit():
            limit = int(requirement.value)
            qs = qs.filter(Q(notice_period_days__lte=limit) | Q(notice_period_days__isnull=True))
    return qs.distinct()


def match_job(job: Job) -> dict:
    requirements = list(job.requirements.all())
    base = Candidate.objects.filter(
        organization=job.organization, archived_at__isnull=True, merged_into__isnull=True
    )
    eligible = hard_filter(base, requirements)
    query_text = " ".join(
        part
        for part in [job.title, job.domain, job.original_description[:500]]
        + [item.value for item in requirements if item.kind in {JobRequirement.Kind.SKILL, JobRequirement.Kind.TOOL, JobRequirement.Kind.TITLE}]
        if part
    )[:2000]
    lexical_ids: list = []
    if query_text.strip():
        search_query = SearchQuery(query_text, config="english")
        lexical_ids = list(
            eligible.filter(search_vector=search_query)
            .annotate(rank=SearchRank(F("search_vector"), search_query))
            .order_by("-rank")
            .values_list("id", flat=True)[:80]
        )
    skill_keys = []
    for requirement in requirements:
        if requirement.kind in {JobRequirement.Kind.SKILL, JobRequirement.Kind.TOOL}:
            skill_keys.extend(_requirement_keys(requirement.value))
    skill_ids = []
    if skill_keys:
        skill_ids = list(
            eligible.filter(candidate_skills__skill__normalized_name__in=skill_keys)
            .values_list("id", flat=True)
            .distinct()[:150]
        )
    semantic_ids: list = []
    embed_result = execute(job.organization, "generate_embedding", "generate_embedding", job.original_description or job.title or "")
    vector = (embed_result.data or {}).get("embedding")
    if vector:
        semantic_ids = list(
            eligible.exclude(embedding__isnull=True)
            .order_by(CosineDistance("embedding", vector))
            .values_list("id", flat=True)[:80]
        )
    fused = reciprocal_rank_fusion([lexical_ids, semantic_ids])
    pool = list(dict.fromkeys([*skill_ids, *lexical_ids, *semantic_ids]))[:200]
    if not pool:
        pool = list(eligible.order_by("-updated_at").values_list("id", flat=True)[:50])
    candidates = eligible.filter(id__in=pool).prefetch_related(
        "candidate_skills__skill", "experiences", "preferred_locations", "education", "certifications"
    )
    lexical_rank = {item: index for index, item in enumerate(lexical_ids, start=1)}
    semantic_rank = {item: index for index, item in enumerate(semantic_ids, start=1)}
    max_rrf = max(fused.values()) if fused else 0
    scored = []
    for candidate in candidates:
        scored.append(
            _score_candidate(
                candidate,
                job,
                requirements,
                fused.get(candidate.id, 0.0),
                max_rrf,
                lexical_rank.get(candidate.id),
                semantic_rank.get(candidate.id),
            )
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    MatchResult.objects.filter(job=job).delete()
    for item in scored:
        result = MatchResult.objects.create(
            organization=job.organization,
            job=job,
            candidate_id=item["candidate_id"],
            score=item["score"],
            score_version=SCORE_VERSION,
            mandatory_met=item["mandatory_met"],
            mandatory_unknown=item["mandatory_unknown"],
            mandatory_unmet=item["mandatory_unmet"],
            preferred_matched=item["preferred_matched"],
            preferred_total=item["preferred_total"],
            explanation=item["explanation"],
            lexical_rank=item["lexical_rank"],
            semantic_rank=item["semantic_rank"],
        )
        MatchEvidence.objects.bulk_create(
            [
                MatchEvidence(
                    match=result,
                    kind=evidence["kind"],
                    status=evidence["status"],
                    detail=evidence["detail"][:400],
                    quote=(evidence.get("quote") or "")[:400],
                )
                for evidence in item["evidence"]
            ]
        )
    job.score_version = SCORE_VERSION
    job.save(update_fields=["score_version", "updated_at"])
    return {"score_version": SCORE_VERSION, "weights": WEIGHTS, "pool_size": len(scored)}


def _score_candidate(candidate, job, requirements, rrf_score, max_rrf, lexical_rank, semantic_rank):
    skills = {row.skill.normalized_name: row for row in candidate.candidate_skills.all()}
    skill_count = len(skills)
    evidence = []
    mandatory_met = mandatory_unknown = mandatory_unmet = 0
    preferred_matched = preferred_total = 0
    must_skill_met = must_skill_unmet = 0
    pref_skill_met = pref_skill_unmet = 0
    experience_part = None
    location_part = None
    title_part = None

    for requirement in requirements:
        if requirement.priority == JobRequirement.Priority.INFO:
            evidence.append({"kind": requirement.kind, "status": "informational", "detail": requirement.label, "quote": ""})
            continue
        status, detail, quote = _check(candidate, requirement, skills, skill_count)
        evidence.append({"kind": requirement.kind, "status": status, "detail": detail, "quote": quote})
        if requirement.priority == JobRequirement.Priority.MUST:
            if status == "met":
                mandatory_met += 1
            elif status == "unknown":
                mandatory_unknown += 1
            elif status == "unmet":
                mandatory_unmet += 1
            if requirement.kind in {JobRequirement.Kind.SKILL, JobRequirement.Kind.TOOL}:
                if status == "met":
                    must_skill_met += 1
                elif status == "unmet":
                    must_skill_unmet += 1
        elif requirement.priority == JobRequirement.Priority.PREFERRED:
            preferred_total += 1
            if status == "met":
                preferred_matched += 1
            if requirement.kind in {JobRequirement.Kind.SKILL, JobRequirement.Kind.TOOL}:
                if status == "met":
                    pref_skill_met += 1
                elif status == "unmet":
                    pref_skill_unmet += 1
        if requirement.kind == JobRequirement.Kind.EXPERIENCE and requirement.priority == JobRequirement.Priority.MUST:
            if status == "unknown":
                experience_part = None
            else:
                experience_part = WEIGHTS["experience"] if status == "met" else 0
        if requirement.kind == JobRequirement.Kind.LOCATION and requirement.priority == JobRequirement.Priority.MUST:
            location_part = None if status == "unknown" else (WEIGHTS["location"] if status == "met" else 0)
        if requirement.kind == JobRequirement.Kind.TITLE:
            title_part = None if status == "unknown" else (WEIGHTS["title"] if status == "met" else 0)

    if experience_part is None and job.min_experience_months:
        if candidate.total_experience_months is None:
            experience_part = None
            evidence.append({"kind": "experience", "status": "unknown", "detail": "Total experience was not provided.", "quote": ""})
        else:
            ok = candidate.total_experience_months >= job.min_experience_months and (
                job.max_experience_months is None or candidate.total_experience_months <= job.max_experience_months
            )
            experience_part = WEIGHTS["experience"] if ok else 0
    retrieval = None
    if max_rrf:
        retrieval = WEIGHTS["retrieval"] * (rrf_score / max_rrf)
    elif lexical_rank or semantic_rank:
        retrieval = WEIGHTS["retrieval"]
    parts = [
        ("mandatory", component_ratio(must_skill_met, must_skill_unmet, WEIGHTS["mandatory"])),
        ("preferred", component_ratio(pref_skill_met, pref_skill_unmet, WEIGHTS["preferred"])),
        ("experience", experience_part),
        ("title", title_part),
        ("location", location_part),
        ("retrieval", retrieval),
    ]
    # Count non-skill mandatory checks inside the mandatory weight when there are no skill checks.
    if must_skill_met + must_skill_unmet == 0:
        other_met = sum(1 for item in evidence if item["status"] == "met" and item["kind"] not in {"skill", "tool"})
        other_unmet = sum(1 for item in evidence if item["status"] == "unmet" and item["kind"] not in {"skill", "tool"})
        parts[0] = ("mandatory", component_ratio(other_met, other_unmet, WEIGHTS["mandatory"]))
    score = finalize_score(parts)
    try:
        explanation = execute(
            job.organization,
            "generate_match_explanation",
            "generate_match_explanation",
            evidence,
            candidate.full_name,
        ).data["explanation"]
    except Exception:
        explanation = ""
    if not explanation:
        from apps.ai.provider import _template_explanation

        explanation = _template_explanation(evidence, candidate.full_name)
    return {
        "candidate_id": candidate.id,
        "score": score,
        "mandatory_met": mandatory_met,
        "mandatory_unknown": mandatory_unknown,
        "mandatory_unmet": mandatory_unmet,
        "preferred_matched": preferred_matched,
        "preferred_total": preferred_total,
        "explanation": explanation,
        "lexical_rank": lexical_rank,
        "semantic_rank": semantic_rank,
        "evidence": evidence,
    }


def _check(candidate, requirement, skills, skill_count):
    kind = requirement.kind
    value = (requirement.value or "").strip()
    if kind in {JobRequirement.Kind.SKILL, JobRequirement.Kind.TOOL}:
        if skill_count == 0:
            return "unknown", f"{requirement.label}: skills were not provided.", ""
        keys = _requirement_keys(value)
        matched = [row for key, row in skills.items() if key in keys]
        if matched:
            source = matched[0].source
            label = "verified" if source == "verified" else "extracted, not yet verified" if source == "extracted" else "on file"
            return "met", f"{requirement.label} ({label})", matched[0].skill.name
        return "unmet", f"{requirement.label} is not on the profile.", ""
    if kind == JobRequirement.Kind.EXPERIENCE:
        if candidate.total_experience_months is None:
            return "unknown", "Total experience was not provided.", ""
        minimum, maximum = _experience_bounds(requirement)
        months = candidate.total_experience_months
        if minimum is not None and months < minimum:
            return "unmet", f"Experience is {months} months, below {minimum}.", ""
        if maximum is not None and months > maximum:
            return "unmet", f"Experience is {months} months, above {maximum}.", ""
        return "met", f"Experience on file is {months} months.", ""
    if kind == JobRequirement.Kind.LOCATION:
        locations = [candidate.location] + [row.location for row in candidate.preferred_locations.all()]
        known = [item for item in locations if item]
        if not known:
            return "unknown", "Location was not provided.", ""
        if any(value.lower() in item.lower() for item in known):
            return "met", f"Location matches {value}.", known[0]
        return "unmet", f"Location on file does not match {value}.", known[0]
    if kind == JobRequirement.Kind.WORK_MODE:
        if not candidate.work_mode:
            return "unknown", "Work mode was not provided.", ""
        if candidate.work_mode == value:
            return "met", f"Work mode is {candidate.work_mode}.", ""
        return "unmet", f"Work mode is {candidate.work_mode}, not {value}.", ""
    if kind == JobRequirement.Kind.EMPLOYMENT_TYPE:
        if not candidate.employment_type:
            return "unknown", "Employment type was not provided.", ""
        if candidate.employment_type == value:
            return "met", f"Employment type is {candidate.employment_type}.", ""
        return "unmet", f"Employment type is {candidate.employment_type}, not {value}.", ""
    if kind == JobRequirement.Kind.TITLE:
        title = candidate.normalized_title or candidate.current_title
        if not title:
            return "unknown", "Title was not provided.", ""
        if _tokens_overlap(title, value):
            return "met", f"Title on file: {title}.", title
        return "unmet", f"Title on file is {title}.", title
    if kind == JobRequirement.Kind.DOMAIN:
        haystack = " ".join(filter(None, [candidate.industry, candidate.summary, candidate.search_document[:2000]])).lower()
        if not haystack.strip():
            return "unknown", "Domain was not provided.", ""
        if value.lower() in haystack:
            return "met", f"Domain “{value}” appears on the profile.", value
        return "unmet", f"Domain “{value}” was not found on the profile.", ""
    if kind in {JobRequirement.Kind.EDUCATION, JobRequirement.Kind.CERTIFICATION}:
        rows = candidate.education.all() if kind == JobRequirement.Kind.EDUCATION else candidate.certifications.all()
        if not rows:
            return "unknown", f"{requirement.label} was not provided.", ""
        blob = " ".join(
            " ".join(filter(None, [getattr(row, "degree", ""), getattr(row, "institution", ""), getattr(row, "name", ""), getattr(row, "issuer", "")]))
            for row in rows
        ).lower()
        if value.lower() in blob:
            return "met", f"{requirement.label} is on file.", value
        return "unmet", f"{requirement.label} is not on file.", ""
    return "unknown", requirement.label, ""


def _requirement_keys(value: str) -> set[str]:
    from apps.candidates.models import SkillAlias

    key = skill_key(value)
    keys = {key}
    alias = SkillAlias.objects.filter(alias=key).select_related("skill").first()
    if alias:
        keys.add(alias.skill.normalized_name)
    return {item for item in keys if item}


def _experience_bounds(requirement: JobRequirement) -> tuple[int | None, int | None]:
    numbers = [int(item) for item in re.findall(r"\d+", requirement.value or "")]
    if not numbers:
        return None, None
    if len(numbers) >= 2:
        return numbers[0] * 12, numbers[1] * 12
    if "+" in (requirement.value or "") or "least" in (requirement.value or "").lower():
        return numbers[0] * 12, None
    return numbers[0] * 12, None


def _tokens_overlap(left: str, right: str) -> bool:
    stop = {"senior", "junior", "the", "and", "of"}
    left_tokens = {token for token in re.findall(r"[a-z0-9]+", left.lower()) if token not in stop and len(token) > 2}
    right_tokens = {token for token in re.findall(r"[a-z0-9]+", right.lower()) if token not in stop and len(token) > 2}
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) >= 1
