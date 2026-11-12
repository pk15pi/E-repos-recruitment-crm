import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai.models import AIUsageRecord
from apps.candidates.models import Candidate, CandidateEmail
from apps.jobs.models import Job, JobRequirement
from apps.pipeline.models import Interview, InterviewQuestion
from tests.conftest import login

pytestmark = pytest.mark.django_db


def _candidate(org, name="Asha Rao", email="asha.rao@example.com"):
    candidate = Candidate.objects.create(organization=org, full_name=name, current_title="Backend Engineer")
    CandidateEmail.objects.create(organization=org, candidate=candidate, email=email, is_primary=True)
    return candidate


def _job(org, company, levels=1, questions=5):
    job = Job.objects.create(
        organization=org,
        client_company=company,
        title="Senior Backend Engineer",
        interview_levels=levels,
        interview_question_count=questions,
        status=Job.Status.OPEN,
    )
    for kind, value in [("skill", "Python"), ("skill", "Django"), ("skill", "SQL")]:
        JobRequirement.objects.create(
            organization=org, job=job, kind=kind, label=value, value=value, priority="must_have"
        )
    return job


def _submission(api, candidate, job):
    response = api.post(
        "/api/v1/submissions/",
        {"candidate_id": str(candidate.id), "job_id": str(job.id), "stage": "sourced"},
        format="json",
    )
    assert response.status_code == 201, response.content
    return response.json()


def _schedule_ai(api, submission_id, **extra):
    payload = {
        "submission_id": submission_id,
        "level": "screening",
        "kind": "ai",
        "scheduled_at": timezone.now().isoformat(),
        "duration_minutes": 30,
        "interviewer_name": "Ravi Iyer",
        **extra,
    }
    return api.post("/api/v1/interviews/", payload, format="json")


def test_ai_interview_generates_questions_and_emails_invite(agency):
    api = APIClient()
    login(api, "ravi@sable.test")
    candidate = _candidate(agency["org"])
    job = _job(agency["org"], agency["company"], questions=7)
    submission = _submission(api, candidate, job)
    mail.outbox = []

    created = _schedule_ai(
        api,
        submission["id"],
        question_source="random",
        meeting_url="https://meet.google.com/abc-defg-hij",
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["kind"] == "ai"
    assert body["question_source"] == "random"
    assert body["question_count"] == 7
    assert len(body["questions"]) == 7
    assert body["meeting_provider"] == "google_meet"
    assert body["join_url"].startswith("http://127.0.0.1:43123/interview/")
    assert body["invitation"]["sent"] is True
    assert body["invited_at"]

    assert len(mail.outbox) == 1
    invite = mail.outbox[0]
    assert invite.to == ["asha.rao@example.com"]
    assert "Interview invitation" in invite.subject
    assert "http://127.0.0.1:43123/interview/" in invite.body
    assert "meet.google.com/abc-defg-hij" in invite.body
    assert "AI interview feedback" not in invite.body

    assert AIUsageRecord.objects.filter(operation="interview_questions", status="ok").exists()
    listed = api.get("/api/v1/interviews/").json()
    assert listed[0]["join_url"] == body["join_url"]
    assert listed[0]["question_count"] == 7


def test_ai_interview_manual_questions_and_count_override(agency):
    api = APIClient()
    login(api, "ravi@sable.test")
    candidate = _candidate(agency["org"], name="Manual Candidate")
    job = _job(agency["org"], agency["company"], questions=6)
    submission = _submission(api, candidate, job)

    missing = _schedule_ai(api, submission["id"], question_source="manual", questions=[])
    assert missing.status_code == 400
    assert "question" in str(missing.json()["error"]["details"]).lower()

    created = _schedule_ai(
        api,
        submission["id"],
        question_source="manual",
        questions=["Tell us about a payments migration you led.", "How do you review a schema change?"],
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["question_count"] == 2
    assert [row["prompt"] for row in body["questions"]] == [
        "Tell us about a payments migration you led.",
        "How do you review a schema change?",
    ]

    updated = api.put(
        f"/api/v1/interviews/{body['id']}/questions/",
        {"questions": ["Question one?", "Question two?", "Question three?"]},
        format="json",
    )
    assert updated.status_code == 200, updated.content
    assert updated.json()["question_count"] == 3

    second_candidate = _candidate(agency["org"], name="Count Candidate", email="count@example.com")
    second_submission = _submission(api, second_candidate, job)
    overridden = _schedule_ai(api, second_submission["id"], question_source="random", question_count=3)
    assert overridden.status_code == 201, overridden.content
    assert overridden.json()["question_count"] == 3
    assert len(overridden.json()["questions"]) == 3

    third_candidate = _candidate(agency["org"], name="Bounds Candidate", email="bounds@example.com")
    third_submission = _submission(api, third_candidate, job)
    bad_count = _schedule_ai(api, third_submission["id"], question_source="random", question_count=25)
    assert bad_count.status_code == 400
    assert "question_count" in bad_count.json()["error"]["details"]
    assert not Interview.objects.filter(submission_id=third_submission["id"]).exists()


def test_candidate_joins_submits_and_recruiter_receives_ai_feedback(agency):
    api = APIClient()
    login(api, "ravi@sable.test")
    candidate = _candidate(agency["org"], name="Join Candidate", email="join@example.com")
    job = _job(agency["org"], agency["company"], questions=3)
    submission = _submission(api, candidate, job)
    created = _schedule_ai(api, submission["id"], question_source="random")
    assert created.status_code == 201, created.content
    body = created.json()
    token = body["join_url"].rsplit("/", 1)[-1]
    mail.outbox = []

    anonymous = APIClient()
    invalid = anonymous.get("/api/v1/interviews/join/not-a-token/")
    assert invalid.status_code == 403
    assert invalid.json()["error"]["code"] == "invalid_token"

    room = anonymous.get(f"/api/v1/interviews/join/{token}/")
    assert room.status_code == 200, room.content
    room_body = room.json()
    assert room_body["submitted"] is False
    assert len(room_body["questions"]) == 3
    assert "asha" not in str(room_body).lower()
    assert "ai_report" not in room_body

    incomplete = anonymous.post(
        f"/api/v1/interviews/join/{token}/",
        {"answers": [{"question_id": room_body["questions"][0]["id"], "answer": "Only one answer."}]},
        format="json",
    )
    assert incomplete.status_code == 400
    assert incomplete.json()["error"]["code"] == "incomplete_answers"

    answers = [
        {
            "question_id": row["id"],
            "answer": (
                "I built a Python and Django service backed by SQL for payment reconciliation. "
                "I owned the schema, reviewed the migration, and ran the rollout in stages."
            ),
        }
        for row in room_body["questions"]
    ]
    submitted = anonymous.post(f"/api/v1/interviews/join/{token}/", {"answers": answers}, format="json")
    assert submitted.status_code == 200, submitted.content
    assert submitted.json()["submitted"] is True
    assert submitted.json()["feedback_shared"] is True

    interview = Interview.objects.get(id=body["id"])
    assert interview.status == Interview.Status.COMPLETED
    assert interview.outcome == Interview.Outcome.PENDING
    assert interview.ai_status == "ready"
    assert interview.ai_feedback
    assert interview.ai_score is not None
    assert interview.ai_recommendation in {"advance", "hold", "reject"}
    assert interview.questions.filter(answered_at__isnull=False).count() == 3

    assert len(mail.outbox) == 1
    report = mail.outbox[0]
    assert report.to == ["ravi@sable.test"]
    assert "AI interview feedback" in report.subject
    assert "decision support" in report.body.lower()

    duplicate = anonymous.post(f"/api/v1/interviews/join/{token}/", {"answers": answers}, format="json")
    assert duplicate.status_code == 400
    assert duplicate.json()["error"]["code"] == "already_submitted"

    after = anonymous.get(f"/api/v1/interviews/join/{token}/").json()
    assert after["submitted"] is True
    assert after["questions"] == []

    recruiter_view = next(row for row in api.get("/api/v1/interviews/").json() if row["id"] == body["id"])
    assert recruiter_view["ai_report"]["score"] == interview.ai_score
    assert recruiter_view["questions"][0]["answer"]

    client = APIClient()
    login(client, "client@sable.test")
    client_view = next(row for row in client.get("/api/v1/interviews/").json() if row["id"] == body["id"])
    assert client_view["join_url"] is None
    assert client_view["ai_report"] is None
    assert client_view["questions"] == []

    decided = api.post(
        f"/api/v1/interviews/{body['id']}/feedback/",
        {"feedback": "Reviewed the answers and AI notes.", "rating": 4, "outcome": "passed"},
        format="json",
    )
    assert decided.status_code == 200, decided.content
    assert decided.json()["outcome"] == "passed"
    submission_row = api.get(f"/api/v1/submissions/?job_id={job.id}").json()[0]
    assert submission_row["stage"] == "screened"


def test_client_cannot_schedule_or_email_ai_interview(agency):
    candidate = _candidate(agency["org"], name="Client Blocked", email="blocked@example.com")
    job = _job(agency["org"], agency["company"], questions=4)
    recruiter = APIClient()
    login(recruiter, "ravi@sable.test")
    submission = _submission(recruiter, candidate, job)
    created = _schedule_ai(recruiter, submission["id"], question_source="random")
    assert created.status_code == 201, created.content

    client = APIClient()
    login(client, "client@sable.test")
    denied = client.post(
        "/api/v1/interviews/",
        {"submission_id": submission["id"], "level": "screening", "kind": "ai"},
        format="json",
    )
    assert denied.status_code == 403
    invite = client.post(f"/api/v1/interviews/{created.json()['id']}/invite/", {}, format="json")
    assert invite.status_code == 403
    report = client.post(f"/api/v1/interviews/{created.json()['id']}/ai-report/", {}, format="json")
    assert report.status_code == 403


def test_ai_interview_rejects_non_meeting_links(agency):
    api = APIClient()
    login(api, "ravi@sable.test")
    candidate = _candidate(agency["org"], name="Meeting Link Candidate")
    job = _job(agency["org"], agency["company"], questions=2)
    submission = _submission(api, candidate, job)
    invalid = _schedule_ai(api, submission["id"], question_source="random", meeting_url="https://example.com/meeting")
    assert invalid.status_code == 400
    assert "meeting_url" in invalid.json()["error"]["details"]
    assert Interview.objects.filter(submission_id=submission["id"]).count() == 0
    assert InterviewQuestion.objects.count() == 0
