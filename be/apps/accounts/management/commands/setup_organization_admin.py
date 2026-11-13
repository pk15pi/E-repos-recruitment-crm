from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Organization, OrganizationMembership, User


class Command(BaseCommand):
    help = "Create or update an organization and its agency administrator."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--slug", required=True)
        parser.add_argument("--admin-email", required=True)
        parser.add_argument("--admin-name", default="Organization Administrator")
        parser.add_argument("--allow-weak-password", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        email = options["admin_email"].strip().lower()
        password = getpass("Set organization admin password: ")
        confirmation = getpass("Confirm organization admin password: ")
        if password != confirmation:
            raise CommandError("Passwords did not match.")
        if not password:
            raise CommandError("Password cannot be empty.")

        organization, _ = Organization.objects.get_or_create(
            slug=options["slug"], defaults={"name": options["name"]}
        )
        user, _ = User.objects.get_or_create(email=email, defaults={"full_name": options["admin_name"]})
        user.full_name = options["admin_name"]
        user.is_active = True
        user.set_password(password)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            if not options["allow_weak_password"]:
                raise CommandError(" ".join(exc.messages) + " Use --allow-weak-password only if intended.") from exc
            self.stderr.write(self.style.WARNING("The requested password is weak. Change it after first login."))
        user.save()

        membership, created = OrganizationMembership.objects.get_or_create(
            organization=organization,
            user=user,
            defaults={"role": OrganizationMembership.Role.AGENCY_ADMIN},
        )
        if not created and membership.role != OrganizationMembership.Role.AGENCY_ADMIN:
            membership.role = OrganizationMembership.Role.AGENCY_ADMIN
            membership.is_active = True
            membership.save(update_fields=["role", "is_active"])
        self.stdout.write(
            self.style.SUCCESS(f"Organization {organization.name} and admin {email} are ready.")
        )
