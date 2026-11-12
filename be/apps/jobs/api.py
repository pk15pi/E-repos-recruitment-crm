import hashlib

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import GlobalDataGrant, OrganizationMembership
from apps.candidates.present import candidate_card
from apps.clients.models import ClientCompany
from apps.common.audit import record_audit
from apps.common.global_access import can_read_global, global_jobs, is_foreign, owner_organization
from apps.common.permissions import AgencyOnly, IsAuthenticatedInOrg, TenantMixin
from apps.common.roles import AGENCY_ROLES
from apps.common.scoping import active_shares, candidate_queryset
from apps.common.tenancy import is_client, require_org
from apps.jobs.models import Job, JobRequirement, MatchResult
from apps.processing.models import ProcessingJob
from apps.processing.services import enqueue

PRIORITIES = set(JobRequirement.Priority.values)
KINDS = set(JobRequirement.Kind.values)


class JobListView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request):
        qs = _visible_jobs(request)
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        client_id = request.query_params.get("client_id")
        if client_id:
            qs = qs.filter(client_company_id=client_id)
        page = _page(qs.order_by("-updated_at"), request)
        return page

    def post(self, request):
        if is_client(request):
            raise PermissionDenied("Clients cannot open requisitions.")
        org = require_org(request)
        job = Job(organization=org, created_by=request.user, assigned_recruiter=request.user, status=Job.Status.OPEN)
        _apply_job_fields(job, request.data, creating=True)
        job.save()
        record_audit(request, "job_create", job, job.title)
        return Response(_job_payload(job), status=201)


class JobDetailView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request, job_id):
        job = get_object_or_404(_visible_jobs(request), pk=job_id)
        return Response(_job_payload(job, include_requirements=True, request=request))

    def patch(self, request, job_id):
        if is_client(request):
            raise PermissionDenied()
        job = get_object_or_404(_jobs(request), pk=job_id)
        _apply_job_fields(job, request.data, creating=False)
        job.save()
        record_audit(request, "job_update", job, job.title)
        return Response(_job_payload(job, include_requirements=True))


class AnalyzeJobView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request):
        description = request.data.get("description") or ""
        if not isinstance(description, str) or not description.strip():
            raise ValidationError({"description": "Paste a job description."})
        if len(description) > settings.MAX_JD_CHARS:
            raise ValidationError(
                {"description": f"Job descriptions must be {settings.MAX_JD_CHARS} characters or fewer."}
            )
        org = require_org(request)
        job = Job(
            organization=org,
            created_by=request.user,
            assigned_recruiter=request.user,
            original_description=description,
            analysis_status=Job.AnalysisStatus.PENDING,
            status=Job.Status.DRAFT,
        )
        _apply_job_fields(job, request.data.get("overrides") or {}, creating=True)
        job.original_description = description
        job.save()
        digest = hashlib.sha256(description.encode()).hexdigest()[:12]
        from apps.jobs.tasks import analyze_job_task

        processing = enqueue(
            analyze_job_task,
            organization=org,
            kind=ProcessingJob.Kind.JD_ANALYZE,
            target_type="job",
            target_id=str(job.id),
            idempotency_key=f"job:{job.id}:analyze:{digest}",
            provider=settings.AI_PROVIDER,
        )
        job.refresh_from_db()
        record_audit(request, "jd_analyze", job, "Job description stored")
        payload = _job_payload(job, include_requirements=True)
        payload["processing"] = {"id": str(processing.id), "status": processing.status, "last_error": processing.last_error}
        return Response(payload, status=201)


class RequirementView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def put(self, request, job_id):
        job = get_object_or_404(_jobs(request), pk=job_id)
        rows = request.data.get("requirements")
        if not isinstance(rows, list):
            raise ValidationError({"requirements": "Provide a list of requirements."})
        job.requirements.all().delete()
        for index, item in enumerate(rows):
            if not isinstance(item, dict):
                raise ValidationError({"requirements": "Each requirement must be an object."})
            kind = item.get("kind") or "other"
            priority = item.get("priority") or "preferred"
            if kind not in KINDS or priority not in PRIORITIES:
                raise ValidationError({"requirements": f"Unknown kind or priority at position {index + 1}."})
            value = str(item.get("value") or "")[:500]
            label = str(item.get("label") or value or kind)[:200]
            JobRequirement.objects.create(
                organization=job.organization,
                job=job,
                kind=kind,
                label=label,
                value=value,
                priority=priority,
                source="user",
                sort_order=index,
            )
            _sync_scalar_from_requirement(job, kind, value, priority)
        job.analysis_status = Job.AnalysisStatus.READY
        job.save()
        record_audit(request, "requirements_update", job, f"{len(rows)} requirements")
        return Response(_job_payload(job, include_requirements=True))


class MatchView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request, job_id):
        job = get_object_or_404(_jobs(request), pk=job_id)
        if job.analysis_status != Job.AnalysisStatus.READY and not job.requirements.exists():
            raise ValidationError("Review the requirements before matching.")
        from apps.jobs.tasks import match_job_task

        existing = ProcessingJob.objects.filter(idempotency_key=f"job:{job.id}:match").first()
        if existing and existing.status == ProcessingJob.Status.RUNNING:
            processing = existing
        elif existing:
            existing.status = ProcessingJob.Status.QUEUED
            existing.attempts = 0
            existing.last_error = ""
            existing.finished_at = None
            existing.save(update_fields=["status", "attempts", "last_error", "finished_at", "updated_at"])
            if settings.CELERY_TASK_ALWAYS_EAGER:
                match_job_task.apply(args=[str(existing.id)])
                existing.refresh_from_db()
            else:
                from django.db import transaction

                transaction.on_commit(lambda: match_job_task.delay(str(existing.id)))
            processing = existing
        else:
            processing = enqueue(
                match_job_task,
                organization=job.organization,
                kind=ProcessingJob.Kind.MATCH,
                target_type="job",
                target_id=str(job.id),
                idempotency_key=f"job:{job.id}:match",
                provider=settings.AI_PROVIDER,
            )
        return Response(
            {
                "processing": {"id": str(processing.id), "status": processing.status, "last_error": processing.last_error},
                "score_version": job.score_version or "sable-score-v1",
                "disclaimer": "Scores are decision support for a recruiter. They are not probabilities and they are not hiring decisions.",
            }
        )


class MatchListView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def get(self, request, job_id):
        job = get_object_or_404(_jobs(request), pk=job_id)
        qs = (
            MatchResult.objects.filter(job=job, organization=job.organization)
            .select_related("candidate", "candidate__assigned_recruiter")
            .prefetch_related(
                "evidence",
                "candidate__emails",
                "candidate__candidate_skills__skill",
                "candidate__candidate_tags__tag",
                "candidate__experiences",
            )
            .order_by("-score")
        )
        ordering = request.query_params.get("ordering") or "-score"
        if ordering == "updated_at":
            qs = qs.order_by("-candidate__updated_at")
        elif ordering == "experience":
            qs = qs.order_by("-candidate__total_experience_months")
        elif ordering not in {"-score", "score"}:
            raise ValidationError({"ordering": "Sort by score, updated_at, or experience."})
        paginator_page = _paginate(qs, request)
        shares = active_shares(request, [row.candidate_id for row in paginator_page["rows"]])
        results = []
        for row in paginator_page["rows"]:
            card = candidate_card(row.candidate, request, shares.get(row.candidate_id))
            card.update(
                {
                    "match_id": str(row.id),
                    "score": row.score,
                    "score_version": row.score_version,
                    "mandatory_met": row.mandatory_met,
                    "mandatory_unknown": row.mandatory_unknown,
                    "mandatory_unmet": row.mandatory_unmet,
                    "preferred_matched": row.preferred_matched,
                    "preferred_total": row.preferred_total,
                    "explanation": row.explanation,
                    "evidence": [
                        {"kind": item.kind, "status": item.status, "detail": item.detail, "quote": item.quote}
                        for item in row.evidence.all()
                    ],
                    "employers": [item.employer for item in row.candidate.experiences.all() if item.employer][:4],
                }
            )
            results.append(card)
        return Response(
            {
                "count": paginator_page["count"],
                "next": paginator_page["next"],
                "previous": paginator_page["previous"],
                "results": results,
                "score_version": job.score_version,
                "disclaimer": "Scores are decision support for a recruiter. They are not probabilities and they are not hiring decisions.",
            }
        )


def _jobs(request):
    org = require_org(request)
    qs = Job.objects.filter(organization=org).select_related(
        "organization", "client_company", "created_by", "assigned_recruiter"
    )
    if is_client(request):
        from apps.common.scoping import client_company_ids

        qs = qs.filter(client_company_id__in=client_company_ids(request))
    return qs


def _visible_jobs(request):
    org = require_org(request)
    qs = _jobs(request)
    if can_read_global(request, GlobalDataGrant.Scope.JDS):
        qs = (qs | global_jobs(org).select_related("organization")).distinct()
    return qs


def _apply_job_fields(job: Job, data: dict, creating: bool) -> None:
    if not isinstance(data, dict):
        raise ValidationError("Job fields must be an object.")
    if "title" in data:
        job.title = str(data.get("title") or "")[:200]
    if creating and not job.title and not data.get("title"):
        job.title = ""
    if "interview_levels" in data and data.get("interview_levels") not in (None, ""):
        try:
            levels = int(data["interview_levels"])
        except (TypeError, ValueError):
            raise ValidationError({"interview_levels": "Choose how many interview levels the role needs."})
        if levels < 0 or levels > 5:
            raise ValidationError({"interview_levels": "Interview levels must be between 0 and 5."})
        job.interview_levels = levels
    if "interview_question_count" in data and data.get("interview_question_count") not in (None, ""):
        try:
            count = int(data["interview_question_count"])
        except (TypeError, ValueError):
            raise ValidationError({"interview_question_count": "Choose how many AI interview questions to ask."})
        if count < 1 or count > 20:
            raise ValidationError({"interview_question_count": "AI interview questions must be between 1 and 20."})
        job.interview_question_count = count
    if "assigned_recruiter_id" in data:
        user_id = data.get("assigned_recruiter_id") or None
        if user_id is None:
            job.assigned_recruiter = None
        else:
            membership = (
                OrganizationMembership.objects.filter(
                    organization=job.organization_id or job.organization.id,
                    user_id=user_id,
                    is_active=True,
                    role__in=AGENCY_ROLES,
                )
                .select_related("user")
                .first()
            )
            if membership is None:
                raise ValidationError({"assigned_recruiter_id": "Choose someone on this desk."})
            job.assigned_recruiter = membership.user
    if "client_company_id" in data and data.get("client_company_id"):
        company = ClientCompany.objects.filter(organization=job.organization_id or job.organization.id, id=data["client_company_id"]).first()
        if company is None:
            raise ValidationError({"client_company_id": "Unknown client."})
        job.client_company = company
    for field, limit in {
        "location": 200,
        "work_mode": 16,
        "employment_type": 16,
        "seniority": 80,
        "domain": 120,
        "salary_currency": 3,
        "salary_period": 16,
        "status": 16,
    }.items():
        if field in data and data[field] is not None:
            setattr(job, field, str(data[field])[:limit])
    for field in ("min_experience_months", "max_experience_months", "notice_period_days"):
        if field in data:
            value = data[field]
            job.__dict__[field] = None if value in (None, "") else int(value)
    for field in ("salary_min", "salary_max"):
        if field in data:
            value = data[field]
            setattr(job, field, None if value in (None, "") else value)
    if "original_description" in data and data["original_description"] is not None:
        text = str(data["original_description"])
        if len(text) > settings.MAX_JD_CHARS:
            raise ValidationError({"original_description": f"Must be {settings.MAX_JD_CHARS} characters or fewer."})
        job.original_description = text


def _sync_scalar_from_requirement(job, kind, value, priority):
    if priority != "must_have":
        return
    if kind == "location":
        job.location = value[:200]
    elif kind == "work_mode":
        job.work_mode = value
    elif kind == "employment_type":
        job.employment_type = value
    elif kind == "title" and not job.title:
        job.title = value[:200]
    elif kind == "experience":
        from apps.jobs.matching import _experience_bounds

        requirement = JobRequirement(kind=kind, value=value, priority=priority, label=value)
        minimum, maximum = _experience_bounds(requirement)
        job.min_experience_months = minimum
        job.max_experience_months = maximum


def _job_payload(job: Job, include_requirements=False, request=None) -> dict:
    shared = request is not None and is_foreign(request, job)
    payload = {
        "id": str(job.id),
        "title": job.title or None,
        "original_description": job.original_description,
        "location": job.location or None,
        "work_mode": job.work_mode or None,
        "employment_type": job.employment_type or None,
        "seniority": job.seniority or None,
        "domain": job.domain or None,
        "min_experience_months": job.min_experience_months,
        "max_experience_months": job.max_experience_months,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency or None,
        "salary_period": job.salary_period or None,
        "notice_period_days": job.notice_period_days,
        "interview_levels": job.interview_levels,
        "interview_question_count": job.interview_question_count,
        "status": job.status,
        "analysis_status": job.analysis_status,
        "analysis_error": job.analysis_error,
        "client_company": None
        if not job.client_company_id
        else {
            "id": str(job.client_company_id),
            "name": job.client_company.name,
            "plan": job.client_company.plan,
            "distribution_enabled": job.client_company.distribution_enabled,
        },
        "created_by": None
        if not job.created_by_id
        else {"id": str(job.created_by_id), "full_name": job.created_by.full_name, "email": job.created_by.email},
        "assigned_recruiter": None
        if not job.assigned_recruiter_id
        else {
            "id": str(job.assigned_recruiter_id),
            "full_name": job.assigned_recruiter.full_name,
            "email": job.assigned_recruiter.email,
        },
        "provider": job.provider,
        "model": job.model,
        "prompt_version": job.prompt_version,
        "schema_version": job.schema_version,
        "score_version": job.score_version,
        "updated_at": job.updated_at,
        "is_global": shared,
        "owner_organization": owner_organization(job) if shared else None,
    }
    if shared:
        payload.update(
            {
                "client_company": None,
                "created_by": None,
                "assigned_recruiter": None,
                "provider": None,
                "model": None,
                "prompt_version": None,
                "schema_version": None,
                "score_version": None,
                "analysis_error": "",
            }
        )
    if include_requirements:
        payload["requirements"] = [
            {
                "id": str(row.id),
                "kind": row.kind,
                "label": row.label,
                "value": row.value,
                "priority": row.priority,
                "source": row.source,
            }
            for row in job.requirements.all()
        ]
    return payload


def _page(qs, request):
    data = _paginate(qs, request)
    return Response(
        {
            "count": data["count"],
            "next": data["next"],
            "previous": data["previous"],
            "results": [_job_payload(row, request=request) for row in data["rows"]],
        }
    )


def _paginate(qs, request):
    from apps.common.pagination import StandardPagination

    paginator = StandardPagination()

    class _View:
        pass

    page = paginator.paginate_queryset(qs, request, view=_View())
    return {
        "rows": page,
        "count": paginator.page.paginator.count,
        "next": paginator.get_next_link(),
        "previous": paginator.get_previous_link(),
    }
