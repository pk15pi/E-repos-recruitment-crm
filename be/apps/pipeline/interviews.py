"""AI interview helpers: questions, signed candidate links, and email workflow."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.core.signing import TimestampSigner
from django.utils import timezone

from apps.ai import service as ai_service
from apps.pipeline.models import Interview, InterviewQuestion

join_signer = TimestampSigner(salt="sable-interview-join")


def join_token(interview: Interview) -> str:
    return join_signer.sign(str(interview.id))


def join_url(interview: Interview) -> str:
    base = settings.INTERVIEW_JOIN_URL.rstrip("/")
    return f"{base}/{join_token(interview)}"


def resolve_join_token(token: str) -> Interview | None:
    from django.core.signing import BadSignature, SignatureExpired

    try:
        raw = join_signer.unsign(token, max_age=settings.INTERVIEW_JOIN_TTL_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    return (
        Interview.objects.filter(id=raw, kind=Interview.Kind.AI)
        .select_related("candidate", "submission", "submission__job")
        .first()
    )


def candidate_email(candidate) -> str:
    row = candidate.emails.filter(is_primary=True).first() or candidate.emails.first()
    return row.email if row else ""


def job_context(interview: Interview) -> dict:
    job = interview.submission.job
    return {
        "title": job.title or "",
        "seniority": job.seniority or "",
        "domain": job.domain or "",
        "location": job.location or "",
        "requirements": [row.label or row.value for row in job.requirements.all()[:20] if row.label or row.value],
        "skills": [
            row.skill.name
            for row in interview.candidate.candidate_skills.select_related("skill").all()[:20]
        ],
        "description": (job.original_description or "")[:4000],
    }


def candidate_context(interview: Interview) -> dict:
    candidate = interview.candidate
    return {
        "current_title": candidate.current_title or "",
        "current_employer": candidate.current_employer or "",
        "total_experience_months": candidate.total_experience_months,
        "skills": [
            row.skill.name for row in candidate.candidate_skills.select_related("skill").all()[:20]
        ],
    }


def generate_questions(interview: Interview, count: int, actor=None) -> None:
    result = ai_service.execute(
        interview.organization,
        "interview_questions",
        "generate_interview_questions",
        job_context(interview),
        candidate_context(interview),
        count,
    )
    replace_questions(interview, result.data.get("questions") or [], source=Interview.QuestionSource.RANDOM)
    interview.question_source = Interview.QuestionSource.RANDOM
    interview.question_count = len(interview.questions.all())
    interview.ai_status = "questions_ready"
    interview.save(update_fields=["question_source", "question_count", "ai_status", "updated_at"])


def replace_questions(interview: Interview, rows: list[dict], source: str) -> None:
    interview.questions.all().delete()
    for index, row in enumerate(rows):
        prompt = str(row.get("prompt") or "").strip()
        if not prompt:
            continue
        InterviewQuestion.objects.create(
            interview=interview,
            prompt=prompt[:4000],
            focus=str(row.get("focus") or "")[:120],
            source=source,
            sort_order=index,
        )


def invite_candidate(interview: Interview) -> tuple[bool, str]:
    recipient = candidate_email(interview.candidate)
    if not recipient:
        return False, "Add a candidate email before sending the invitation."
    job = interview.submission.job
    join = join_url(interview)
    when = (
        timezone.localtime(interview.scheduled_at).strftime("%d %b %Y, %H:%M %Z")
        if interview.scheduled_at
        else "A time the recruiter will confirm"
    )
    duration = f"{interview.duration_minutes} minutes" if interview.duration_minutes else "the time shown in Sable"
    questions = interview.questions.count() or interview.question_count
    lines = [
        f"Hello {interview.candidate.full_name or 'there'},",
        "",
        f"You are invited to an AI interview for {job.title or 'the role'}.",
        f"When: {when}",
        f"Duration: {duration}",
        f"Join link: {join}",
    ]
    if interview.meeting_url:
        lines.append(f"Video room: {interview.meeting_url}")
    else:
        lines.append("The interview runs in your browser. Use the join link above at the scheduled time.")
    lines.extend(
        [
            "",
            f"The interview asks {questions} question(s). Answer in your own words; there are no trick questions.",
            "If you cannot attend, reply to the recruiter who shared this invitation.",
            "",
            settings.DEFAULT_FROM_EMAIL,
        ]
    )
    send_mail(
        f"Interview invitation: {job.title or 'Sable interview'}",
        "\n".join(lines),
        settings.DEFAULT_FROM_EMAIL,
        [recipient],
        fail_silently=True,
    )
    interview.invited_at = timezone.now()
    interview.save(update_fields=["invited_at", "updated_at"])
    return True, ""


def evaluate_submission(interview: Interview) -> bool:
    answers = [
        {"prompt": row.prompt, "focus": row.focus, "answer": row.answer}
        for row in interview.questions.all()
    ]
    try:
        result = ai_service.execute(
            interview.organization,
            "interview_evaluation",
            "evaluate_interview",
            job_context(interview),
            answers,
        )
    except Exception:
        interview.ai_status = "failed"
        interview.save(update_fields=["ai_status", "updated_at"])
        return False
    data = result.data
    interview.ai_status = "ready"
    interview.ai_feedback = data.get("summary") or ""
    interview.ai_recommendation = data.get("recommendation") or ""
    interview.ai_score = data.get("score")
    interview.ai_generated_at = timezone.now()
    interview.save(
        update_fields=[
            "ai_status",
            "ai_feedback",
            "ai_recommendation",
            "ai_score",
            "ai_generated_at",
            "updated_at",
        ]
    )
    email_report(interview, result)
    return True


def email_report(interview: Interview, result=None) -> tuple[bool, str]:
    job = interview.submission.job
    recipient = job.assigned_recruiter or job.created_by or interview.created_by or interview.submission.submitted_by
    if recipient is None or not recipient.email:
        return False, "No recruiter email is available for this interview."
    data = result.data if result is not None else {}
    strengths = data.get("strengths") or []
    concerns = data.get("concerns") or []
    lines = [
        f"AI interview feedback for {interview.candidate.full_name or 'the candidate'}",
        f"Role: {job.title or 'Untitled requisition'}",
        f"Recommendation: {interview.ai_recommendation or 'not available'} (decision support only)",
        f"Score: {interview.ai_score if interview.ai_score is not None else 'not scored'}",
        "",
        interview.ai_feedback or "No AI summary is stored.",
    ]
    if strengths:
        lines.extend(["", "Strengths:"] + [f"- {item}" for item in strengths])
    if concerns:
        lines.extend(["", "Concerns:"] + [f"- {item}" for item in concerns])
    lines.extend(
        [
            "",
            "The AI does not set the outcome. Open the interview in Sable to read the answers and record pass or fail.",
            settings.DEFAULT_FROM_EMAIL,
        ]
    )
    send_mail(
        f"AI interview feedback: {interview.candidate.full_name or 'Candidate'} - {job.title or 'Role'}",
        "\n".join(lines),
        settings.DEFAULT_FROM_EMAIL,
        [recipient.email],
        fail_silently=True,
    )
    return True, ""


def public_payload(interview: Interview) -> dict:
    submitted = interview.status == Interview.Status.COMPLETED or bool(interview.completed_at)
    return {
        "candidate_name": interview.candidate.full_name or "Candidate",
        "job_title": interview.submission.job.title or "Interview",
        "scheduled_at": interview.scheduled_at,
        "duration_minutes": interview.duration_minutes,
        "meeting_url": interview.meeting_url or None,
        "status": interview.status,
        "submitted": submitted,
        "questions": []
        if submitted
        else [
            {"id": str(row.id), "prompt": row.prompt, "focus": row.focus or None}
            for row in interview.questions.all()
        ],
    }


def report_payload(interview: Interview) -> dict:
    return {
        "status": interview.ai_status or None,
        "summary": interview.ai_feedback or None,
        "recommendation": interview.ai_recommendation or None,
        "score": interview.ai_score,
        "generated_at": interview.ai_generated_at,
    }
