from getpass import getpass

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Create or update the Synfowebs platform administrator account."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-weak-password",
            action="store_true",
            help="Allow a password that fails the project's password strength validators.",
        )

    def handle(self, *args, **options):
        email = settings.DJANGO_ADMIN_LOGIN_EMAIL
        user = User.objects.filter(email__iexact=email).first()
        password = getpass("Set platform admin password: ")
        confirmation = getpass("Confirm platform admin password: ")
        if password != confirmation:
            raise CommandError("Passwords did not match.")
        if not password:
            raise CommandError("Password cannot be empty.")

        user = user or User(email=email)
        user.full_name = user.full_name or "Synfowebs Administrator"
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.is_platform_admin = True
        user.set_password(password)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            if not options["allow_weak_password"]:
                raise CommandError(" ".join(exc.messages) + " Use --allow-weak-password only if intended.") from exc
            self.stderr.write(self.style.WARNING("The requested password is weak. Change it after first login."))
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Platform admin {email} is ready. Use '{settings.DJANGO_ADMIN_LOGIN_ALIAS}' as the Django admin user ID."))
