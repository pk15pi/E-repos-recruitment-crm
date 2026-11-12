"""Validate model output against the resume text. Unsupported values are dropped, not guessed."""

from __future__ import annotations

import re

from apps.ai.constants import LOW_CONFIDENCE
from apps.ai.provider import skill_mentioned, supported_phrase
from apps.candidates.dates import experience_months, parse_date_token

EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.I)


def normalize_resume(raw: dict, source_text: str, pages: list[dict] | None = None) -> dict:
    source = source_text or ""
    pages = pages or [{"page": 1, "text": source}]
    warnings: list[str] = []
    fields: list[dict] = []

    def evidence(path, label, value, quote, confidence, status=None):
        if status is None:
            if value in (None, "", []):
                status = "missing"
                confidence = None
            elif confidence is not None and confidence < LOW_CONFIDENCE:
                status = "needs_review"
            else:
                status = "extracted"
        fields.append(
            {
                "path": path,
                "label": label,
                "value": value if not isinstance(value, (list, dict)) else value,
                "status": status,
                "confidence": confidence,
                "quote": (quote or "")[:400],
                "page": _page(quote, pages),
                "low_confidence": bool(confidence is not None and confidence < LOW_CONFIDENCE),
            }
        )

    def keep_text(value: str | None) -> str:
        if not value or not supported_phrase(str(value), source):
            if value:
                warnings.append(f"Omitted unsupported value for “{str(value)[:80]}”.")
            return ""
        return " ".join(str(value).split())

    full_name = keep_text(raw.get("full_name"))
    evidence("full_name", "Full name", full_name, full_name, 0.55 if full_name else None)

    emails = []
    for item in raw.get("emails") or []:
        email = str(item).strip()
        if EMAIL_RE.match(email) and email.lower() in source.lower():
            emails.append({"email": email.lower(), "is_primary": not emails, "label": ""})
        elif email:
            warnings.append("Omitted an email that was not present in the resume text.")
    evidence("emails", "Emails", ", ".join(item["email"] for item in emails), emails[0]["email"] if emails else "", 0.95 if emails else None)

    phones = []
    source_digits = re.sub(r"\D", "", source)
    for item in raw.get("phones") or []:
        raw_phone = str(item).strip()
        digits = re.sub(r"\D", "", raw_phone)
        if len(digits) >= 10 and digits in source_digits:
            phones.append({"raw": raw_phone, "is_primary": not phones, "label": ""})
        elif raw_phone:
            warnings.append("Omitted a phone number that was not present in the resume text.")
    evidence("phones", "Phones", ", ".join(item["raw"] for item in phones), phones[0]["raw"] if phones else "", 0.8 if phones else None)

    location = keep_text(raw.get("location"))
    evidence("location", "Location", location, location, 0.7 if location else None)
    summary = keep_text(raw.get("summary"))
    evidence("summary", "Summary", summary, summary[:180] if summary else "", 0.7 if summary else None)

    experiences = []
    for index, item in enumerate(raw.get("experiences") or []):
        if not isinstance(item, dict):
            continue
        title = keep_text(item.get("title"))
        employer = keep_text(item.get("employer"))
        description = keep_text(item.get("description")) if item.get("description") else ""
        start_token = item.get("start") or ""
        end_token = item.get("end") or ""
        is_current = bool(item.get("is_current")) or str(end_token).lower() in {"present", "current", "now"}
        start = parse_date_token(str(start_token), end=False) if start_token and _token_in_source(str(start_token), source) else None
        if start_token and start is None and _token_in_source(str(start_token), source):
            warnings.append("An experience date could not be parsed.")
        end = None
        if not is_current and end_token and _token_in_source(str(end_token), source):
            end = parse_date_token(str(end_token), end=True)
        if not any([title, employer, start]):
            continue
        experiences.append(
            {
                "title": title,
                "employer": employer,
                "start_date": start[0].isoformat() if start else None,
                "end_date": None if is_current else (end[0].isoformat() if end else None),
                "start_granularity": start[1] if start else "",
                "end_granularity": "" if is_current else (end[1] if end else ""),
                "is_current": is_current,
                "location": keep_text(item.get("location")) if item.get("location") else "",
                "description": description,
            }
        )
    # Current role is the first current entry, else the first entry. Do not invent one.
    current = next((item for item in experiences if item["is_current"]), experiences[0] if experiences else None)
    current_title = current["title"] if current else ""
    current_employer = current["employer"] if current else ""
    if raw.get("current_title") and not current_title:
        current_title = keep_text(raw.get("current_title"))
    if raw.get("current_employer") and not current_employer:
        current_employer = keep_text(raw.get("current_employer"))
    evidence("current_title", "Current title", current_title, current_title, 0.75 if current_title else None)
    evidence("current_employer", "Current employer", current_employer, current_employer, 0.75 if current_employer else None)
    evidence(
        "experience",
        "Employment history",
        f"{len(experiences)} roles" if experiences else "",
        experiences[0]["employer"] if experiences else "",
        0.75 if experiences else None,
    )

    computed = experience_months(experiences)
    stated = raw.get("total_experience_years")
    stated_months = None
    if isinstance(stated, (int, float)) and _years_supported(stated, source):
        stated_months = int(round(float(stated) * 12))
    total_months = computed
    total_status = "extracted" if computed is not None else "missing"
    if computed is not None and stated_months is not None and abs(computed - stated_months) > 6:
        total_status = "conflicting"
        warnings.append("Stated years and employment dates disagree. The date calculation was kept.")
    elif computed is None and stated_months is not None:
        total_months = stated_months
        total_status = "needs_review"
    evidence(
        "total_experience_months",
        "Total experience",
        total_months,
        f"{total_months} months" if total_months is not None else "",
        0.8 if computed is not None else (0.5 if total_months is not None else None),
        status=total_status if total_months is not None or total_status == "conflicting" else "missing",
    )

    relevant = raw.get("relevant_experience_years")
    relevant_months = None
    if isinstance(relevant, (int, float)) and re.search(r"relevant experience", source, re.I):
        relevant_months = int(round(float(relevant) * 12))
    evidence(
        "relevant_experience_months",
        "Relevant experience",
        relevant_months,
        "",
        0.5 if relevant_months is not None else None,
        status="needs_review" if relevant_months is not None else "missing",
    )

    skills = []
    for item in raw.get("skills") or []:
        name = str(item).strip()
        if name and skill_mentioned(name, source):
            skills.append({"name": name, "confidence": 0.8})
        elif name:
            warnings.append(f"Omitted skill “{name[:40]}” because it was not found in the resume text.")
    evidence("skills", "Skills", ", ".join(item["name"] for item in skills), skills[0]["name"] if skills else "", 0.8 if skills else None)

    education = []
    for item in raw.get("education") or []:
        if not isinstance(item, dict):
            continue
        institution = keep_text(item.get("institution"))
        degree = keep_text(item.get("degree"))
        field = keep_text(item.get("field_of_study")) if item.get("field_of_study") else ""
        if not institution and not degree:
            continue
        education.append(
            {
                "institution": institution,
                "degree": degree,
                "field_of_study": field,
                "start_date": _iso(item.get("start"), source, end=False),
                "end_date": _iso(item.get("end"), source, end=True),
            }
        )
    evidence("education", "Education", f"{len(education)} records" if education else "", "", 0.7 if education else None)

    certifications = []
    for item in raw.get("certifications") or []:
        if not isinstance(item, dict):
            continue
        name = keep_text(item.get("name"))
        if not name:
            continue
        certifications.append(
            {
                "name": name,
                "issuer": keep_text(item.get("issuer")) if item.get("issuer") else "",
                "issued_on": _iso(item.get("issued_on"), source, end=False),
                "expires_on": None,
            }
        )
    evidence("certifications", "Certifications", f"{len(certifications)} records" if certifications else "", "", 0.7 if certifications else None)

    projects = []
    for item in raw.get("projects") or []:
        if not isinstance(item, dict):
            continue
        name = keep_text(item.get("name"))
        if not name:
            continue
        url = item.get("url") or ""
        if url and url not in source:
            url = ""
        projects.append(
            {
                "name": name,
                "description": keep_text(item.get("description")) if item.get("description") else "",
                "url": url,
                "technologies": keep_text(item.get("technologies")) if item.get("technologies") else "",
            }
        )
    evidence("projects", "Projects", f"{len(projects)} records" if projects else "", "", 0.7 if projects else None)

    languages = []
    for item in raw.get("languages") or []:
        if not isinstance(item, dict):
            continue
        language = keep_text(item.get("language"))
        if not language:
            continue
        languages.append({"language": language, "proficiency": keep_text(item.get("proficiency")) if item.get("proficiency") else ""})
    evidence("languages", "Languages", ", ".join(item["language"] for item in languages), "", 0.7 if languages else None)

    def url_field(key, label):
        value = raw.get(key) or ""
        if value and str(value) in source:
            kept = str(value).strip()
        else:
            if value:
                warnings.append(f"Omitted {label.lower()} because it was not present in the resume text.")
            kept = ""
        evidence(key, label, kept, kept, 0.9 if kept else None)
        return kept

    linkedin = url_field("linkedin_url", "LinkedIn")
    github = url_field("github_url", "GitHub")
    portfolio = url_field("portfolio_url", "Portfolio")

    notice = raw.get("notice_period_days")
    if not isinstance(notice, int) or not re.search(rf"\b{notice}\b", source):
        if notice:
            warnings.append("Omitted notice period because it was not present in the resume text.")
        notice = None
    evidence("notice_period_days", "Notice period", notice, "", 0.7 if notice is not None else None)

    profile = {
        "full_name": full_name,
        "summary": summary,
        "current_title": current_title,
        "normalized_title": _normalize_title(current_title),
        "current_employer": current_employer,
        "location": location,
        "linkedin_url": linkedin,
        "github_url": github,
        "portfolio_url": portfolio,
        "industry": "",
        "total_experience_months": total_months,
        "relevant_experience_months": relevant_months,
        "notice_period_days": notice,
        "availability_date": None,
        "work_mode": "",
        "employment_type": "",
        "willing_to_relocate": None,
        "current_salary_amount": None,
        "current_salary_currency": "",
        "current_salary_period": "",
        "expected_salary_amount": None,
        "expected_salary_currency": "",
        "expected_salary_period": "",
        "source": "resume",
        "emails": emails,
        "phones": phones,
        "skills": skills,
        "experiences": experiences,
        "education": education,
        "certifications": certifications,
        "projects": projects,
        "languages": languages,
        "preferred_locations": [],
        "tags": [],
    }
    return {"profile": profile, "fields": fields, "warnings": warnings}


def _normalize_title(title: str) -> str:
    if not title:
        return ""
    cleaned = " ".join(title.replace("Sr.", "Senior").replace("Jr.", "Junior").split())
    return cleaned[:200]


def _page(quote: str, pages: list[dict]):
    if not quote:
        return None
    needle = quote.lower()[:180]
    for page in pages:
        if needle and needle in (page.get("text") or "").lower():
            return page.get("page")
    return None


def _token_in_source(token: str, source: str) -> bool:
    compact = re.sub(r"\s+", " ", token).strip().lower()
    return bool(compact) and compact in re.sub(r"\s+", " ", source).lower()


def _years_supported(years, source: str) -> bool:
    text = f"{float(years):g}"
    return text in source or str(int(years)) in source


def _iso(token, source: str, end: bool):
    if not token or not _token_in_source(str(token), source):
        return None
    parsed = parse_date_token(str(token), end=end)
    if not parsed:
        return None
    return parsed[0].isoformat()
