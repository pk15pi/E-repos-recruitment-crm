"""Serialize candidates without leaking client-hidden fields."""

from apps.common.global_access import is_foreign, owner_organization
from apps.common.scoping import can_see_compensation, can_see_contact
from apps.common.tenancy import is_client


def _or_blank(value):
    return value if value not in (None, "") else None


def candidate_card(candidate, request, share=None) -> dict:
    contact = can_see_contact(request, candidate, share)
    money = can_see_compensation(request, candidate, share)
    foreign = is_foreign(request, candidate)
    skills = [
        {"name": row.skill.name, "source": row.source, "confidence": row.confidence}
        for row in list(candidate.candidate_skills.all())[:12]
    ]
    emails = list(candidate.emails.all())
    return {
        "id": str(candidate.id),
        "full_name": candidate.full_name or None,
        "current_title": candidate.current_title or None,
        "current_employer": candidate.current_employer or None,
        "location": candidate.location or None,
        "total_experience_months": candidate.total_experience_months,
        "work_mode": candidate.work_mode or None,
        "employment_type": candidate.employment_type or None,
        "status": candidate.status,
        "verification_status": candidate.verification_status,
        "notice_period_days": candidate.notice_period_days,
        "availability_date": candidate.availability_date,
        "expected_salary_amount": candidate.expected_salary_amount if money else None,
        "expected_salary_currency": candidate.expected_salary_currency if money else None,
        "compensation_visible": money,
        "primary_email": emails[0].email if contact and emails else None,
        "skills": skills,
        "tags": [row.tag.name for row in candidate.candidate_tags.all()],
        "updated_at": candidate.updated_at,
        "is_global": foreign,
        "owner_organization": owner_organization(candidate) if foreign else None,
        "assigned_recruiter": None
        if foreign or is_client(request) or not candidate.assigned_recruiter_id
        else {"id": str(candidate.assigned_recruiter_id), "full_name": candidate.assigned_recruiter.full_name},
    }


def candidate_detail(candidate, request, share=None) -> dict:
    card = candidate_card(candidate, request, share)
    contact = can_see_contact(request, candidate, share)
    money = can_see_compensation(request, candidate, share)
    foreign = card["is_global"]
    notes = candidate.notes.all()
    if is_client(request):
        notes = notes.filter(visibility="client")
    card.update(
        {
            "summary": candidate.summary or None,
            "normalized_title": candidate.normalized_title or None,
            "linkedin_url": candidate.linkedin_url or None,
            "github_url": candidate.github_url or None,
            "portfolio_url": candidate.portfolio_url or None,
            "industry": candidate.industry or None,
            "relevant_experience_months": candidate.relevant_experience_months,
            "willing_to_relocate": candidate.willing_to_relocate,
            "source": None if is_client(request) or foreign else (candidate.source or None),
            "emails": [{"email": row.email, "label": row.label, "is_primary": row.is_primary} for row in candidate.emails.all()]
            if contact
            else [],
            "phones": [{"raw": row.raw, "label": row.label, "is_primary": row.is_primary} for row in candidate.phones.all()]
            if contact
            else [],
            "contact_visible": contact,
            "preferred_locations": list(candidate.preferred_locations.values_list("location", flat=True)),
            "current_salary_amount": candidate.current_salary_amount if money else None,
            "current_salary_currency": candidate.current_salary_currency if money else None,
            "current_salary_period": candidate.current_salary_period if money else None,
            "expected_salary_period": candidate.expected_salary_period if money else None,
            "experiences": [
                {
                    "id": str(row.id),
                    "employer": row.employer or None,
                    "title": row.title or None,
                    "start_date": row.start_date,
                    "end_date": row.end_date,
                    "is_current": row.is_current,
                    "location": row.location or None,
                    "description": row.description or None,
                }
                for row in candidate.experiences.all()
            ],
            "education": [
                {
                    "id": str(row.id),
                    "institution": row.institution or None,
                    "degree": row.degree or None,
                    "field_of_study": row.field_of_study or None,
                    "start_date": row.start_date,
                    "end_date": row.end_date,
                }
                for row in candidate.education.all()
            ],
            "certifications": [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "issuer": row.issuer or None,
                    "issued_on": row.issued_on,
                    "expires_on": row.expires_on,
                }
                for row in candidate.certifications.all()
            ],
            "projects": [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "description": row.description or None,
                    "url": row.url or None,
                    "technologies": row.technologies or None,
                }
                for row in candidate.projects.all()
            ],
            "languages": [
                {"id": str(row.id), "language": row.language, "proficiency": row.proficiency or None}
                for row in candidate.languages.all()
            ],
            "skills": [
                {"name": row.skill.name, "source": row.source, "confidence": row.confidence}
                for row in candidate.candidate_skills.select_related("skill")
            ],
            "notes": []
            if foreign
            else [
                {
                    "id": str(row.id),
                    "body": row.body,
                    "visibility": row.visibility,
                    "author": row.author.full_name if row.author_id else None,
                    "created_at": row.created_at,
                }
                for row in notes
            ],
            "consents": []
            if foreign or is_client(request)
            else [
                {
                    "id": str(row.id),
                    "purpose": row.purpose,
                    "lawful_basis": row.lawful_basis,
                    "granted": row.granted,
                    "created_at": row.created_at,
                }
                for row in candidate.consents.all()
            ],
            "deletion_requested_at": None if is_client(request) or foreign else candidate.deletion_requested_at,
        }
    )
    return card
