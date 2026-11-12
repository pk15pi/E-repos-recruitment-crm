from rest_framework.exceptions import NotAuthenticated, PermissionDenied
from rest_framework.permissions import SAFE_METHODS

from apps.accounts.models import Organization, OrganizationMembership
from apps.common.exceptions import OrganizationReadOnly
from apps.common.roles import CLIENT_ROLES

READ_ONLY_EXEMPT_PATHS = frozenset(
    {
        "/api/v1/auth/logout/",
        "/api/v1/auth/change-password/",
    }
)


def attach_tenant(request) -> None:
    request.organization = None
    request.membership = None
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return
    header_org = request.headers.get("X-Organization-Id")
    if user.is_platform_admin:
        if header_org:
            request.organization = Organization.objects.filter(id=header_org).first()
            if request.organization is None:
                raise PermissionDenied("Unknown organization.")
        return
    membership = (
        OrganizationMembership.objects.filter(user=user, is_active=True)
        .select_related("organization")
        .first()
    )
    request.membership = membership
    if membership is None:
        return
    # Agency and client users are scoped to their membership. A supplied header
    # cannot switch tenants.
    request.organization = membership.organization


def is_client(request) -> bool:
    membership = getattr(request, "membership", None)
    return bool(membership and membership.role in CLIENT_ROLES)


def enforce_org_writable(request) -> None:
    organization = getattr(request, "organization", None)
    if organization is None or not organization.read_only:
        return
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_platform_admin:
        return
    if request.method in SAFE_METHODS or request.path in READ_ONLY_EXEMPT_PATHS:
        return
    raise OrganizationReadOnly(
        f"{organization.name} is read-only ({organization.get_status_display().lower()}). "
        "Contact the platform owner to restore write access."
    )


def require_org(request):
    if not request.user.is_authenticated:
        raise NotAuthenticated()
    org = getattr(request, "organization", None)
    if org is None:
        if request.user.is_platform_admin:
            raise PermissionDenied("Send X-Organization-Id to choose an organization.")
        raise PermissionDenied("No active organization membership.")
    return org
