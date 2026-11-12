"""Deterministic resume reader. It only returns strings it can quote from the text."""

from __future__ import annotations

import re

from apps.candidates.skills import known_skill_names

SECTION_MAP = {
    "summary": "summary",
    "professional summary": "summary",
    "profile": "summary",
    "about": "summary",
    "skills": "skills",
    "technical skills": "skills",
    "core skills": "skills",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "employment": "experience",
    "employment history": "experience",
    "education": "education",
    "certifications": "certifications",
    "certificates": "certifications",
    "projects": "projects",
    "languages": "languages",
}

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s\-]?)?(?:\(?\d{2,5}\)?[\s\-]?)?\d{3,5}[\s\-]?\d{3,5}")
LINKEDIN_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+", re.I)
GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/[A-Za-z0-9\-_.]+", re.I)
URL_RE = re.compile(r"https?://[^\s)]+", re.I)
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
    "Dubai",
    "Remote",
]


def extract_resume(text: str, pages: list[dict] | None = None) -> dict:
    raw = text or ""
    sections = _sections(raw)
    header = "\n".join(sections.get("header", []))
    emails = []
    for match in EMAIL_RE.finditer(raw):
        email = match.group(0).strip(".,;")
        if email.lower() not in {item.lower() for item in emails}:
            emails.append(email)
    phones = []
    for match in PHONE_RE.finditer(raw):
        value = match.group(0).strip()
        digits = re.sub(r"\D", "", value)
        if len(digits) < 10 or len(digits) > 15:
            continue
        if digits not in {re.sub(r"\D", "", item) for item in phones}:
            phones.append(value)
    linkedin = _first(LINKEDIN_RE, raw)
    github = _first(GITHUB_RE, raw)
    portfolio = None
    for match in URL_RE.finditer(raw):
        url = match.group(0).rstrip(".,)")
        lowered = url.lower()
        if "linkedin.com" in lowered or "github.com" in lowered:
            continue
        portfolio = url
        break
    experiences = _experiences(sections.get("experience", []))
    education = _education(sections.get("education", []))
    certifications = _certs(sections.get("certifications", []))
    projects = _projects(sections.get("projects", []))
    languages = _languages(sections.get("languages", []))
    skills = _skills(sections.get("skills", []), raw)
    summary = " ".join(line.strip() for line in sections.get("summary", []) if line.strip()) or None
    if summary and len(summary) > 2000:
        summary = summary[:2000]
    current_title = experiences[0]["title"] if experiences else None
    current_employer = experiences[0]["employer"] if experiences else None
    notice = _notice(raw)
    total_years = _stated_years(raw)
    relevant = _relevant_years(raw)
    return {
        "full_name": _name(sections.get("header", [])),
        "emails": emails,
        "phones": phones,
        "location": _location(header, raw),
        "linkedin_url": linkedin,
        "github_url": github,
        "portfolio_url": portfolio,
        "summary": summary,
        "current_title": current_title,
        "current_employer": current_employer,
        "skills": skills,
        "experiences": experiences,
        "education": education,
        "certifications": certifications,
        "projects": projects,
        "languages": languages,
        "notice_period_days": notice,
        "total_experience_years": total_years,
        "relevant_experience_years": relevant,
    }


def _sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in text.splitlines():
        key = line.strip().lower().rstrip(":")
        if key in SECTION_MAP and len(line.strip()) <= 40:
            current = SECTION_MAP[key]
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _name(lines: list[str]) -> str | None:
    for line in lines:
        value = line.strip()
        if not value or "@" in value or "http" in value.lower() or any(char.isdigit() for char in value):
            continue
        words = value.split()
        if not 2 <= len(words) <= 4:
            continue
        if all(re.match(r"[A-Za-z][A-Za-z.'\-]*$", word) for word in words):
            return value
    return None


def _location(header: str, text: str) -> str | None:
    labeled = re.search(r"location\s*[:\-]\s*(.+)", header, re.I)
    if labeled:
        return labeled.group(1).strip()[:200]
    for city in CITIES:
        if re.search(rf"\b{re.escape(city)}\b", header, re.I) or re.search(rf"\b{re.escape(city)}\b", text[:400], re.I):
            return city
    return None


def _skills(section_lines: list[str], text: str) -> list[str]:
    found: list[str] = []
    blob = " ".join(section_lines)
    for piece in re.split(r"[,•|/]|\n|·", blob):
        name = piece.strip(" -\t")
        if 1 < len(name) <= 40 and "@" not in name:
            _push(found, name)
    lowered = text.lower()
    for known in known_skill_names():
        if len(known) <= 2 and known.lower() not in {"go", "js", "ts", "ml", "c#", "c++"}:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(known.lower())}(?![a-z0-9])", lowered):
            _push(found, known if known[0].isupper() or known in {"C#", "C++"} else known)
    # Prefer canonical display for aliases by leaving normalize to map them.
    return found[:40]


def _push(found: list[str], name: str) -> None:
    key = re.sub(r"[^a-z0-9+#]", "", name.lower())
    if not key or key in {re.sub(r"[^a-z0-9+#]", "", item.lower()) for item in found}:
        return
    found.append(name.strip())


def _experiences(lines: list[str]) -> list[dict]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line.strip())
    if current:
        blocks.append(current)
    entries = []
    for block in blocks:
        joined = " \n ".join(block)
        from apps.candidates.dates import RANGE_RE, parse_date_token

        match = RANGE_RE.search(joined)
        if not match:
            continue
        start = match.group("start")
        end_raw = match.group("end")
        is_current = end_raw.lower() in {"present", "current", "now"}
        heading = block[0]
        if RANGE_RE.search(heading) and len(block) > 1:
            heading = block[1] if not RANGE_RE.search(block[0]) else block[0]
        # Prefer a line that is not only the date range.
        heading = next((line for line in block if not RANGE_RE.fullmatch(line.strip()) and len(line) > 3), block[0])
        title, employer = _split_role(heading)
        description_lines = [line for line in block if line != heading and not RANGE_RE.search(line)]
        entries.append(
            {
                "title": title,
                "employer": employer,
                "start": start,
                "end": None if is_current else end_raw,
                "is_current": is_current,
                "location": _location("\n".join(block), ""),
                "description": " ".join(description_lines)[:1000] or None,
            }
        )
        if not parse_date_token(start):
            entries.pop()
    return entries


def _split_role(line: str) -> tuple[str | None, str | None]:
    cleaned = RANGE_RE_LINE.sub("", line).strip(" -–—|,")
    if not cleaned:
        return None, None
    for separator in (" — ", " – ", " - ", " at ", " @ "):
        if separator in cleaned:
            left, right = cleaned.split(separator, 1)
            left, right = left.strip(), right.strip()
            if separator.strip() in {"at", "@"}:
                return left or None, right or None
            # "Title, Employer — dates" already removed dates. "Title, Employer"
            if "," in left:
                title, employer = left.split(",", 1)
                return title.strip() or None, employer.strip() or None
            return left or None, right or None
    if "," in cleaned:
        title, employer = cleaned.split(",", 1)
        return title.strip() or None, employer.strip() or None
    return cleaned, None


RANGE_RE_LINE = re.compile(
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{4}|\d{4}",
    re.I,
)


def _education(lines: list[str]) -> list[dict]:
    entries = []
    for line in lines:
        value = line.strip()
        if not value:
            continue
        years = re.search(r"(\d{4})\s*(?:–|—|-|to)\s*(\d{4}|Present|Current)", value, re.I)
        body = years.string[: years.start()].strip(" -–—,") if years else value
        if "," in body:
            degree, institution = body.split(",", 1)
        else:
            degree, institution = body, ""
        entries.append(
            {
                "degree": degree.strip(" -–—") or None,
                "institution": institution.strip(" -–—") or None,
                "field_of_study": None,
                "start": years.group(1) if years else None,
                "end": years.group(2) if years else None,
            }
        )
    return entries


def _certs(lines: list[str]) -> list[dict]:
    entries = []
    for line in lines:
        value = line.strip()
        if not value:
            continue
        year = re.search(r"(20\d{2}|19\d{2})", value)
        body = value
        if "—" in body or "–" in body:
            body = re.split(r"—|–", body)[0]
        if "," in body:
            name, issuer = body.split(",", 1)
        else:
            name, issuer = body, ""
        entries.append(
            {
                "name": name.strip(" -") or None,
                "issuer": issuer.strip(" -") or None,
                "issued_on": year.group(1) if year else None,
            }
        )
    return entries


def _projects(lines: list[str]) -> list[dict]:
    entries = []
    for line in lines:
        value = line.strip()
        if not value:
            continue
        url = _first(URL_RE, value)
        body = URL_RE.sub("", value).strip(" -–—")
        if "—" in body or "–" in body:
            name, description = re.split(r"—|–", body, maxsplit=1)
        else:
            name, description = body, ""
        entries.append(
            {
                "name": name.strip() or None,
                "description": description.strip() or None,
                "url": url,
                "technologies": None,
            }
        )
    return entries


def _languages(lines: list[str]) -> list[dict]:
    entries = []
    for line in lines:
        value = line.strip()
        if not value:
            continue
        if "—" in value or "–" in value or "-" in value:
            language, proficiency = re.split(r"—|–|-", value, maxsplit=1)
        else:
            language, proficiency = value, ""
        entries.append({"language": language.strip() or None, "proficiency": proficiency.strip() or None})
    return entries


def _notice(text: str) -> int | None:
    match = re.search(r"notice(?:\s+period)?\s*[:\-]?\s*(\d{1,3})\s*(day|days|month|months)", text, re.I)
    if not match:
        return None
    amount = int(match.group(1))
    if match.group(2).lower().startswith("month"):
        amount *= 30
    if amount > 365:
        return None
    return amount


def _stated_years(text: str) -> float | None:
    match = re.search(r"(\d{1,2}(?:\.\d)?)\s*\+?\s+years\s+of\s+experience", text, re.I)
    if not match:
        return None
    value = float(match.group(1))
    return value if value <= 60 else None


def _relevant_years(text: str) -> float | None:
    match = re.search(r"relevant experience\s*[:\-]?\s*(\d{1,2}(?:\.\d)?)\s+years", text, re.I)
    if not match:
        return None
    value = float(match.group(1))
    return value if value <= 60 else None


def _first(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.search(text or "")
    return match.group(0).rstrip(".,)") if match else None
