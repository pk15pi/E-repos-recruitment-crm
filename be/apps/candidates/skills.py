import re

from apps.candidates.models import Skill, SkillAlias

DEFAULT_SKILLS: dict[str, list[str]] = {
    "Python": ["python", "py"],
    "Django": ["django"],
    "PostgreSQL": ["postgresql", "postgres", "psql"],
    "Redis": ["redis"],
    "JavaScript": ["javascript", "js", "es6"],
    "TypeScript": ["typescript", "ts"],
    "React": ["react", "reactjs", "react.js"],
    "Node.js": ["node", "nodejs", "node.js"],
    "Amazon Web Services": ["aws", "amazon web services"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Java": ["java"],
    "Go": ["golang", "go"],
    "SQL": ["sql"],
    "MongoDB": ["mongodb", "mongo"],
    "Kafka": ["kafka"],
    "Spark": ["spark", "apache spark"],
    "Airflow": ["airflow"],
    "Tableau": ["tableau"],
    "Figma": ["figma"],
    "Salesforce": ["salesforce", "sfdc"],
    "Excel": ["excel", "ms excel"],
    "Product management": ["product management", "product manager"],
    "Machine learning": ["machine learning", "ml"],
    "Payments": ["payments", "payment"],
}

STOP = {
    "and",
    "or",
    "the",
    "with",
    "for",
    "a",
    "an",
    "of",
    "to",
    "in",
    "on",
    "at",
    "by",
    "from",
    "years",
    "year",
    "experience",
}


def skill_key(value: str) -> str:
    return re.sub(r"[^a-z0-9+#]", "", (value or "").lower())


def ensure_default_skills(organization) -> None:
    if SkillAlias.objects.filter(organization=organization).exists():
        return
    for name, aliases in DEFAULT_SKILLS.items():
        skill, _ = Skill.objects.get_or_create(
            organization=organization,
            normalized_name=skill_key(name),
            defaults={"name": name},
        )
        for alias in aliases:
            SkillAlias.objects.get_or_create(
                organization=organization,
                alias=skill_key(alias),
                defaults={"skill": skill},
            )


def resolve_skill(organization, raw: str) -> Skill | None:
    key = skill_key(raw)
    if not key or key in STOP or len(key) < 2:
        return None
    alias = (
        SkillAlias.objects.filter(organization=organization, alias=key).select_related("skill").first()
    )
    if alias:
        return alias.skill
    existing = Skill.objects.filter(organization=organization, normalized_name=key).first()
    if existing:
        return existing
    # Unknown skills are kept only when the caller extracted them from a skills section.
    display = " ".join(raw.split())[:120]
    if not display:
        return None
    return Skill.objects.create(organization=organization, name=display, normalized_name=key)


def known_skill_names() -> list[str]:
    names: list[str] = []
    for canonical, aliases in DEFAULT_SKILLS.items():
        names.append(canonical)
        names.extend(aliases)
    return names
