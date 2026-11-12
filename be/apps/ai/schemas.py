"""JSON schemas sent to hosted models and used to validate every AI payload."""

_NULL_STR = {"type": ["string", "null"]}

RESUME_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "full_name": _NULL_STR,
        "emails": {"type": "array", "items": {"type": "string"}},
        "phones": {"type": "array", "items": {"type": "string"}},
        "location": _NULL_STR,
        "linkedin_url": _NULL_STR,
        "github_url": _NULL_STR,
        "portfolio_url": _NULL_STR,
        "summary": _NULL_STR,
        "current_title": _NULL_STR,
        "current_employer": _NULL_STR,
        "skills": {"type": "array", "items": {"type": "string"}},
        "experiences": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "employer": _NULL_STR,
                    "title": _NULL_STR,
                    "start": _NULL_STR,
                    "end": _NULL_STR,
                    "is_current": {"type": ["boolean", "null"]},
                    "location": _NULL_STR,
                    "description": _NULL_STR,
                },
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "institution": _NULL_STR,
                    "degree": _NULL_STR,
                    "field_of_study": _NULL_STR,
                    "start": _NULL_STR,
                    "end": _NULL_STR,
                },
            },
        },
        "certifications": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"name": _NULL_STR, "issuer": _NULL_STR, "issued_on": _NULL_STR},
            },
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": _NULL_STR,
                    "description": _NULL_STR,
                    "url": _NULL_STR,
                    "technologies": _NULL_STR,
                },
            },
        },
        "languages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"language": _NULL_STR, "proficiency": _NULL_STR},
            },
        },
        "notice_period_days": {"type": ["integer", "null"]},
        "total_experience_years": {"type": ["number", "null"]},
        "relevant_experience_years": {"type": ["number", "null"]},
    },
}

JD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": _NULL_STR,
        "seniority": _NULL_STR,
        "domain": _NULL_STR,
        "min_experience_years": {"type": ["number", "null"]},
        "max_experience_years": {"type": ["number", "null"]},
        "location": _NULL_STR,
        "work_mode": {"type": ["string", "null"], "enum": ["remote", "hybrid", "onsite", None]},
        "employment_type": {
            "type": ["string", "null"],
            "enum": ["full_time", "part_time", "contract", "internship", "temporary", None],
        },
        "salary_min": {"type": ["number", "null"]},
        "salary_max": {"type": ["number", "null"]},
        "salary_currency": _NULL_STR,
        "salary_period": {"type": ["string", "null"], "enum": ["annual", "monthly", "daily", "hourly", None]},
        "notice_period_days": {"type": ["integer", "null"]},
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "title",
                            "seniority",
                            "skill",
                            "tool",
                            "responsibility",
                            "education",
                            "certification",
                            "domain",
                            "location",
                            "work_mode",
                            "employment_type",
                            "experience",
                            "salary",
                            "notice",
                            "other",
                        ],
                    },
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "priority": {"type": "string", "enum": ["must_have", "preferred", "informational"]},
                },
                "required": ["kind", "label", "value", "priority"],
            },
        },
    },
    "required": ["requirements"],
}

SEARCH_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "boolean_query": {"type": "string"},
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "field": {
                        "type": "string",
                        "enum": [
                            "location",
                            "title",
                            "employer",
                            "skill",
                            "work_mode",
                            "employment_type",
                            "industry",
                            "experience_min_months",
                            "experience_max_months",
                            "notice_max_days",
                        ],
                    },
                    "operator": {"type": "string", "enum": ["eq", "icontains", "gte", "lte"]},
                    "value": {"type": "string"},
                },
                "required": ["field", "operator", "value"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["boolean_query", "filters"],
}

EXPLANATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"explanation": {"type": "string"}},
    "required": ["explanation"],
}

SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}

INTERVIEW_QUESTIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "prompt": {"type": "string"},
                    "focus": {"type": "string"},
                },
                "required": ["prompt", "focus"],
            },
        }
    },
    "required": ["questions"],
}

INTERVIEW_EVALUATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "concerns": {"type": "array", "items": {"type": "string"}},
        "recommendation": {"type": "string", "enum": ["advance", "hold", "reject"]},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": ["summary", "strengths", "concerns", "recommendation", "score"],
}
