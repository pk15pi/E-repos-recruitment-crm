"""Deterministic job-description reader. Criteria come only from the pasted text."""

from __future__ import annotations

import re

from apps.candidates.skills import DEFAULT_SKILLS, known_skill_names

CITIES = [
    "Bengaluru",
    "Bangalore",
    "Mumbai",
    "Delhi",
    "New Delhi",
    "Hyderabad",
    "Pune",
    "Chennai",
    "Kochi",
    "Noida",
    "Gurugram",
    "Gurgaon",
    "London",
    "Singapore",
    "Remote",
]
DOMAINS = ["payments", "fintech", "healthcare", "ecommerce", "banking", "saas", "insurance"]
SENIORITY = ["principal", "staff", "senior", "lead", "junior", "mid", "intern"]


def analyze_jd(text: str) -> dict:
    raw = (text or "").strip()
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    title = lines[0][:200] if lines and len(lines[0]) <= 120 else None
    lowered = raw.lower()
    requirements: list[dict] = []
    skills = _skills_with_priority(raw)
    for name, priority in skills:
        requirements.append({"kind": "skill", "label": name, "value": name, "priority": priority})
    min_years, max_years = _years(raw)
    if min_years is not None or max_years is not None:
        label = _years_label(min_years, max_years)
        requirements.append({"kind": "experience", "label": label, "value": label, "priority": "must_have"})
    location = next((city for city in CITIES if re.search(rf"\b{re.escape(city)}\b", raw, re.I)), None)
    if location:
        requirements.append({"kind": "location", "label": location, "value": location, "priority": "must_have"})
    work_mode = _work_mode(lowered)
    if work_mode:
        requirements.append(
            {"kind": "work_mode", "label": work_mode.replace("_", " "), "value": work_mode, "priority": "must_have"}
        )
    employment = _employment(lowered)
    if employment:
        requirements.append(
            {
                "kind": "employment_type",
                "label": employment.replace("_", " "),
                "value": employment,
                "priority": "must_have",
            }
        )
    seniority = next((item for item in SENIORITY if re.search(rf"\b{item}\b", lowered)), None)
    if seniority:
        requirements.append({"kind": "seniority", "label": seniority, "value": seniority, "priority": "preferred"})
    domain = next((item for item in DOMAINS if item in lowered), None)
    if domain:
        requirements.append({"kind": "domain", "label": domain, "value": domain, "priority": "preferred"})
    if title:
        requirements.append({"kind": "title", "label": title, "value": title, "priority": "preferred"})
    notice = re.search(r"notice(?:\s+period)?\s*[:\-]?\s*(\d{1,3})\s*(day|days|month|months)", raw, re.I)
    notice_days = None
    if notice:
        notice_days = int(notice.group(1)) * (30 if notice.group(2).lower().startswith("month") else 1)
        requirements.append(
            {
                "kind": "notice",
                "label": f"Notice within {notice_days} days",
                "value": str(notice_days),
                "priority": "preferred",
            }
        )
    return {
        "title": title,
        "seniority": seniority,
        "domain": domain,
        "min_experience_years": min_years,
        "max_experience_years": max_years,
        "location": location,
        "work_mode": work_mode,
        "employment_type": employment,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "notice_period_days": notice_days,
        "requirements": requirements,
    }


def _skills_with_priority(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    sentences = re.split(r"[\n\.]+", text)
    catalog = []
    for canonical, aliases in DEFAULT_SKILLS.items():
        catalog.append(canonical)
        catalog.extend(aliases)
    catalog.extend(known_skill_names())
    for sentence in sentences:
        lowered = sentence.lower()
        if re.search(r"\b(must|required|mandatory)\b", lowered):
            priority = "must_have"
        elif re.search(r"\b(preferred|nice to have|bonus|plus)\b", lowered):
            priority = "preferred"
        else:
            priority = "preferred"
        for name in catalog:
            if len(name) <= 2 and name.lower() not in {"go", "js", "ml"}:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(name.lower())}(?![a-z0-9])", lowered):
                display = _canonical(name)
                key = display.lower()
                if key in seen:
                    continue
                seen.add(key)
                found.append((display, priority))
    return found


def _canonical(name: str) -> str:
    key = re.sub(r"[^a-z0-9+#]", "", name.lower())
    for canonical, aliases in DEFAULT_SKILLS.items():
        alias_keys = {re.sub(r"[^a-z0-9+#]", "", item.lower()) for item in aliases}
        alias_keys.add(re.sub(r"[^a-z0-9+#]", "", canonical.lower()))
        if key in alias_keys:
            return canonical
    return name


def _years(text: str) -> tuple[float | None, float | None]:
    span = re.search(r"(\d{1,2})\s*(?:–|—|-|to)\s*(\d{1,2})\s*\+?\s*years", text, re.I)
    if span:
        return float(span.group(1)), float(span.group(2))
    minimum = re.search(r"(\d{1,2})\s*\+\s*years", text, re.I)
    if minimum:
        return float(minimum.group(1)), None
    at_least = re.search(r"(?:at least|minimum|min\.?)\s*(\d{1,2})\s*years", text, re.I)
    if at_least:
        return float(at_least.group(1)), None
    return None, None


def _years_label(min_years, max_years) -> str:
    if min_years is not None and max_years is not None:
        return f"{min_years:g}-{max_years:g} years"
    if min_years is not None:
        return f"{min_years:g}+ years"
    return f"up to {max_years:g} years"


def _work_mode(lowered: str) -> str | None:
    if "hybrid" in lowered:
        return "hybrid"
    if re.search(r"\bremote\b", lowered):
        return "remote"
    if re.search(r"on[- ]?site|in[- ]office", lowered):
        return "onsite"
    return None


def _employment(lowered: str) -> str | None:
    if "full-time" in lowered or "full time" in lowered or "permanent" in lowered:
        return "full_time"
    if "part-time" in lowered or "part time" in lowered:
        return "part_time"
    if "contract" in lowered:
        return "contract"
    if "intern" in lowered:
        return "internship"
    return None
