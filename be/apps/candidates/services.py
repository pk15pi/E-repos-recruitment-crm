"""Candidate writes, reindexing, duplicates, merge, and retention purge."""

from __future__ import annotations

import re
from decimal import Decimal

from django.contrib.postgres.search import SearchVector, TrigramSimilarity
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.candidates.models import (
    Candidate,
    CandidateCertification,
    CandidateEducation,
    CandidateEmail,
    CandidateExperience,
    CandidateLanguage,
    CandidatePhone,
    CandidatePreferredLocation,
    CandidateProject,
    CandidateSkill,
    CandidateTag,
    Tag,
)
from apps.candidates.skills import ensure_default_skills, resolve_skill, skill_key
from apps.common.audit import record_audit
from apps.resumes.models import CandidateFieldEvidence

SCALAR_FIELDS = [
    "full_name",
    "summary",
    "current_title",
    "normalized_title",
    "current_employer",
    "location",
    "linkedin_url",
    "github_url",
    "portfolio_url",
    "industry",
    "total_experience_months",
    "relevant_experience_months",
    "notice_period_days",
    "availability_date",
    "work_mode",
    "employment_type",
    "willing_to_relocate",
    "current_salary_amount",
    "current_salary_currency",
    "current_salary_period",
    "expected_salary_amount",
    "expected_salary_currency",
    "expected_salary_period",
    "source",
    "status",
]

SECTION_FIELDS = [
    "emails",
    "phones",
    "skills",
    "experience",
    "education",
    "certifications",
    "projects",
    "languages",
    "preferred_locations",
    "tags",
]


def blank(value) -> bool:
    return value is None or value == "" or value == []


def build_search_document(candidate: Candidate) -> str:
    parts = [
        candidate.full_name,
        candidate.current_title,
        candidate.normalized_title,
        candidate.current_employer,
        candidate.summary,
        candidate.location,
        candidate.industry,
        candidate.linkedin_url,
    ]
    parts += list(candidate.emails.values_list("email", flat=True))
    parts += list(candidate.preferred_locations.values_list("location", flat=True))
    for experience in candidate.experiences.all():
        parts.extend([experience.employer, experience.title, experience.description, experience.location])
    for row in candidate.candidate_skills.select_related("skill"):
        parts.append(row.skill.name)
    for row in candidate.education.all():
        parts.extend([row.institution, row.degree, row.field_of_study])
    for row in candidate.certifications.all():
        parts.extend([row.name, row.issuer])
    for row in candidate.projects.all():
        parts.extend([row.name, row.description, row.technologies])
    for row in candidate.languages.all():
        parts.append(row.language)
    return "\n".join(part.strip() for part in parts if part and str(part).strip())[:100000]


def reindex_candidate(candidate: Candidate) -> None:
    candidate.search_document = build_search_document(candidate)
    candidate.save(update_fields=["search_document", "updated_at"])
    Candidate.objects.filter(pk=candidate.pk).update(
        search_vector=SearchVector("search_document", config="english")
    )


def verified_paths(candidate: Candidate) -> set[str]:
    if not candidate.pk:
        return set()
    return set(
        CandidateFieldEvidence.objects.filter(candidate=candidate, status=CandidateFieldEvidence.Status.VERIFIED)
        .values_list("field_path", flat=True)
    )


@transaction.atomic
def apply_profile(candidate: Candidate, profile: dict, user, *, overwrite_verified: list[str] | None = None, lock_verified: bool = False, mark_verified: bool = False) -> list[str]:
    """Write a profile. When lock_verified is set, verified fields stay unless listed."""
    ensure_default_skills(candidate.organization)
    overwrite = set(overwrite_verified or [])
    locked = verified_paths(candidate) if lock_verified else set()
    skipped = []
    for field in SCALAR_FIELDS:
        if field not in profile:
            continue
        if field in locked and field not in overwrite:
            skipped.append(field)
            continue
        value = profile.get(field)
        if field in {"current_salary_amount", "expected_salary_amount"} and value not in (None, ""):
            value = Decimal(str(value))
        if value is None:
            value = "" if field not in {
                "total_experience_months",
                "relevant_experience_months",
                "notice_period_days",
                "availability_date",
                "willing_to_relocate",
                "current_salary_amount",
                "expected_salary_amount",
            } else None
        setattr(candidate, field, value)
    if not candidate.normalized_title and candidate.current_title:
        candidate.normalized_title = candidate.current_title
    if candidate.pk is None:
        candidate.save()
    else:
        candidate.save()

    if "emails" in profile and _section_open("emails", locked, overwrite):
        candidate.emails.all().delete()
        for item in profile.get("emails") or []:
            email = (item.get("email") or "").strip().lower()
            if email:
                CandidateEmail.objects.create(
                    organization=candidate.organization,
                    candidate=candidate,
                    email=email,
                    label=(item.get("label") or "")[:40],
                    is_primary=bool(item.get("is_primary")),
                )
    elif "emails" in profile:
        skipped.append("emails")

    if "phones" in profile and _section_open("phones", locked, overwrite):
        candidate.phones.all().delete()
        for item in profile.get("phones") or []:
            raw = (item.get("raw") or "").strip()
            if not raw:
                continue
            CandidatePhone.objects.create(
                organization=candidate.organization,
                candidate=candidate,
                raw=raw[:40],
                digits=re.sub(r"\D", "", raw)[:20],
                label=(item.get("label") or "")[:40],
                is_primary=bool(item.get("is_primary")),
            )
    elif "phones" in profile:
        skipped.append("phones")

    if "experiences" in profile and _section_open("experience", locked, overwrite):
        candidate.experiences.all().delete()
        for index, item in enumerate(profile.get("experiences") or []):
            CandidateExperience.objects.create(
                organization=candidate.organization,
                candidate=candidate,
                employer=(item.get("employer") or "")[:200],
                title=(item.get("title") or "")[:200],
                start_date=item.get("start_date") or None,
                end_date=item.get("end_date") or None,
                start_granularity=(item.get("start_granularity") or "")[:8],
                end_granularity=(item.get("end_granularity") or "")[:8],
                is_current=bool(item.get("is_current")),
                location=(item.get("location") or "")[:200],
                description=item.get("description") or "",
                sort_order=index,
            )
    elif "experiences" in profile:
        skipped.append("experience")

    if "skills" in profile and _section_open("skills", locked, overwrite):
        candidate.candidate_skills.all().delete()
        source = CandidateSkill.Source.VERIFIED if mark_verified else CandidateSkill.Source.EXTRACTED
        seen = set()
        for item in profile.get("skills") or []:
            name = item.get("name") if isinstance(item, dict) else str(item)
            skill = resolve_skill(candidate.organization, name or "")
            if skill is None or skill.id in seen:
                continue
            seen.add(skill.id)
            CandidateSkill.objects.create(
                organization=candidate.organization,
                candidate=candidate,
                skill=skill,
                source=source,
                confidence=(item.get("confidence") if isinstance(item, dict) else None),
            )
    elif "skills" in profile:
        skipped.append("skills")

    if "education" in profile and _section_open("education", locked, overwrite):
        candidate.education.all().delete()
        for item in profile.get("education") or []:
            CandidateEducation.objects.create(
                organization=candidate.organization,
                candidate=candidate,
                institution=(item.get("institution") or "")[:200],
                degree=(item.get("degree") or "")[:200],
                field_of_study=(item.get("field_of_study") or "")[:200],
                start_date=item.get("start_date") or None,
                end_date=item.get("end_date") or None,
            )
    elif "education" in profile:
        skipped.append("education")

    if "certifications" in profile and _section_open("certifications", locked, overwrite):
        candidate.certifications.all().delete()
        for item in profile.get("certifications") or []:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            CandidateCertification.objects.create(
                organization=candidate.organization,
                candidate=candidate,
                name=name[:200],
                issuer=(item.get("issuer") or "")[:200],
                issued_on=item.get("issued_on") or None,
                expires_on=item.get("expires_on") or None,
            )
    elif "certifications" in profile:
        skipped.append("certifications")

    if "projects" in profile and _section_open("projects", locked, overwrite):
        candidate.projects.all().delete()
        for item in profile.get("projects") or []:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            CandidateProject.objects.create(
                organization=candidate.organization,
                candidate=candidate,
                name=name[:200],
                description=item.get("description") or "",
                url=item.get("url") or "",
                technologies=(item.get("technologies") or "")[:400],
            )
    elif "projects" in profile:
        skipped.append("projects")

    if "languages" in profile and _section_open("languages", locked, overwrite):
        candidate.languages.all().delete()
        for item in profile.get("languages") or []:
            language = (item.get("language") or "").strip()
            if language:
                CandidateLanguage.objects.create(
                    organization=candidate.organization,
                    candidate=candidate,
                    language=language[:80],
                    proficiency=(item.get("proficiency") or "")[:80],
                )
    elif "languages" in profile:
        skipped.append("languages")

    if "preferred_locations" in profile and _section_open("preferred_locations", locked, overwrite):
        candidate.preferred_locations.all().delete()
        for value in profile.get("preferred_locations") or []:
            if str(value).strip():
                CandidatePreferredLocation.objects.create(
                    organization=candidate.organization,
                    candidate=candidate,
                    location=str(value).strip()[:200],
                )
    if "tags" in profile and _section_open("tags", locked, overwrite):
        candidate.candidate_tags.all().delete()
        for value in profile.get("tags") or []:
            name = str(value.get("name") if isinstance(value, dict) else value).strip()
            if not name:
                continue
            kind = Tag.Kind.POOL if isinstance(value, dict) and value.get("kind") == "pool" else Tag.Kind.TAG
            tag, _ = Tag.objects.get_or_create(organization=candidate.organization, kind=kind, name=name[:80])
            CandidateTag.objects.get_or_create(candidate=candidate, tag=tag)

    if mark_verified:
        _mark_evidence_verified(candidate, user, profile)
        candidate.verification_status = Candidate.Verification.VERIFIED
        candidate.save(update_fields=["verification_status", "updated_at"])
    reindex_candidate(candidate)
    return skipped


def _section_open(name: str, locked: set[str], overwrite: set[str]) -> bool:
    return name not in locked or name in overwrite


def _mark_evidence_verified(candidate, user, profile) -> None:
    now = timezone.now()
    CandidateFieldEvidence.objects.filter(candidate=candidate, status=CandidateFieldEvidence.Status.VERIFIED).exclude(
        extraction__isnull=False
    ).delete()
    rows = []
    for path in ["full_name", "summary", "current_title", "current_employer", "location", "emails", "phones", "skills", "experience", "education"]:
        value = profile.get(path if path != "experience" else "experiences", profile.get(path))
        text = value if isinstance(value, str) else ""
        status = CandidateFieldEvidence.Status.VERIFIED if not blank(value) else CandidateFieldEvidence.Status.MISSING
        rows.append(
            CandidateFieldEvidence(
                organization=candidate.organization,
                candidate=candidate,
                field_path=path,
                value_text=str(text)[:500],
                status=status,
                confidence=1 if status == CandidateFieldEvidence.Status.VERIFIED else None,
                verified_by=user,
                verified_at=now if status == CandidateFieldEvidence.Status.VERIFIED else None,
            )
        )
    CandidateFieldEvidence.objects.bulk_create(rows)


def find_duplicates(organization, profile: dict, exclude_id=None) -> list[dict]:
    found: list[dict] = []
    seen = set()

    def add(kind, candidate, detail, blocking):
        key = (kind, str(candidate.id))
        if key in seen:
            return
        seen.add(key)
        found.append(
            {
                "kind": kind,
                "candidate_id": str(candidate.id),
                "name": candidate.full_name or "Unnamed candidate",
                "detail": detail[:200],
                "blocking": blocking,
            }
        )

    base = Candidate.objects.filter(organization=organization, merged_into__isnull=True, archived_at__isnull=True)
    if exclude_id:
        base = base.exclude(id=exclude_id)
    emails = [item.get("email", "").lower() for item in profile.get("emails") or [] if item.get("email")]
    if emails:
        for row in CandidateEmail.objects.filter(organization=organization, email__in=emails).select_related("candidate"):
            if exclude_id and row.candidate_id == exclude_id:
                continue
            add("email", row.candidate, row.email, True)
    digits = [re.sub(r"\D", "", item.get("raw") or "")[-10:] for item in profile.get("phones") or []]
    digits = [item for item in digits if len(item) >= 10]
    if digits:
        query = Q()
        for item in digits:
            query |= Q(digits__endswith=item)
        for row in CandidatePhone.objects.filter(organization=organization).filter(query).select_related("candidate"):
            if exclude_id and row.candidate_id == exclude_id:
                continue
            add("phone", row.candidate, row.raw, True)
    linkedin = (profile.get("linkedin_url") or "").strip()
    if linkedin:
        for candidate in base.filter(linkedin_url__iexact=linkedin):
            add("linkedin", candidate, linkedin, True)
    name = (profile.get("full_name") or "").strip()
    employers = {(item.get("employer") or "").strip().lower() for item in profile.get("experiences") or [] if item.get("employer")}
    if name:
        similar = (
            base.annotate(sim=TrigramSimilarity("full_name", name))
            .filter(sim__gt=0.72)
            .order_by("-sim")[:8]
        )
        for candidate in similar:
            history = candidate.experiences.filter(employer__isnull=False)
            shared = False
            if employers:
                for experience in history:
                    if experience.employer.strip().lower() in employers:
                        shared = True
                        break
            if shared:
                add("history", candidate, "Similar name and overlapping employment history.", False)
            else:
                add("name", candidate, "Similar name. Review before merging. Names are not merged automatically.", False)
    return found


@transaction.atomic
def merge_candidates(target: Candidate, source: Candidate, user, request) -> Candidate:
    if target.organization_id != source.organization_id:
        raise ValueError("Candidates belong to different organizations.")
    if target.id == source.id:
        raise ValueError("Choose two different candidates.")
    for email in source.emails.all():
        if not target.emails.filter(email__iexact=email.email).exists():
            email.candidate = target
            email.save(update_fields=["candidate"])
    for phone in source.phones.all():
        if phone.digits and not target.phones.filter(digits=phone.digits).exists():
            phone.candidate = target
            phone.save(update_fields=["candidate"])
    for collection in ("experiences", "education", "certifications", "projects", "languages", "notes"):
        for row in getattr(source, collection).all():
            row.candidate = target
            row.save(update_fields=["candidate"])
    for row in source.candidate_skills.select_related("skill"):
        if not target.candidate_skills.filter(skill=row.skill).exists():
            row.candidate = target
            row.save(update_fields=["candidate"])
    source.resumes.update(candidate=target)
    source.status = Candidate.Status.ARCHIVED
    source.archived_at = timezone.now()
    source.merged_into = target
    source.save(update_fields=["status", "archived_at", "merged_into", "updated_at"])
    reindex_candidate(target)
    record_audit(request, "candidate_merge", target, "Merged another candidate into this record")
    return target


def purge_candidate(candidate: Candidate, request=None) -> None:
    from apps.common.storage import get_storage

    storage = get_storage()
    for resume in candidate.resumes.all():
        for key in (resume.storage_key, resume.quarantine_key):
            if key:
                try:
                    storage.delete(key)
                except Exception:
                    pass
        resume.extracted_text = ""
        resume.save(update_fields=["extracted_text", "updated_at"])
    organization = candidate.organization
    object_id = str(candidate.id)
    candidate.delete()
    from apps.audit.models import AuditEvent

    actor = None
    if request is not None and getattr(request.user, "is_authenticated", False):
        actor = request.user
    AuditEvent.objects.create(
        organization=organization,
        actor=actor,
        action="retention_delete",
        object_type="Candidate",
        object_id=object_id,
        detail="Personal data deleted",
        ip_address=getattr(request, "META", {}).get("REMOTE_ADDR") if request is not None else None,
    )


def profile_from_candidate(candidate: Candidate) -> dict:
    return {
        "full_name": candidate.full_name,
        "summary": candidate.summary,
        "current_title": candidate.current_title,
        "normalized_title": candidate.normalized_title,
        "current_employer": candidate.current_employer,
        "location": candidate.location,
        "linkedin_url": candidate.linkedin_url,
        "github_url": candidate.github_url,
        "portfolio_url": candidate.portfolio_url,
        "industry": candidate.industry,
        "total_experience_months": candidate.total_experience_months,
        "relevant_experience_months": candidate.relevant_experience_months,
        "notice_period_days": candidate.notice_period_days,
        "availability_date": candidate.availability_date.isoformat() if candidate.availability_date else None,
        "work_mode": candidate.work_mode,
        "employment_type": candidate.employment_type,
        "willing_to_relocate": candidate.willing_to_relocate,
        "current_salary_amount": candidate.current_salary_amount,
        "current_salary_currency": candidate.current_salary_currency,
        "current_salary_period": candidate.current_salary_period,
        "expected_salary_amount": candidate.expected_salary_amount,
        "expected_salary_currency": candidate.expected_salary_currency,
        "expected_salary_period": candidate.expected_salary_period,
        "source": candidate.source,
        "status": candidate.status,
        "emails": [{"email": row.email, "label": row.label, "is_primary": row.is_primary} for row in candidate.emails.all()],
        "phones": [{"raw": row.raw, "label": row.label, "is_primary": row.is_primary} for row in candidate.phones.all()],
        "skills": [
            {"name": row.skill.name, "source": row.source, "confidence": row.confidence}
            for row in candidate.candidate_skills.select_related("skill")
        ],
        "experiences": [
            {
                "employer": row.employer,
                "title": row.title,
                "start_date": row.start_date.isoformat() if row.start_date else None,
                "end_date": row.end_date.isoformat() if row.end_date else None,
                "is_current": row.is_current,
                "location": row.location,
                "description": row.description,
            }
            for row in candidate.experiences.all()
        ],
        "education": [
            {
                "institution": row.institution,
                "degree": row.degree,
                "field_of_study": row.field_of_study,
                "start_date": row.start_date.isoformat() if row.start_date else None,
                "end_date": row.end_date.isoformat() if row.end_date else None,
            }
            for row in candidate.education.all()
        ],
        "certifications": [
            {"name": row.name, "issuer": row.issuer, "issued_on": row.issued_on, "expires_on": row.expires_on}
            for row in candidate.certifications.all()
        ],
        "projects": [
            {"name": row.name, "description": row.description, "url": row.url, "technologies": row.technologies}
            for row in candidate.projects.all()
        ],
        "languages": [{"language": row.language, "proficiency": row.proficiency} for row in candidate.languages.all()],
        "preferred_locations": list(candidate.preferred_locations.values_list("location", flat=True)),
        "tags": [row.tag.name for row in candidate.candidate_tags.select_related("tag")],
    }


def skill_keys_for(candidate: Candidate) -> set[str]:
    keys = set()
    for row in candidate.candidate_skills.select_related("skill"):
        keys.add(row.skill.normalized_name)
        keys.add(skill_key(row.skill.name))
    return keys
