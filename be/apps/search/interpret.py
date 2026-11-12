"""Turn a natural-language request into an editable search plan. Never SQL."""

from __future__ import annotations

import re

from apps.candidates.skills import DEFAULT_SKILLS
from apps.search.boolean import BooleanSyntaxError, parse_boolean

STOP = {
    "a",
    "an",
    "the",
    "who",
    "with",
    "and",
    "or",
    "of",
    "for",
    "in",
    "on",
    "to",
    "find",
    "show",
    "candidates",
    "candidate",
    "people",
    "someone",
    "that",
    "have",
    "has",
    "looking",
    "need",
    "please",
}
CITIES = ["Bengaluru", "Bangalore", "Mumbai", "Delhi", "Hyderabad", "Pune", "Chennai", "Remote", "London"]


def deterministic_plan(text: str) -> dict:
    raw = " ".join((text or "").split())
    filters = []
    lowered = raw.lower()
    for city in CITIES:
        if re.search(rf"\b{re.escape(city)}\b", raw, re.I):
            filters.append({"field": "location", "operator": "icontains", "value": city})
            break
    years = re.search(r"(\d{1,2})\s*\+?\s*years", lowered)
    if years:
        filters.append({"field": "experience_min_months", "operator": "gte", "value": str(int(years.group(1)) * 12)})
    if "remote" in lowered:
        filters.append({"field": "work_mode", "operator": "eq", "value": "remote"})
    elif "hybrid" in lowered:
        filters.append({"field": "work_mode", "operator": "eq", "value": "hybrid"})
    skill_terms = []
    for canonical, aliases in DEFAULT_SKILLS.items():
        names = [canonical, *aliases]
        if any(re.search(rf"(?<![a-z0-9]){re.escape(name.lower())}(?![a-z0-9])", lowered) for name in names):
            skill_terms.append(canonical)
            filters.append({"field": "skill", "operator": "eq", "value": canonical})
    words = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+.#]{2,}", raw):
        if token.lower() in STOP:
            continue
        if any(token.lower() == city.lower() for city in CITIES):
            continue
        if token.lower() in {item.lower() for item in skill_terms}:
            continue
        words.append(token)
    terms = skill_terms[:6] + words[:6]
    if not terms:
        boolean_query = ""
        notes = "No searchable terms were found. Add skills or a title before running the search."
    else:
        boolean_query = " AND ".join(f'"{term}"' if " " in term else term for term in terms[:8])
        notes = "Review the plan before running it. Nothing here was executed as SQL."
        try:
            parse_boolean(boolean_query)
        except BooleanSyntaxError:
            boolean_query = " AND ".join(re.sub(r"[^A-Za-z0-9+#]", "", term) for term in terms if term)
            parse_boolean(boolean_query)
    return {"boolean_query": boolean_query, "filters": filters, "notes": notes}
