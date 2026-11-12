from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Organization, OrganizationMembership, User
from apps.candidates.models import Candidate
from apps.candidates.services import apply_profile
from apps.candidates.skills import ensure_default_skills
from apps.clients.models import ClientCompany, ClientContact, ClientMembership

PASSWORD = "Harbor-Desk-19"


class Command(BaseCommand):
    help = "Create a local agency, users, two clients, and a handful of candidates. Dev only."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo refuses to run unless DJANGO_DEBUG=true.")
        org, _ = Organization.objects.get_or_create(
            slug="northwind",
            defaults={
                "name": "Northwind Search",
                "privacy_notice": "Northwind Search processes candidate data to consider people for client roles. "
                "Access is limited to the assigned desk and to client users a profile is explicitly shared with.",
                "retention_days": 365,
            },
        )
        ensure_default_skills(org)
        users = {
            "ada@sable.test": ("Ada Menon", "agency_admin", None),
            "ravi@sable.test": ("Ravi Iyer", "recruiter", None),
            "client@sable.test": ("Meera Shah", "client_admin", "Harbour Labs"),
            "otherclient@sable.test": ("Dev Kapoor", "client_admin", "Southwind Logistics"),
        }
        harbour, _ = ClientCompany.objects.get_or_create(
            organization=org,
            name="Harbour Labs",
            defaults={"industry": "Payments", "plan": ClientCompany.Plan.PAID, "plan_reference": "Demo paid account"},
        )
        south, _ = ClientCompany.objects.get_or_create(
            organization=org,
            name="Southwind Logistics",
            defaults={"industry": "Logistics", "plan": ClientCompany.Plan.FREE, "free_access_reason": "Demo free access"},
        )
        ClientContact.objects.get_or_create(
            organization=org, company=harbour, email="meera@harbour.example", defaults={"name": "Meera Shah", "title": "Talent lead", "is_primary": True}
        )
        companies = {"Harbour Labs": harbour, "Southwind Logistics": south}
        for email, (name, role, company_name) in users.items():
            user, created = User.objects.get_or_create(email=email, defaults={"full_name": name})
            if created:
                user.set_password(PASSWORD)
                user.save()
            OrganizationMembership.objects.get_or_create(organization=org, user=user, defaults={"role": role})
            if company_name:
                ClientMembership.objects.get_or_create(
                    organization=org, company=companies[company_name], user=user, defaults={"role": role}
                )
        recruiter = User.objects.get(email="ravi@sable.test")
        samples = [
            {
                "full_name": "Asha Rao",
                "current_title": "Senior Backend Engineer",
                "current_employer": "Northwind Payments",
                "location": "Bengaluru",
                "summary": "Backend engineer focused on payments and distributed systems.",
                "total_experience_months": 128,
                "work_mode": "hybrid",
                "employment_type": "full_time",
                "emails": [{"email": "asha.rao@example.com", "is_primary": True}],
                "skills": [{"name": "Python"}, {"name": "Django"}, {"name": "PostgreSQL"}, {"name": "Redis"}],
                "experiences": [
                    {"title": "Senior Backend Engineer", "employer": "Northwind Payments", "start_date": "2020-01-01", "is_current": True}
                ],
                "source": "seed",
            },
            {
                "full_name": "Lata Menon",
                "current_title": "Java Developer",
                "current_employer": "Orbit Systems",
                "location": "Mumbai",
                "summary": "Java services for logistics.",
                "total_experience_months": 30,
                "employment_type": "full_time",
                "emails": [{"email": "lata.menon@example.com", "is_primary": True}],
                "skills": [{"name": "Java"}],
                "source": "seed",
            },
            {
                "full_name": "Incomplete Profile",
                "summary": "",
                "source": "seed",
            },
        ]
        for sample in samples:
            if Candidate.objects.filter(organization=org, full_name=sample["full_name"]).exists():
                continue
            candidate = Candidate(organization=org, created_by=recruiter, assigned_recruiter=recruiter, status="active")
            apply_profile(candidate, sample, recruiter, mark_verified=True)
        self.stdout.write(self.style.SUCCESS(f"Demo agency ready. Sign in as ravi@sable.test / {PASSWORD}"))
