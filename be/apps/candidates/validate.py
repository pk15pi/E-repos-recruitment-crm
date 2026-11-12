from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError

from apps.candidates.models import Candidate

STRINGS = {
    "full_name": 200,
    "summary": 8000,
    "current_title": 200,
    "normalized_title": 200,
    "current_employer": 200,
    "location": 200,
    "linkedin_url": 300,
    "github_url": 300,
    "portfolio_url": 300,
    "industry": 120,
    "current_salary_currency": 3,
    "current_salary_period": 16,
    "expected_salary_currency": 3,
    "expected_salary_period": 16,
    "source": 80,
    "work_mode": 16,
    "employment_type": 16,
    "status": 32,
}
NULLABLE_INTS = ["total_experience_months", "relevant_experience_months", "notice_period_days"]
AMOUNTS = ["current_salary_amount", "expected_salary_amount"]


def clean_profile(data: dict, *, partial: bool = False) -> dict:
    if not isinstance(data, dict):
        raise ValidationError("Profile must be an object.")
    cleaned: dict = {}
    for field, limit in STRINGS.items():
        if field not in data:
            continue
        value = data[field]
        if value is None:
            cleaned[field] = ""
            continue
        if not isinstance(value, str):
            raise ValidationError({field: "Must be text."})
        value = value.strip()
        if len(value) > limit:
            raise ValidationError({field: f"Must be {limit} characters or fewer."})
        cleaned[field] = value
    if "work_mode" in cleaned and cleaned["work_mode"] and cleaned["work_mode"] not in Candidate.WorkMode.values:
        raise ValidationError({"work_mode": "Use remote, hybrid, or onsite."})
    if "employment_type" in cleaned and cleaned["employment_type"] and cleaned["employment_type"] not in Candidate.EmploymentType.values:
        raise ValidationError({"employment_type": "Unknown employment type."})
    if "status" in cleaned and cleaned["status"] and cleaned["status"] not in Candidate.Status.values:
        raise ValidationError({"status": "Unknown status."})
    for field in ("current_salary_period", "expected_salary_period"):
        if cleaned.get(field) and cleaned[field] not in Candidate.SalaryPeriod.values:
            raise ValidationError({field: "Use annual, monthly, daily, or hourly."})
    for field in NULLABLE_INTS:
        if field not in data:
            continue
        value = data[field]
        if value in (None, ""):
            cleaned[field] = None
        else:
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError({field: "Must be a whole number."}) from exc
            if number < 0 or number > 1000:
                raise ValidationError({field: "Value is out of range."})
            cleaned[field] = number
    for field in AMOUNTS:
        if field not in data:
            continue
        value = data[field]
        if value in (None, ""):
            cleaned[field] = None
        else:
            try:
                cleaned[field] = Decimal(str(value))
            except (InvalidOperation, ValueError) as exc:
                raise ValidationError({field: "Must be a number."}) from exc
    if "availability_date" in data:
        cleaned["availability_date"] = data["availability_date"] or None
    if "willing_to_relocate" in data:
        value = data["willing_to_relocate"]
        if value in (None, ""):
            cleaned["willing_to_relocate"] = None
        elif isinstance(value, bool):
            cleaned["willing_to_relocate"] = value
        else:
            raise ValidationError({"willing_to_relocate": "Use true, false, or null."})
    for key in (
        "emails",
        "phones",
        "skills",
        "experiences",
        "education",
        "certifications",
        "projects",
        "languages",
        "preferred_locations",
        "tags",
    ):
        if key in data:
            if not isinstance(data[key], list):
                raise ValidationError({key: "Must be a list."})
            cleaned[key] = data[key]
    if not partial and not cleaned.get("full_name") and "full_name" not in data:
        cleaned.setdefault("full_name", "")
    return cleaned
