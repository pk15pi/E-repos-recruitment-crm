import re
from datetime import date

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_MONTH = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
DATE_TOKEN = rf"(?:(?:{_MONTH})\.?\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
RANGE_RE = re.compile(
    rf"(?P<start>{DATE_TOKEN})\s*(?:–|—|-|to)\s*(?P<end>{DATE_TOKEN}|Present|Current|Now)",
    re.IGNORECASE,
)


def parse_date_token(token: str, *, end: bool = False) -> tuple[date, str] | None:
    raw = (token or "").strip().rstrip(".")
    if not raw:
        return None
    if raw.lower() in {"present", "current", "now"}:
        today = date.today()
        return today, "month"
    month_match = re.match(rf"({_MONTH})\.?\s+(\d{{4}})", raw, re.IGNORECASE)
    if month_match:
        key = month_match.group(1).lower().replace(".", "")
        month = MONTHS.get(key) or MONTHS.get(key[:3])
        year = int(month_match.group(2))
        if not month or year < 1950 or year > 2100:
            return None
        return date(year, month, 1), "month"
    slash = re.match(r"(\d{1,2})/(\d{4})", raw)
    if slash:
        month = int(slash.group(1))
        year = int(slash.group(2))
        if 1 <= month <= 12 and 1950 <= year <= 2100:
            return date(year, month, 1), "month"
        return None
    year_match = re.match(r"(\d{4})$", raw)
    if year_match:
        year = int(year_match.group(1))
        if not 1950 <= year <= 2100:
            return None
        if end:
            return date(year, 12, 1), "year"
        return date(year, 1, 1), "year"
    return None


def _coerce_date(value, *, end: bool):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text[:10])
    parsed = parse_date_token(text, end=end)
    return parsed[0] if parsed else None


def month_index(value: date) -> int:
    return value.year * 12 + value.month


def merge_months(intervals: list[tuple[int, int]]) -> int:
    """Inclusive month indexes. Overlaps count once."""
    if not intervals:
        return 0
    ordered = sorted(intervals)
    merged: list[list[int]] = []
    for start, end in ordered:
        if end < start:
            continue
        if not merged or start > merged[-1][1] + 1:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start + 1 for start, end in merged)


def experience_months(entries: list[dict], today: date | None = None) -> int | None:
    today = today or date.today()
    intervals: list[tuple[int, int]] = []
    saw_date = False
    for entry in entries:
        start = _coerce_date(entry.get("start_date"), end=False)
        end = _coerce_date(entry.get("end_date"), end=True)
        if start is None:
            continue
        saw_date = True
        if entry.get("is_current") or end is None:
            end = today
        if end < start:
            continue
        intervals.append((month_index(start), month_index(end)))
    if not saw_date:
        return None
    return merge_months(intervals)
