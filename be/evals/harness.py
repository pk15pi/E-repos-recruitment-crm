"""Small extraction and filter-violation eval. It scores the configured provider.

The deterministic provider is what runs without an API key. A hosted key is not
called from this harness unless AI_PROVIDER=hosted and AI_API_KEY are both set.
"""

from __future__ import annotations

import re

from apps.candidates.models import Candidate, CandidateSkill, Skill
from apps.jobs.matching import hard_filter
from apps.jobs.models import JobRequirement
from apps.resumes.heuristic import extract_resume
from apps.resumes.normalize import normalize_resume

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)


def _prf(expected: set[str], predicted: set[str]) -> dict:
    true_positive = len(expected & predicted)
    precision = true_positive / len(predicted) if predicted else 1.0
    recall = true_positive / len(expected) if expected else 1.0
    return {"precision": precision, "recall": recall, "true_positive": true_positive}


def score_case(text: str, expected_emails: list[str], expected_skills: list[str]) -> dict:
    raw = extract_resume(text)
    normalized = normalize_resume(raw, text)["profile"]
    emails = {item["email"].lower() for item in normalized["emails"]}
    skills = {item["name"].lower() for item in normalized["skills"]}
    source_emails = {match.lower() for match in EMAIL_RE.findall(text)}
    hallucinated_emails = emails - source_emails
    hallucinated_skills = {name for name in skills if name not in text.lower() and name.split()[0] not in text.lower()}
    return {
        "emails": _prf({item.lower() for item in expected_emails}, emails),
        "skills": _prf({item.lower() for item in expected_skills}, skills),
        "hallucinated": sorted(hallucinated_emails | hallucinated_skills),
    }


def aggregate(cases: list[dict]) -> dict:
    email_p = sum(case["emails"]["precision"] for case in cases) / len(cases)
    email_r = sum(case["emails"]["recall"] for case in cases) / len(cases)
    skill_p = sum(case["skills"]["precision"] for case in cases) / len(cases)
    skill_r = sum(case["skills"]["recall"] for case in cases) / len(cases)
    hallucinations = sum(len(case["hallucinated"]) for case in cases)
    predicted = sum(len(case["hallucinated"]) + case["emails"]["true_positive"] + case["skills"]["true_positive"] for case in cases)
    return {
        "email_precision": email_p,
        "email_recall": email_r,
        "skill_precision": skill_p,
        "skill_recall": skill_r,
        "hallucination_rate": hallucinations / predicted if predicted else 0.0,
        "cases": len(cases),
    }


def filter_violation_rate(organization) -> float:
    """Known hard-filter failures must not remain in the eligible set."""
    weak = Candidate.objects.create(
        organization=organization,
        full_name="Weak Match",
        total_experience_months=6,
        location="Mumbai",
        employment_type="contract",
    )
    blank = Candidate.objects.create(organization=organization, full_name="Fields Missing")
    skill = Skill.objects.create(organization=organization, name="COBOL", normalized_name=f"cobol-{weak.id}")
    CandidateSkill.objects.create(organization=organization, candidate=weak, skill=skill, source="verified")
    requirements = [
        JobRequirement(kind="skill", priority="must_have", value="Python", label="Python"),
        JobRequirement(kind="experience", priority="must_have", value="5+ years", label="5+ years"),
        JobRequirement(kind="employment_type", priority="must_have", value="full_time", label="Full-time"),
    ]
    eligible = set(hard_filter(Candidate.objects.filter(id__in=[weak.id, blank.id]), requirements).values_list("id", flat=True))
    violations = 0
    checked = 0
    if weak.id in eligible:
        violations += 1
    checked += 1
    if blank.id not in eligible:
        violations += 1
    checked += 1
    weak.delete()
    blank.delete()
    return violations / checked
