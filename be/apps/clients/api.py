from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import GlobalDataGrant
from apps.clients.models import ClientCompany, ClientContact, ClientMembership
from apps.common.audit import record_audit
from apps.common.global_access import can_read_global, global_clients, owner_organization
from apps.common.permissions import AgencyAdminOnly, AgencyOnly, IsAuthenticatedInOrg, TenantMixin
from apps.common.scoping import client_company_ids
from apps.common.tenancy import is_client, require_org


class ClientListView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request):
        org = require_org(request)
        qs = ClientCompany.objects.filter(organization=org)
        if is_client(request):
            return Response([_company(row) for row in qs.filter(id__in=client_company_ids(request))])
        rows = [_company(row) for row in qs]
        if can_read_global(request, GlobalDataGrant.Scope.CLIENTS):
            include_contacts = can_read_global(request, GlobalDataGrant.Scope.CUSTOMERS)
            rows.extend(
                _company(row, shared=True, include_contacts=include_contacts)
                for row in global_clients(org).select_related("organization").prefetch_related("contacts")
            )
        return Response(rows)

    def post(self, request):
        if is_client(request):
            raise PermissionDenied()
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "Company name is required."})
        if ClientCompany.objects.filter(organization=request.organization, name=name).exists():
            raise ValidationError({"name": "That company is already on file."})
        company = ClientCompany.objects.create(
            organization=request.organization,
            name=name[:200],
            industry=(request.data.get("industry") or "")[:120],
            website=(request.data.get("website") or "")[:200],
            notes=(request.data.get("notes") or "")[:4000],
        )
        record_audit(request, "client_create", company, company.name)
        return Response(_company(company), status=201)


class ClientDetailView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request, company_id):
        org = require_org(request)
        own = ClientCompany.objects.filter(organization=org, id=company_id).first()
        if own is not None:
            if is_client(request) and own.id not in client_company_ids(request):
                raise Http404()
            return Response(_company(own, detail=True))
        if can_read_global(request, GlobalDataGrant.Scope.CLIENTS):
            shared = global_clients(org).select_related("organization").filter(id=company_id).first()
            if shared is not None:
                include_contacts = can_read_global(request, GlobalDataGrant.Scope.CUSTOMERS)
                return Response(_company(shared, detail=True, shared=True, include_contacts=include_contacts))
        raise Http404()

    def patch(self, request, company_id):
        if is_client(request):
            raise PermissionDenied()
        company = _company_or_404(request, company_id)
        plan_fields = {"plan", "plan_reference", "free_access_reason"}
        if plan_fields & set(request.data):
            if not AgencyAdminOnly().has_permission(request, self):
                raise PermissionDenied("Only an agency admin can change a client's distribution plan.")
            if "plan" in request.data:
                plan = request.data.get("plan")
                if plan not in ClientCompany.Plan.values:
                    raise ValidationError({"plan": "Choose no plan, paid, or free access."})
                if plan != company.plan:
                    record_audit(request, "client_plan_change", company, f"{company.plan} -> {plan}")
                company.plan = plan
                if plan == ClientCompany.Plan.FREE:
                    company.free_access_granted_at = timezone.now()
                    company.free_access_granted_by = request.user
                else:
                    company.free_access_granted_at = None
                    company.free_access_granted_by = None
            if "plan_reference" in request.data:
                company.plan_reference = str(request.data.get("plan_reference") or "")[:120]
            if "free_access_reason" in request.data:
                company.free_access_reason = str(request.data.get("free_access_reason") or "")[:200]
        for field, limit in {"name": 200, "industry": 120, "website": 200, "notes": 4000}.items():
            if field in request.data:
                setattr(company, field, str(request.data.get(field) or "")[:limit])
        company.save()
        return Response(_company(company, detail=True))


class ContactView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def post(self, request, company_id):
        company = _company_or_404(request, company_id)
        if is_client(request) and request.membership.role != "client_admin":
            raise PermissionDenied()
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "Contact name is required."})
        contact = ClientContact.objects.create(
            organization=company.organization,
            company=company,
            name=name[:200],
            email=(request.data.get("email") or "")[:200],
            phone=(request.data.get("phone") or "")[:40],
            title=(request.data.get("title") or "")[:160],
            is_primary=bool(request.data.get("is_primary")),
        )
        return Response(_contact(contact), status=201)

    def delete(self, request, company_id, contact_id):
        if is_client(request):
            raise PermissionDenied()
        company = _company_or_404(request, company_id)
        contact = get_object_or_404(ClientContact, company=company, id=contact_id)
        contact.delete()
        return Response(status=204)


def _company_or_404(request, company_id):
    qs = ClientCompany.objects.filter(organization=require_org(request), id=company_id)
    if is_client(request):
        qs = qs.filter(id__in=client_company_ids(request))
    return get_object_or_404(qs)


def _company(row: ClientCompany, detail=False, shared=False, include_contacts=True) -> dict:
    payload = {
        "id": str(row.id),
        "name": row.name,
        "industry": row.industry or None,
        "website": row.website or None,
        "notes": None if shared else (row.notes or None),
        "plan": None if shared else row.plan,
        "plan_reference": None if shared else (row.plan_reference or None),
        "free_access_reason": None if shared else (row.free_access_reason or None),
        "free_access_granted_at": None if shared else row.free_access_granted_at,
        "distribution_enabled": False if shared else row.distribution_enabled,
        "is_global": shared,
        "owner_organization": owner_organization(row) if shared else None,
    }
    if detail and shared:
        payload["contacts"] = [_contact(item) for item in row.contacts.all()] if include_contacts else []
        payload["members"] = []
    elif detail:
        payload["contacts"] = [_contact(item) for item in row.contacts.all()]
        payload["members"] = [
            {"user_id": str(item.user_id), "email": item.user.email, "role": item.role}
            for item in ClientMembership.objects.filter(company=row).select_related("user")
        ]
    return payload


def _contact(row: ClientContact) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "email": row.email or None,
        "phone": row.phone or None,
        "title": row.title or None,
        "is_primary": row.is_primary,
    }
