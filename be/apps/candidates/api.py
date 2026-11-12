import csv
from io import StringIO

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from pgvector.django import CosineDistance
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.ai.provider import ProviderError
from apps.ai.service import execute
from apps.audit.models import AuditEvent
from apps.candidates.models import Candidate, ConsentRecord, RecruiterNote, Task
from apps.candidates.present import candidate_card, candidate_detail
from apps.candidates.services import apply_profile, find_duplicates, merge_candidates, profile_from_candidate, purge_candidate, reindex_candidate
from apps.candidates.validate import clean_profile
from apps.common.audit import record_audit
from apps.common.exceptions import Conflict
from apps.common.global_access import candidates_visible_to, is_foreign
from apps.common.permissions import AgencyAdminOnly, AgencyOnly, IsAuthenticatedInOrg, TenantMixin
from apps.common.scoping import active_shares, candidate_queryset
from apps.common.tenancy import is_client, require_org
from apps.search.services import apply_filters


class CandidateViewSet(TenantMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticatedInOrg]

    def get_queryset(self):
        return self._refine(candidate_queryset(self.request))

    def read_queryset(self):
        return self._refine(candidates_visible_to(self.request))

    def _refine(self, qs):
        qs = qs.select_related("organization", "assigned_recruiter").prefetch_related(
            "emails",
            "phones",
            "candidate_skills__skill",
            "candidate_tags__tag",
            "experiences",
            "education",
            "certifications",
            "projects",
            "languages",
            "preferred_locations",
            "notes",
            "consents",
        )
        filters = {
            "location": self.request.query_params.get("location", ""),
            "title": self.request.query_params.get("title", ""),
            "skill": self.request.query_params.get("skill", ""),
            "work_mode": self.request.query_params.get("work_mode", ""),
            "employment_type": self.request.query_params.get("employment_type", ""),
            "status": self.request.query_params.get("status", ""),
            "verification_status": self.request.query_params.get("verification_status", ""),
            "experience_min_months": self.request.query_params.get("experience_min_months") or None,
            "experience_max_months": self.request.query_params.get("experience_max_months") or None,
            "tag": self.request.query_params.get("tag", ""),
        }
        hide_unknown = self.request.query_params.get("hide_unknown") in {"1", "true"}
        qs = apply_filters(qs, filters, hide_unknown=hide_unknown)
        query = (self.request.query_params.get("q") or "").strip()
        if query:
            from django.contrib.postgres.search import SearchQuery, SearchRank
            from django.db.models import F

            if len(query) > 500:
                raise ValidationError({"q": "Search text is too long."})
            search = SearchQuery(query, search_type="websearch", config="english")
            qs = qs.filter(Q(search_vector=search) | Q(full_name__icontains=query) | Q(current_title__icontains=query)).annotate(
                rank=SearchRank(F("search_vector"), search)
            )
        ordering = self.request.query_params.get("ordering") or "-updated_at"
        allowed = {
            "updated_at",
            "-updated_at",
            "full_name",
            "-full_name",
            "total_experience_months",
            "-total_experience_months",
            "rank",
            "-rank",
        }
        if ordering not in allowed:
            raise ValidationError({"ordering": "That sort field is not available."})
        if ordering in {"total_experience_months", "-total_experience_months"}:
            from django.db.models import F

            desc = ordering.startswith("-")
            qs = qs.order_by(F("total_experience_months").desc(nulls_last=True) if desc else F("total_experience_months").asc(nulls_last=True))
        else:
            qs = qs.order_by(ordering)
        return qs

    def list(self, request):
        qs = self.read_queryset()
        page = self.paginate_queryset(qs)
        shares = active_shares(request, [row.id for row in page])
        return self.get_paginated_response([candidate_card(row, request, shares.get(row.id)) for row in page])

    def create(self, request):
        if is_client(request):
            raise PermissionDenied("Clients cannot create candidates.")
        org = require_org(request)
        profile = clean_profile(request.data, partial=False)
        candidate = Candidate(organization=org, created_by=request.user, status=profile.get("status") or Candidate.Status.ACTIVE)
        if request.data.get("assigned_recruiter_id"):
            candidate.assigned_recruiter_id = request.data["assigned_recruiter_id"]
        apply_profile(candidate, profile, request.user, mark_verified=True)
        record_audit(request, "candidate_create", candidate, "Created from the desk")
        return Response(candidate_detail(self.get_queryset().get(pk=candidate.pk), request), status=201)

    def retrieve(self, request, pk=None):
        candidate = get_object_or_404(self.read_queryset(), pk=pk)
        return Response(candidate_detail(candidate, request, active_shares(request, [candidate.id]).get(candidate.id)))

    def partial_update(self, request, pk=None):
        if is_client(request):
            raise PermissionDenied("Clients cannot edit candidates.")
        candidate = get_object_or_404(self.get_queryset(), pk=pk)
        profile = clean_profile(request.data, partial=True)
        apply_profile(candidate, profile, request.user, mark_verified=True)
        record_audit(request, "candidate_update", candidate, "Profile edited")
        return Response(candidate_detail(self.get_queryset().get(pk=candidate.pk), request))

    def destroy(self, request, pk=None):
        if not AgencyAdminOnly().has_permission(request, self):
            raise PermissionDenied("Only an agency admin can delete a candidate.")
        candidate = get_object_or_404(self.get_queryset(), pk=pk)
        purge_candidate(candidate, request)
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        if is_client(request):
            raise PermissionDenied()
        candidate = get_object_or_404(candidate_queryset(request, include_archived=True), pk=pk)
        candidate.status = Candidate.Status.ARCHIVED
        candidate.archived_at = timezone.now()
        candidate.save(update_fields=["status", "archived_at", "updated_at"])
        record_audit(request, "candidate_archive", candidate, "Archived")
        return Response({"status": "archived"})

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        candidate = get_object_or_404(self.read_queryset(), pk=pk)
        events = AuditEvent.objects.filter(organization=request.organization, object_id=str(candidate.id)).select_related("actor")[:100]
        return Response(
            [
                {
                    "id": str(row.id),
                    "action": row.action,
                    "detail": row.detail,
                    "actor": row.actor.email if row.actor_id else None,
                    "created_at": row.created_at,
                }
                for row in events
            ]
        )

    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        if is_client(request):
            raise PermissionDenied()
        target = get_object_or_404(self.get_queryset(), pk=pk)
        source = get_object_or_404(self.get_queryset(), pk=request.data.get("source_id"))
        if not request.data.get("acknowledge"):
            raise Conflict("Confirm the merge. Name matches are never merged automatically.")
        merge_candidates(target, source, request.user, request)
        return Response(candidate_detail(self.get_queryset().get(pk=target.pk), request))

    @action(detail=True, methods=["get", "post"])
    def notes(self, request, pk=None):
        qs = self.read_queryset() if request.method == "GET" else self.get_queryset()
        candidate = get_object_or_404(qs, pk=pk)
        if request.method == "GET":
            if is_foreign(request, candidate):
                return Response([])
            rows = candidate.notes.all()
            if is_client(request):
                rows = rows.filter(visibility=RecruiterNote.Visibility.CLIENT)
            return Response(
                [
                    {
                        "id": str(row.id),
                        "body": row.body,
                        "visibility": row.visibility,
                        "created_at": row.created_at,
                        "author": row.author.full_name if row.author_id else None,
                    }
                    for row in rows
                ]
            )
        if is_client(request):
            raise PermissionDenied("Clients leave interview feedback, not recruiter notes.")
        body = (request.data.get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "Write a note before saving."})
        visibility = request.data.get("visibility") or RecruiterNote.Visibility.PRIVATE
        if visibility not in RecruiterNote.Visibility.values:
            raise ValidationError({"visibility": "Use private or client."})
        note = RecruiterNote.objects.create(
            organization=request.organization,
            candidate=candidate,
            author=request.user,
            body=body,
            visibility=visibility,
        )
        record_audit(request, "note_create", candidate, visibility)
        return Response({"id": str(note.id)}, status=201)

    @action(detail=True, methods=["get", "post"])
    def consents(self, request, pk=None):
        if is_client(request):
            raise PermissionDenied()
        qs = self.read_queryset() if request.method == "GET" else self.get_queryset()
        candidate = get_object_or_404(qs, pk=pk)
        if request.method == "GET":
            if is_foreign(request, candidate):
                return Response([])
            return Response(
                [
                    {
                        "id": str(row.id),
                        "purpose": row.purpose,
                        "lawful_basis": row.lawful_basis,
                        "granted": row.granted,
                        "source": row.source,
                        "created_at": row.created_at,
                    }
                    for row in candidate.consents.all()
                ]
            )
        purpose = (request.data.get("purpose") or "").strip()
        if not purpose:
            raise ValidationError({"purpose": "Purpose is required."})
        row = ConsentRecord.objects.create(
            organization=request.organization,
            candidate=candidate,
            purpose=purpose[:200],
            lawful_basis=(request.data.get("lawful_basis") or "consent")[:80],
            granted=bool(request.data.get("granted", True)),
            source=(request.data.get("source") or "recruiter")[:80],
            notes=(request.data.get("notes") or "")[:2000],
            recorded_by=request.user,
        )
        record_audit(request, "consent_record", candidate, purpose[:80])
        return Response({"id": str(row.id), "granted": row.granted}, status=201)

    @action(detail=True, methods=["get"], url_path="resumes")
    def resumes(self, request, pk=None):
        candidate = get_object_or_404(self.read_queryset(), pk=pk)
        from apps.common.scoping import can_download_resume

        if is_client(request) and not can_download_resume(request, candidate):
            return Response([])
        return Response(
            [
                {
                    "id": str(row.id),
                    "filename": row.original_filename,
                    "status": row.status,
                    "created_at": row.created_at,
                }
                for row in candidate.resumes.all()
            ]
        )

    @action(detail=False, methods=["get"])
    def compare(self, request):
        raw_ids = request.query_params.getlist("id") or (request.query_params.get("ids") or "").split(",")
        ids = [item for item in raw_ids if item]
        if not 2 <= len(ids) <= 3:
            raise ValidationError("Compare two or three candidates.")
        rows = list(self.read_queryset().filter(id__in=ids))
        if len(rows) != len(set(ids)):
            return Response({"error": {"code": "not_found", "message": "One or more candidates are not available.", "details": {}}}, status=404)
        order = {value: index for index, value in enumerate(ids)}
        rows.sort(key=lambda row: order.get(str(row.id), 0))
        shares = active_shares(request, [row.id for row in rows])
        return Response([candidate_detail(row, request, shares.get(row.id)) for row in rows])

    @action(detail=False, methods=["get"])
    def export(self, request):
        if is_client(request):
            raise PermissionDenied("Clients cannot export the candidate file.")
        qs = self.read_queryset()[:1000]
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "full_name", "title", "employer", "location", "experience_months", "status", "verification"])
        for row in qs:
            writer.writerow(
                [
                    row.id,
                    row.full_name,
                    row.current_title,
                    row.current_employer,
                    row.location,
                    row.total_experience_months if row.total_experience_months is not None else "",
                    row.status,
                    row.verification_status,
                ]
            )
        record_audit(request, "export", request.organization, "Candidate export")
        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="candidates.csv"'
        return response

    @action(detail=True, methods=["get"])
    def similar(self, request, pk=None):
        candidate = get_object_or_404(self.read_queryset(), pk=pk)
        qs = self.read_queryset().exclude(pk=candidate.pk)
        if candidate.embedding is not None:
            rows = list(qs.exclude(embedding__isnull=True).order_by(CosineDistance("embedding", candidate.embedding))[:8])
        else:
            skill_ids = list(candidate.candidate_skills.values_list("skill_id", flat=True))
            rows = list(qs.filter(candidate_skills__skill_id__in=skill_ids).distinct()[:8]) if skill_ids else []
        shares = active_shares(request, [row.id for row in rows])
        return Response([candidate_card(row, request, shares.get(row.id)) for row in rows])

    @action(detail=True, methods=["post"], url_path="summary")
    def summary(self, request, pk=None):
        if is_client(request):
            raise PermissionDenied()
        candidate = get_object_or_404(self.get_queryset(), pk=pk)
        profile = profile_from_candidate(candidate)
        try:
            result = execute(request.organization, "generate_candidate_summary", "generate_candidate_summary", profile)
        except ProviderError as exc:
            return Response({"error": {"code": exc.code, "message": str(exc), "details": {}}}, status=503)
        return Response(
            {
                "summary": result.data.get("summary"),
                "provider": result.provider,
                "provider_label": result.label,
                "saved": False,
            }
        )

    @action(detail=True, methods=["post"], url_path="deletion-request")
    def deletion_request(self, request, pk=None):
        if not AgencyAdminOnly().has_permission(request, self):
            raise PermissionDenied("Only an agency admin can request deletion.")
        candidate = get_object_or_404(self.get_queryset(), pk=pk)
        candidate.deletion_requested_at = timezone.now()
        candidate.save(update_fields=["deletion_requested_at", "updated_at"])
        record_audit(request, "deletion_request", candidate, "Deletion requested")
        return Response({"deletion_requested_at": candidate.deletion_requested_at})

    @action(detail=False, methods=["post"], url_path="duplicates")
    def duplicates(self, request):
        if is_client(request):
            raise PermissionDenied()
        profile = clean_profile(request.data, partial=True)
        return Response(find_duplicates(require_org(request), profile))


class TaskViewSet(TenantMixin, viewsets.GenericViewSet):
    permission_classes = [AgencyOnly]

    def list(self, request):
        qs = Task.objects.filter(organization=require_org(request)).select_related("candidate", "assigned_to")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        if request.query_params.get("mine") == "1":
            qs = qs.filter(assigned_to=request.user)
        page = self.paginate_queryset(qs.order_by("due_at", "-created_at"))
        return self.get_paginated_response([_task(row) for row in page])

    def create(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            raise ValidationError({"title": "Title is required."})
        candidate = None
        if request.data.get("candidate_id"):
            candidate = get_object_or_404(candidate_queryset(request), pk=request.data["candidate_id"])
        task = Task.objects.create(
            organization=request.organization,
            candidate=candidate,
            assigned_to_id=request.data.get("assigned_to") or request.user.id,
            created_by=request.user,
            title=title[:200],
            notes=(request.data.get("notes") or "")[:4000],
            due_at=request.data.get("due_at") or None,
        )
        return Response(_task(task), status=201)

    def partial_update(self, request, pk=None):
        task = get_object_or_404(Task, organization=require_org(request), pk=pk)
        if "title" in request.data:
            task.title = str(request.data["title"]).strip()[:200]
        if "notes" in request.data:
            task.notes = str(request.data["notes"])[:4000]
        if "status" in request.data:
            if request.data["status"] not in Task.Status.values:
                raise ValidationError({"status": "Unknown status."})
            task.status = request.data["status"]
        if "due_at" in request.data:
            task.due_at = request.data["due_at"] or None
        task.save()
        return Response(_task(task))

    def destroy(self, request, pk=None):
        task = get_object_or_404(Task, organization=require_org(request), pk=pk)
        task.delete()
        return Response(status=204)


def _task(row: Task) -> dict:
    return {
        "id": str(row.id),
        "title": row.title,
        "notes": row.notes,
        "status": row.status,
        "due_at": row.due_at,
        "candidate_id": str(row.candidate_id) if row.candidate_id else None,
        "candidate_name": row.candidate.full_name if row.candidate_id else None,
        "assigned_to": str(row.assigned_to_id) if row.assigned_to_id else None,
        "created_at": row.created_at,
    }
