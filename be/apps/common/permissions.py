from rest_framework.permissions import BasePermission

from apps.common.roles import AGENCY_ADMIN, AGENCY_ROLES
from apps.common.tenancy import attach_tenant, enforce_org_writable


class TenantMixin:
    """Resolve the organization after DRF authentication."""

    allow_missing_org = False

    def initial(self, request, *args, **kwargs):
        # Authenticate before permission checks so the organization is already bound.
        self.format_kwarg = self.get_format_suffix(**kwargs)
        neg = self.perform_content_negotiation(request)
        request.accepted_renderer, request.accepted_media_type = neg
        version, scheme = self.determine_version(request, *args, **kwargs)
        request.version, request.versioning_scheme = version, scheme
        self.perform_authentication(request)
        attach_tenant(request)
        self.check_permissions(request)
        enforce_org_writable(request)
        self.check_throttles(request)
        if request.user.is_authenticated and not self.allow_missing_org:
            if request.organization is None:
                self.permission_denied(
                    request,
                    message=(
                        "Send X-Organization-Id to choose an organization."
                        if request.user.is_platform_admin
                        else "No active organization membership."
                    ),
                )


class IsAuthenticatedInOrg(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(view, "allow_missing_org", False):
            return True
        return getattr(request, "organization", None) is not None


class AgencyOnly(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated or getattr(request, "organization", None) is None:
            return False
        if user.is_platform_admin:
            return True
        membership = getattr(request, "membership", None)
        return bool(membership and membership.role in AGENCY_ROLES)


class AgencyAdminOnly(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated or getattr(request, "organization", None) is None:
            return False
        if user.is_platform_admin:
            return True
        membership = getattr(request, "membership", None)
        return bool(membership and membership.role == AGENCY_ADMIN)


class PlatformOnly(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_platform_admin)
