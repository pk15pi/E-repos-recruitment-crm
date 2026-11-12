import re
from datetime import timedelta

from django.core import mail
from django.utils import timezone

from apps.accounts.models import EmailOTP, User
from tests.conftest import PASSWORD


def _code_from_last_mail() -> str:
    body = mail.outbox[-1].body
    match = re.search(r"\b(\d{6})\b", body)
    assert match, body
    return match.group(1)


def test_otp_login_request_and_verify(agency, api):
    response = api.post("/api/v1/auth/otp/request/", {"email": "ada@sable.test"}, format="json")
    assert response.status_code == 200
    assert set(response.json()) == {"message"}
    assert "debug" not in response.json()
    assert len(mail.outbox) == 1
    code = _code_from_last_mail()
    row = EmailOTP.objects.get(user=agency["admin"], purpose=EmailOTP.Purpose.LOGIN)
    assert row.code_hash and row.code_hash != code
    assert row.attempts == 0

    wrong = "000000" if code != "000000" else "111111"
    denied = api.post(
        "/api/v1/auth/otp/verify/", {"email": "ada@sable.test", "code": wrong}, format="json"
    )
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "invalid_otp"
    row.refresh_from_db()
    assert row.attempts == 1

    accepted = api.post(
        "/api/v1/auth/otp/verify/", {"email": "ada@sable.test", "code": code}, format="json"
    )
    assert accepted.status_code == 200
    payload = accepted.json()
    assert payload["access"] and payload["refresh"]
    assert payload["user"]["email"] == "ada@sable.test"
    assert payload["user"]["membership"]["role"] == "agency_admin"

    reused = api.post(
        "/api/v1/auth/otp/verify/", {"email": "ada@sable.test", "code": code}, format="json"
    )
    assert reused.status_code == 400


def test_otp_request_does_not_reveal_unknown_account(agency, api):
    response = api.post("/api/v1/auth/otp/request/", {"email": "nobody@sable.test"}, format="json")
    assert response.status_code == 200
    assert response.json() == {
        "message": "If an account exists for that email, a one-time code was sent."
    }
    assert not EmailOTP.objects.exists()
    assert len(mail.outbox) == 0


def test_otp_password_reset_and_purpose_isolation(agency, api):
    login_request = api.post("/api/v1/auth/otp/request/", {"email": "ravi@sable.test"}, format="json")
    assert login_request.status_code == 200
    login_code = _code_from_last_mail()
    cross = api.post(
        "/api/v1/auth/password-reset/otp/confirm/",
        {"email": "ravi@sable.test", "code": login_code, "password": "New-Harbor-88"},
        format="json",
    )
    assert cross.status_code == 400

    reset_request = api.post(
        "/api/v1/auth/password-reset/otp/", {"email": "ravi@sable.test"}, format="json"
    )
    assert reset_request.status_code == 200
    reset_code = _code_from_last_mail()
    weak = api.post(
        "/api/v1/auth/password-reset/otp/confirm/",
        {"email": "ravi@sable.test", "code": reset_code, "password": "short"},
        format="json",
    )
    assert weak.status_code == 400
    confirmed = api.post(
        "/api/v1/auth/password-reset/otp/confirm/",
        {"email": "ravi@sable.test", "code": reset_code, "password": "New-Harbor-88"},
        format="json",
    )
    assert confirmed.status_code == 200
    assert confirmed.json() == {"status": "password_updated"}

    stale = api.post(
        "/api/v1/auth/login/", {"email": "ravi@sable.test", "password": PASSWORD}, format="json"
    )
    assert stale.status_code == 401
    fresh = api.post(
        "/api/v1/auth/login/", {"email": "ravi@sable.test", "password": "New-Harbor-88"}, format="json"
    )
    assert fresh.status_code == 200
    assert User.objects.get(pk=agency["recruiter"].pk).check_password("New-Harbor-88")


def test_otp_expiry_and_attempt_cap(agency, api):
    api.post("/api/v1/auth/otp/request/", {"email": "ada@sable.test"}, format="json")
    expired_code = _code_from_last_mail()
    EmailOTP.objects.filter(user=agency["admin"], purpose=EmailOTP.Purpose.LOGIN).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    expired = api.post(
        "/api/v1/auth/otp/verify/", {"email": "ada@sable.test", "code": expired_code}, format="json"
    )
    assert expired.status_code == 400

    api.post("/api/v1/auth/otp/request/", {"email": "ravi@sable.test"}, format="json")
    code = _code_from_last_mail()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        denied = api.post(
            "/api/v1/auth/otp/verify/", {"email": "ravi@sable.test", "code": wrong}, format="json"
        )
        assert denied.status_code == 400
    locked = api.post(
        "/api/v1/auth/otp/verify/", {"email": "ravi@sable.test", "code": code}, format="json"
    )
    assert locked.status_code == 400
    row = EmailOTP.objects.get(user=agency["recruiter"], purpose=EmailOTP.Purpose.LOGIN)
    assert row.attempts == 5


def test_otp_resend_cooldown_and_hourly_cap(agency, api):
    api.post("/api/v1/auth/otp/request/", {"email": "ravi@sable.test"}, format="json")
    api.post("/api/v1/auth/otp/request/", {"email": "ravi@sable.test"}, format="json")
    rows = EmailOTP.objects.filter(user=agency["recruiter"], purpose=EmailOTP.Purpose.LOGIN)
    assert rows.count() == 1
    assert len(mail.outbox) == 1

    now = timezone.now()
    for _ in range(4):
        row = EmailOTP.objects.create(
            user=agency["recruiter"],
            purpose=EmailOTP.Purpose.LOGIN,
            code_hash="x",
            expires_at=now + timedelta(minutes=10),
        )
    rows.update(created_at=now - timedelta(minutes=5))
    rows.filter(pk=rows.first().pk).update(created_at=now - timedelta(seconds=61))

    capped = api.post("/api/v1/auth/otp/request/", {"email": "ravi@sable.test"}, format="json")
    assert capped.status_code == 200
    assert EmailOTP.objects.filter(user=agency["recruiter"], purpose=EmailOTP.Purpose.LOGIN).count() == 5
    assert len(mail.outbox) == 1
