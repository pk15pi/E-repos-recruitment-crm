from django.conf import settings
from django.contrib.postgres.search import SearchVector
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import Organization
from apps.candidates.models import Candidate, CandidateEmail, CandidateExperience, CandidateSkill, Skill
from apps.candidates.skills import ensure_default_skills, skill_key

FIRST = ["Asha", "Ravi", "Meera", "Kabir", "Lata", "Dev", "Anika", "Farhan", "Sara", "Nikhil", "Priya", "Arun"]
LAST = ["Rao", "Iyer", "Shah", "Menon", "Kapoor", "Nair", "Das", "Khan", "Joseph", "Reddy", "Bose", "Gill"]
CITIES = ["Bengaluru", "Mumbai", "Delhi", "Hyderabad", "Pune", "Chennai", ""]
TITLES = ["Backend Engineer", "Data Analyst", "Product Manager", "Recruiter", "DevOps Engineer", "Designer"]
SKILLS = ["Python", "Django", "PostgreSQL", "Java", "React", "AWS", "Excel", "Figma"]


class Command(BaseCommand):
    help = "Load synthetic candidates for local search tests. Dev only. Refuses to run when DEBUG is off."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=10000)

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_load is disabled unless DJANGO_DEBUG=true. It creates synthetic personal data.")
        count = options["count"]
        if count < 1 or count > 200000:
            raise CommandError("--count must be between 1 and 200000.")
        org, _ = Organization.objects.get_or_create(slug="northwind", defaults={"name": "Northwind Search"})
        ensure_default_skills(org)
        skill_rows = {}
        for name in SKILLS:
            skill_rows[name], _ = Skill.objects.get_or_create(
                organization=org, normalized_name=skill_key(name), defaults={"name": name}
            )
        now = timezone.now()
        already = Candidate.objects.filter(organization=org, source="load").count()
        if already >= count:
            self.stdout.write(self.style.SUCCESS(f"{already} synthetic candidates already exist in {org.slug}."))
            return
        created = already
        batch = 500
        while created < count:
            size = min(batch, count - created)
            candidates = []
            for index in range(size):
                number = created + index
                first = FIRST[number % len(FIRST)]
                last = LAST[(number // len(FIRST)) % len(LAST)]
                title = TITLES[number % len(TITLES)]
                city = CITIES[number % len(CITIES)]
                months = None if number % 17 == 0 else 12 + (number % 180)
                skill_a = SKILLS[number % len(SKILLS)]
                skill_b = SKILLS[(number + 3) % len(SKILLS)]
                document = f"{first} {last}\n{title}\n{city}\n{skill_a} {skill_b}\nload-{number}@example.test"
                candidates.append(
                    Candidate(
                        organization=org,
                        full_name=f"{first} {last} {number}",
                        current_title=title,
                        current_employer="Sample Employer",
                        location=city,
                        summary="Synthetic profile for local load tests.",
                        total_experience_months=months,
                        source="load",
                        status=Candidate.Status.ACTIVE,
                        search_document=document,
                        created_at=now,
                        updated_at=now,
                    )
                )
            rows = Candidate.objects.bulk_create(candidates, batch_size=batch)
            emails = []
            experiences = []
            links = []
            for row in rows:
                emails.append(
                    CandidateEmail(
                        organization=org,
                        candidate=row,
                        email=f"load-{row.full_name.split()[-1]}@example.test",
                        is_primary=True,
                    )
                )
                experiences.append(
                    CandidateExperience(
                        organization=org,
                        candidate=row,
                        employer="Sample Employer",
                        title=row.current_title,
                        is_current=True,
                    )
                )
                for name in {SKILLS[int(row.full_name.split()[-1]) % len(SKILLS)], SKILLS[(int(row.full_name.split()[-1]) + 3) % len(SKILLS)]}:
                    links.append(
                        CandidateSkill(organization=org, candidate=row, skill=skill_rows[name], source=CandidateSkill.Source.USER)
                    )
            CandidateEmail.objects.bulk_create(emails, batch_size=1000, ignore_conflicts=True)
            CandidateExperience.objects.bulk_create(experiences, batch_size=1000)
            CandidateSkill.objects.bulk_create(links, batch_size=1000, ignore_conflicts=True)
            created += size
            self.stdout.write(f"loaded {created}")
        Candidate.objects.filter(organization=org, source="load").update(search_vector=SearchVector("search_document", config="english"))
        self.stdout.write(self.style.SUCCESS(f"Loaded {count} synthetic candidates into {org.slug}."))
