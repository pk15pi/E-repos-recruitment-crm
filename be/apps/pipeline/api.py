from urllib.parse import urlparse

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.ai.provider import ProviderError
from apps.candidates.models import Candidate
from apps.clients.models import ClientCompany
from apps.common.audit import record_audit
from apps.common.permissions import AgencyOnly, IsAuthenticatedInOrg, TenantMixin
from apps.common.scoping import candidate_queryset, client_company_ids
from apps.common.tenancy import is_client, require_org
from apps.jobs.models import Job
from apps.pipeline import interviews as interview_flow
from apps.pipeline.models import (
    CandidateShare,
    CandidateSubmission,
    Interview,
    InterviewQuestion,
    Shortlist,
    ShortlistItem,
)

CLIENT_STAGE_EDITS = {CandidateSubmission.Stage.REJECTED, CandidateSubmission.Stage.ON_HOLD}
LEVELS = [
    Interview.Level.SCREENING,
    Interview.Level.L1,
    Interview.Level.L2,
    Interview.Level.L3,
    Interview.Level.L4,
    Interview.Level.L5,
]
INTERVIEW_STAGES = {
    CandidateSubmission.Stage.SOURCED,
    CandidateSubmission.Stage.SCREENED,
    CandidateSubmission.Stage.SHORTLISTED,
    CandidateSubmission.Stage.SUBMITTED,
    CandidateSubmission.Stage.INTERVIEW,
}


class SubmissionListView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request):
        qs = _submissions(request).select_related("candidate", "job", "client_company").prefetch_related("interviews")
        stage = request.query_params.get("stage")
        if stage:
            qs = qs.filter(stage=stage)
        if request.query_params.get("job_id"):
            qs = qs.filter(job_id=request.query_params["job_id"])
        return Response([_submission(row) for row in qs[:200]])

    def post(self, request):
        if is_client(request):
            raise PermissionDenied("Clients cannot submit candidates.")
        candidate = get_object_or_404(candidate_queryset(request), pk=request.data.get("candidate_id"))
        job = get_object_or_404(Job, organization=require_org(request), pk=request.data.get("job_id"))
        if job.client_company_id is None:
            raise ValidationError({"job_id": "Attach the requisition to a client before submitting."})
        _require_entitlement(job.client_company)
        stage = request.data.get("stage") or CandidateSubmission.Stage.SUBMITTED
        if stage not in CandidateSubmission.Stage.values:
            raise ValidationError({"stage": "Unknown stage."})
        submission, created = CandidateSubmission.objects.get_or_create(
            organization=request.organization,
            job=job,
            candidate=candidate,
            defaults={
                "client_company": job.client_company,
                "stage": stage,
                "submitted_by": request.user,
            },
        )
        if not created:
            submission.stage = stage
            submission.save(update_fields=["stage", "updated_at"])
        share, _ = CandidateShare.objects.get_or_create(
            organization=request.organization,
            candidate=candidate,
            client_company=job.client_company,
            revoked_at=None,
            defaults={
                "shared_by": request.user,
                "include_resume": bool(request.data.get("include_resume", True)),
                "include_contact": bool(request.data.get("include_contact", False)),
                "include_compensation": bool(request.data.get("include_compensation", False)),
            },
        )
        record_audit(request, "submission_stage", submission, stage)
        record_audit(request, "share_create", share, job.client_company.name)
        return Response(_submission(submission), status=201 if created else 200)


class SubmissionDetailView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def patch(self, request, submission_id):
        submission = get_object_or_404(_submissions(request), pk=submission_id)
        if "stage" in request.data:
            stage = request.data["stage"]
            if stage not in CandidateSubmission.Stage.values:
                raise ValidationError({"stage": "Unknown stage."})
            if is_client(request) and stage not in CLIENT_STAGE_EDITS:
                raise PermissionDenied("You can reject or place this on hold. Other stages stay with the agency.")
            if not is_client(request):
                _validate_stage_change(submission, stage)
            submission.stage = stage
        for field in ("offer_amount", "offer_currency", "joining_date", "placement_notes"):
            if field in request.data:
                if is_client(request):
                    raise PermissionDenied()
                setattr(submission, field, request.data[field] or ("" if field in {"offer_currency", "placement_notes"} else None))
        submission.save()
        record_audit(request, "submission_stage", submission, submission.stage)
        return Response(_submission(submission))


class ShareView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def get(self, request):
        qs = CandidateShare.objects.filter(organization=require_org(request)).select_related("candidate", "client_company")
        if request.query_params.get("candidate_id"):
            qs = qs.filter(candidate_id=request.query_params["candidate_id"])
        return Response([_share(row) for row in qs[:200]])

    def post(self, request):
        candidate = get_object_or_404(candidate_queryset(request), pk=request.data.get("candidate_id"))
        company = get_object_or_404(ClientCompany, organization=require_org(request), pk=request.data.get("client_company_id"))
        _require_entitlement(company)
        share = CandidateShare.objects.create(
            organization=request.organization,
            candidate=candidate,
            client_company=company,
            shared_by=request.user,
            include_resume=bool(request.data.get("include_resume", False)),
            include_contact=bool(request.data.get("include_contact", False)),
            include_compensation=bool(request.data.get("include_compensation", False)),
            note=(request.data.get("note") or "")[:400],
        )
        record_audit(request, "share_create", share, company.name)
        return Response(_share(share), status=201)


class ShareRevokeView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request, share_id):
        share = get_object_or_404(CandidateShare, organization=require_org(request), pk=share_id, revoked_at__isnull=True)
        share.revoked_at = timezone.now()
        share.revoked_by = request.user
        share.save(update_fields=["revoked_at", "revoked_by", "updated_at"])
        record_audit(request, "share_revoke", share, share.client_company.name)
        return Response(_share(share))


class ShortlistView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request):
        return Response([_shortlist(row) for row in _shortlists(request)])

    def post(self, request):
        if is_client(request):
            raise PermissionDenied()
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "Name the shortlist."})
        shortlist = Shortlist.objects.create(
            organization=request.organization,
            name=name[:160],
            created_by=request.user,
            job_id=request.data.get("job_id") or None,
            client_company_id=request.data.get("client_company_id") or None,
        )
        return Response(_shortlist(shortlist), status=201)


class ShortlistItemView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request, shortlist_id):
        shortlist = get_object_or_404(_shortlists(request), pk=shortlist_id)
        candidate = get_object_or_404(candidate_queryset(request), pk=request.data.get("candidate_id"))
        item, created = ShortlistItem.objects.get_or_create(
            shortlist=shortlist,
            candidate=candidate,
            defaults={"added_by": request.user, "note": (request.data.get("note") or "")[:400]},
        )
        record_audit(request, "shortlist_add", candidate, shortlist.name)
        return Response({"id": str(item.id), "candidate_id": str(candidate.id), "created": created}, status=201 if created else 200)

    def delete(self, request, shortlist_id, candidate_id):
        shortlist = get_object_or_404(_shortlists(request), pk=shortlist_id)
        item = get_object_or_404(ShortlistItem, shortlist=shortlist, candidate_id=candidate_id)
        item.delete()
        return Response(status=204)


class InterviewView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def get(self, request):
        qs = _interviews(request).select_related("candidate", "submission", "submission__job").prefetch_related("questions")
        return Response([_interview(row, request) for row in qs[:200]])

    def post(self, request):
        if is_client(request):
            raise PermissionDenied()
        submission = get_object_or_404(
            _submissions(request).select_related("candidate", "job"), pk=request.data.get("submission_id")
        )
        level = request.data.get("level") or Interview.Level.SCREENING
        if level not in Interview.Level.values:
            raise ValidationError({"level": "Unknown interview level."})
        _validate_new_interview(submission, level)
        duration = request.data.get("duration_minutes") or None
        if duration not in (None, ""):
            try:
                duration = int(duration)
            except (TypeError, ValueError):
                raise ValidationError({"duration_minutes": "Enter the interview length in minutes."})
        kind = request.data.get("kind") or Interview.Kind.MANUAL
        if kind not in Interview.Kind.values:
            raise ValidationError({"kind": "Choose a manual or AI interview."})
        meeting_provider, meeting_url = _clean_meeting_url(request.data.get("meeting_url"))
        if kind == Interview.Kind.AI:
            question_source, question_count, manual_questions = _question_settings(request.data, submission.job)
        else:
            question_source, question_count, manual_questions = "", 0, []
        interview = Interview.objects.create(
            organization=request.organization,
            submission=submission,
            candidate=submission.candidate,
            level=level,
            scheduled_at=_scheduled_at(request.data.get("scheduled_at")),
            duration_minutes=duration,
            mode="ui" if level == Interview.Level.SCREENING else (request.data.get("mode") or "ui")[:20],
            interviewer_name=(request.data.get("interviewer_name") or "")[:200],
            created_by=request.user,
            kind=kind,
            question_source=question_source,
            question_count=question_count,
            meeting_provider=meeting_provider,
            meeting_url=meeting_url,
        )
        warning = ""
        invitation = {"sent": False, "error": ""}
        if kind == Interview.Kind.AI:
            if question_source == Interview.QuestionSource.MANUAL:
                interview_flow.replace_questions(interview, manual_questions, source=Interview.QuestionSource.MANUAL)
                interview.question_count = interview.questions.count()
                interview.ai_status = "questions_ready"
                interview.save(update_fields=["question_count", "ai_status", "updated_at"])
            else:
                try:
                    interview_flow.generate_questions(interview, question_count)
                except ProviderError as exc:
                    warning = f"The interview was scheduled, but question generation failed: {exc}"
                    interview.ai_status = "failed"
                    interview.save(update_fields=["ai_status", "updated_at"])
            invitation = _invite(interview)
        record_audit(request, "interview_schedule", interview, f"{level} {kind} interview scheduled")
        payload = _interview(interview, request)
        payload["invitation"] = invitation
        if warning:
            payload["warning"] = warning
        return Response(payload, status=201)


class InterviewQuestionView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def put(self, request, interview_id):
        interview = get_object_or_404(_interviews(request), pk=interview_id)
        if interview.kind != Interview.Kind.AI:
            raise ValidationError({"questions": "Only AI interviews keep a question list."})
        if interview.questions.filter(answered_at__isnull=False).exists():
            raise ValidationError({"questions": "The candidate has already answered; the questions are locked."})
        rows = _manual_questions(request.data.get("questions"))
        interview_flow.replace_questions(interview, rows, source=Interview.QuestionSource.MANUAL)
        interview.question_source = Interview.QuestionSource.MANUAL
        interview.question_count = interview.questions.count()
        interview.ai_status = "questions_ready"
        interview.save(update_fields=["question_source", "question_count", "ai_status", "updated_at"])
        record_audit(request, "interview_questions", interview, f"{interview.question_count} manual questions")
        return Response(_interview(interview, request))


class InterviewInviteView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request, interview_id):
        interview = get_object_or_404(_interviews(request), pk=interview_id)
        if interview.kind != Interview.Kind.AI:
            raise ValidationError({"interview": "Invitations are only sent for AI interviews."})
        sent, error = _invite(interview)
        if not sent:
            raise ValidationError({"email": error})
        record_audit(request, "interview_invite", interview, "Invitation emailed")
        return Response(_interview(interview, request))


class InterviewAIReportView(TenantMixin, APIView):
    permission_classes = [AgencyOnly]

    def post(self, request, interview_id):
        interview = get_object_or_404(_interviews(request), pk=interview_id)
        if interview.kind != Interview.Kind.AI:
            raise ValidationError({"interview": "This is not an AI interview."})
        if not interview.questions.filter(answered_at__isnull=False).exists():
            raise ValidationError({"interview": "The candidate has not submitted answers yet."})
        if not interview_flow.evaluate_submission(interview):
            raise ReportUnavailable("AI feedback could not be generated. Try again or read the answers in Sable.")
        record_audit(request, "interview_ai_report", interview, interview.ai_recommendation)
        return Response(_interview(interview, request))


class InterviewFeedbackView(TenantMixin, APIView):
    permission_classes = [IsAuthenticatedInOrg]

    def post(self, request, interview_id):
        interview = get_object_or_404(_interviews(request), pk=interview_id)
        feedback = (request.data.get("feedback") or "").strip()
        if not feedback:
            raise ValidationError({"feedback": "Write the feedback before saving."})
        rating = request.data.get("rating")
        if rating not in (None, ""):
            try:
                rating = int(rating)
            except (TypeError, ValueError):
                raise ValidationError({"rating": "Rating must be from 1 to 5."})
            if rating not in {1, 2, 3, 4, 5}:
                raise ValidationError({"rating": "Rating must be from 1 to 5."})
        else:
            rating = None
        outcome = request.data.get("outcome") or Interview.Outcome.PASSED
        if outcome not in {Interview.Outcome.PASSED, Interview.Outcome.FAILED}:
            raise ValidationError({"outcome": "Record the candidate as passed or failed."})
        interview.feedback = feedback
        interview.rating = rating
        interview.feedback_by = request.user
        interview.outcome = outcome
        interview.status = Interview.Status.COMPLETED
        interview.save()
        _advance_after_outcome(interview)
        record_audit(request, "feedback_create", interview, f"{interview.level} {outcome}")
        return Response(_interview(interview, request))


class InterviewJoinThrottle(AnonRateThrottle):
    scope = "anon"


class InterviewJoinView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [InterviewJoinThrottle]

    def get(self, request, token):
        interview = _resolve_join(token)
        if interview is None:
            return _token_error("invalid_token", "This interview link is not valid or has expired.", status=403)
        if interview.status in {Interview.Status.CANCELLED, Interview.Status.NO_SHOW}:
            return _token_error("interview_closed", "This interview is no longer open.", status=403)
        if interview.started_at is None and interview.status == Interview.Status.SCHEDULED:
            interview.started_at = timezone.now()
            interview.save(update_fields=["started_at", "updated_at"])
        return Response(interview_flow.public_payload(interview))

    def post(self, request, token):
        interview = _resolve_join(token)
        if interview is None:
            return _token_error("invalid_token", "This interview link is not valid or has expired.", status=403)
        if interview.status == Interview.Status.COMPLETED:
            return _token_error("already_submitted", "Your answers were already submitted.", status=400)
        if interview.status != Interview.Status.SCHEDULED:
            return _token_error("interview_closed", "This interview is not accepting answers.", status=403)
        questions = list(interview.questions.all())
        if not questions:
            return _token_error("no_questions", "This interview does not have questions yet.", status=409)
        answers = request.data.get("answers")
        if not isinstance(answers, list):
            return _token_error("invalid_answers", "Send one answer per question.", status=400)
        by_id = {str(row.id): row for row in questions}
        submitted: dict[str, str] = {}
        for item in answers:
            if not isinstance(item, dict):
                continue
            question = by_id.get(str(item.get("question_id") or ""))
            text = str(item.get("answer") or "").strip()
            if question is None or not text:
                continue
            submitted[str(question.id)] = text[:5000]
        if len(submitted) != len(questions):
            return _token_error("incomplete_answers", "Answer every question before submitting.", status=400)
        now = timezone.now()
        for question in questions:
            question.answer = submitted[str(question.id)]
            question.answered_at = now
            question.save(update_fields=["answer", "answered_at"])
        if interview.started_at is None:
            interview.started_at = now
        interview.status = Interview.Status.COMPLETED
        interview.completed_at = now
        interview.save(update_fields=["status", "completed_at", "started_at", "updated_at"])
        shared = interview_flow.evaluate_submission(interview)
        return Response({"submitted": True, "feedback_shared": shared})


class ReportUnavailable(APIException):
    status_code = 502
    default_detail = "AI feedback could not be generated. Try again or read the answers in Sable."
    default_code = "ai_report_unavailable"


MEETING_HOSTS = {
    "meet.google.com": "google_meet",
    "teams.microsoft.com": "teams",
    "teams.live.com": "teams",
}


def _scheduled_at(value):
    if value in (None, ""):
        return None
    if isinstance(value, str):
        from django.utils.dateparse import parse_datetime

        parsed = parse_datetime(value)
        if parsed is None:
            raise ValidationError({"scheduled_at": "Use a date and time for the interview."})
        value = parsed
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return value


def _clean_meeting_url(value) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    parsed = urlparse(text)
    provider = MEETING_HOSTS.get((parsed.hostname or "").lower())
    if parsed.scheme != "https" or provider is None:
        raise ValidationError(
            {"meeting_url": "Paste a Google Meet or Microsoft Teams https link, or leave it empty."}
        )
    return provider, text[:500]


def _question_settings(data: dict, job: Job) -> tuple[str, int, list[dict]]:
    source = data.get("question_source") or (
        Interview.QuestionSource.MANUAL if data.get("questions") else Interview.QuestionSource.RANDOM
    )
    if source not in Interview.QuestionSource.values:
        raise ValidationError({"question_source": "Choose generated or manual questions."})
    if source == Interview.QuestionSource.MANUAL:
        rows = _manual_questions(data.get("questions"))
        return source, len(rows), rows
    raw_count = data.get("question_count")
    if raw_count in (None, ""):
        count = job.interview_question_count
    else:
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            raise ValidationError({"question_count": "Enter how many questions the interview should ask."})
    if count < 1 or count > 20:
        raise ValidationError({"question_count": "Question counts must be between 1 and 20."})
    return source, count, []


def _manual_questions(value) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ValidationError({"questions": "Add at least one question, or choose generated questions."})
    rows = []
    for item in value[:20]:
        if isinstance(item, dict):
            prompt = str(item.get("prompt") or "").strip()
            focus = str(item.get("focus") or "").strip()
        else:
            prompt = str(item or "").strip()
            focus = ""
        if not prompt:
            raise ValidationError({"questions": "Every question needs text."})
        rows.append({"prompt": prompt[:4000], "focus": focus[:120]})
    return rows


def _invite(interview: Interview) -> dict:
    if not interview.questions.exists():
        return {"sent": False, "error": "Add at least one question before inviting the candidate."}
    sent, error = interview_flow.invite_candidate(interview)
    return {"sent": sent, "error": error}


def _resolve_join(token: str) -> Interview | None:
    return interview_flow.resolve_join_token(token)


def _token_error(code: str, message: str, status: int) -> Response:
    return Response(
        {"error": {"code": code, "message": message, "details": {}}},
        status=status,
    )


def _submissions(request):
    qs = CandidateSubmission.objects.filter(organization=require_org(request))
    if is_client(request):
        qs = qs.filter(client_company_id__in=client_company_ids(request))
    return qs


def _shortlists(request):
    qs = Shortlist.objects.filter(organization=require_org(request)).prefetch_related("items__candidate")
    if is_client(request):
        qs = qs.filter(client_company_id__in=client_company_ids(request))
    return qs


def _interviews(request):
    qs = Interview.objects.filter(organization=require_org(request))
    if is_client(request):
        qs = qs.filter(submission__client_company_id__in=client_company_ids(request))
    return qs


def _require_entitlement(company: ClientCompany) -> None:
    if not company.distribution_enabled:
        raise ValidationError(
            {
                "client_company_id": (
                    "This client does not have a distribution plan. "
                    "An agency admin can enable a paid plan or grant free access."
                )
            }
        )


def _required_levels(job: Job) -> list[str]:
    return LEVELS[1 : 1 + job.interview_levels]


def _passed_levels(submission: CandidateSubmission) -> set[str]:
    return set(
        submission.interviews.filter(outcome=Interview.Outcome.PASSED).values_list("level", flat=True)
    )


def _validate_stage_change(submission: CandidateSubmission, stage: str) -> None:
    if stage not in {
        CandidateSubmission.Stage.SCREENED,
        CandidateSubmission.Stage.INTERVIEW,
        CandidateSubmission.Stage.OFFER,
        CandidateSubmission.Stage.HIRED,
    }:
        return
    passed = _passed_levels(submission)
    if Interview.Level.SCREENING not in passed:
        raise ValidationError(
            {"stage": "Run the in-app screening interview and record a pass before moving this candidate forward."}
        )
    if stage in {CandidateSubmission.Stage.OFFER, CandidateSubmission.Stage.HIRED}:
        missing = [level.upper() for level in _required_levels(submission.job) if level not in passed]
        if missing:
            raise ValidationError(
                {"stage": f"Pass every interview level before an offer or hire. Missing: {', '.join(missing)}."}
            )


def _validate_new_interview(submission: CandidateSubmission, level: str) -> None:
    job = submission.job
    if level != Interview.Level.SCREENING:
        index = LEVELS.index(level)
        if index > job.interview_levels:
            raise ValidationError(
                {"level": f"This requisition requires {job.interview_levels} interview level(s) after screening."}
            )
        passed = _passed_levels(submission)
        if Interview.Level.SCREENING not in passed:
            raise ValidationError({"level": "Pass the screening interview before scheduling an interview level."})
        for earlier in LEVELS[1:index]:
            if earlier not in passed:
                raise ValidationError(
                    {"level": f"Pass {earlier.upper()} before scheduling {level.upper()}."}
                )
    existing = (
        submission.interviews.filter(level=level)
        .exclude(status__in={Interview.Status.CANCELLED, Interview.Status.NO_SHOW})
        .exists()
    )
    if existing:
        raise ValidationError({"level": f"{level.upper()} already has an interview on this submission."})


def _advance_after_outcome(interview: Interview) -> None:
    submission = interview.submission
    if interview.outcome != Interview.Outcome.PASSED:
        return
    if interview.level == Interview.Level.SCREENING:
        if submission.stage in {CandidateSubmission.Stage.SOURCED, CandidateSubmission.Stage.SCREENED}:
            submission.stage = CandidateSubmission.Stage.SCREENED
            submission.save(update_fields=["stage", "updated_at"])
        return
    if submission.stage in INTERVIEW_STAGES:
        submission.stage = CandidateSubmission.Stage.INTERVIEW
        submission.save(update_fields=["stage", "updated_at"])


def _interview_progress(row: CandidateSubmission) -> list[dict]:
    rows = list(row.interviews.all())
    progress = []
    for level in [Interview.Level.SCREENING, *_required_levels(row.job)]:
        level_rows = [item for item in rows if item.level == level]
        if not level_rows:
            progress.append({"level": level, "status": "not_started", "outcome": Interview.Outcome.PENDING, "interview_id": None})
            continue
        latest = max(level_rows, key=lambda item: item.created_at)
        status = latest.outcome if latest.status == Interview.Status.COMPLETED else latest.status
        progress.append(
            {"level": level, "status": status, "outcome": latest.outcome, "interview_id": str(latest.id)}
        )
    return progress


def _submission(row: CandidateSubmission) -> dict:
    progress = _interview_progress(row)
    return {
        "id": str(row.id),
        "stage": row.stage,
        "candidate_id": str(row.candidate_id),
        "candidate_name": row.candidate.full_name or None,
        "job_id": str(row.job_id),
        "job_title": row.job.title or None,
        "interview_levels": row.job.interview_levels,
        "interview_question_count": row.job.interview_question_count,
        "interview_progress": progress,
        "screening_passed": any(
            item["level"] == Interview.Level.SCREENING and item["outcome"] == Interview.Outcome.PASSED
            for item in progress
        ),
        "client_company_id": str(row.client_company_id),
        "client_name": row.client_company.name,
        "client_plan": row.client_company.plan,
        "offer_amount": row.offer_amount,
        "offer_currency": row.offer_currency or None,
        "joining_date": row.joining_date,
        "placement_notes": row.placement_notes or None,
        "updated_at": row.updated_at,
    }


def _share(row: CandidateShare) -> dict:
    return {
        "id": str(row.id),
        "candidate_id": str(row.candidate_id),
        "candidate_name": row.candidate.full_name or None,
        "client_company_id": str(row.client_company_id),
        "client_name": row.client_company.name,
        "include_resume": row.include_resume,
        "include_contact": row.include_contact,
        "include_compensation": row.include_compensation,
        "revoked_at": row.revoked_at,
        "created_at": row.created_at,
    }


def _shortlist(row: Shortlist) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "job_id": str(row.job_id) if row.job_id else None,
        "client_company_id": str(row.client_company_id) if row.client_company_id else None,
        "items": [
            {"candidate_id": str(item.candidate_id), "name": item.candidate.full_name or None, "note": item.note}
            for item in row.items.all()
        ],
    }


def _interview(row: Interview, request=None) -> dict:
    client_view = request is not None and is_client(request)
    payload = {
        "id": str(row.id),
        "submission_id": str(row.submission_id),
        "candidate_id": str(row.candidate_id),
        "candidate_name": row.candidate.full_name or None,
        "job_title": row.submission.job.title or None,
        "job_interview_levels": row.submission.job.interview_levels,
        "level": row.level,
        "kind": row.kind,
        "question_source": row.question_source or None,
        "question_count": row.question_count,
        "outcome": row.outcome,
        "scheduled_at": row.scheduled_at,
        "duration_minutes": row.duration_minutes,
        "mode": row.mode or None,
        "status": row.status,
        "interviewer_name": row.interviewer_name or None,
        "feedback": row.feedback or None,
        "rating": row.rating,
        "meeting_provider": row.meeting_provider or None,
        "meeting_url": row.meeting_url or None,
        "invited_at": row.invited_at,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "join_url": None if client_view or row.kind != Interview.Kind.AI else interview_flow.join_url(row),
        "ai_report": None
        if client_view or row.kind != Interview.Kind.AI
        else interview_flow.report_payload(row),
        "questions": []
        if client_view
        else [
            {
                "id": str(question.id),
                "prompt": question.prompt,
                "focus": question.focus or None,
                "source": question.source,
                "answer": question.answer or None,
                "answered_at": question.answered_at,
            }
            for question in row.questions.all()
        ],
    }
    return payload
