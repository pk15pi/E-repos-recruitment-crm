import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from apps.common.models import TimestampedModel, UUIDModel
from apps.common.roles import ALL_MEMBERSHIP_ROLES


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_platform_admin", True)
        extra.setdefault("full_name", "Platform admin")
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_platform_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]
    objects = UserManager()

    class Meta:
        indexes = [models.Index(fields=["email"])]

    def __str__(self) -> str:
        return self.email


class Organization(TimestampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Payment past due"
        INACTIVE = "inactive", "Inactive"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    contact_email = models.EmailField(blank=True, default="")
    retention_days = models.PositiveIntegerField(default=365)
    privacy_notice = models.TextField(blank=True)
    allow_client_see_compensation = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    status_reason = models.CharField(max_length=200, blank=True)
    status_changed_at = models.DateTimeField(null=True, blank=True)

    @property
    def read_only(self) -> bool:
        return self.status != self.Status.ACTIVE

    def __str__(self) -> str:
        return self.name


class OrganizationMembership(UUIDModel):
    class Role(models.TextChoices):
        AGENCY_ADMIN = "agency_admin", "Agency admin"
        RECRUITER = "recruiter", "Recruiter"
        CLIENT_ADMIN = "client_admin", "Client admin"
        CLIENT_HIRING_MANAGER = "client_hiring_manager", "Client hiring manager"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=40, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="uniq_org_user_membership"),
            models.CheckConstraint(condition=models.Q(role__in=list(ALL_MEMBERSHIP_ROLES)), name="membership_role_known"),
        ]
        indexes = [models.Index(fields=["user", "is_active"])]


class GlobalDataGrant(UUIDModel):
    class Scope(models.TextChoices):
        RESUMES = "resumes", "Global resumes"
        CLIENTS = "clients", "Global clients"
        CUSTOMERS = "customers", "Global customers"
        JDS = "jds", "Global job descriptions"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="global_grants")
    scope = models.CharField(max_length=20, choices=Scope.choices)
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "scope"], name="uniq_global_grant_scope"),
        ]


class PasswordResetToken(UUIDModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reset_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class EmailOTP(UUIDModel):
    class Purpose(models.TextChoices):
        LOGIN = "login", "Sign-in code"
        PASSWORD_RESET = "password_reset", "Password reset"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_otps")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "purpose", "created_at"])]
        ordering = ["-created_at"]
