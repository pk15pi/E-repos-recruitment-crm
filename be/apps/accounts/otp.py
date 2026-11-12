"""Email one-time codes for sign-in and password reset.

Codes are random six-digit values; only an HMAC of the code is stored, so a
database leak does not expose usable sign-in codes. Codes are never returned
from the API or written to logs.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import EmailOTP, User

OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = timedelta(seconds=60)
OTP_MAX_PER_HOUR = 5

_PURPOSE_COPY = {
    EmailOTP.Purpose.LOGIN: (
        "Your Sable sign-in code",
        "Use this code to sign in to Sable",
    ),
    EmailOTP.Purpose.PASSWORD_RESET: (
        "Reset your Sable password",
        "Use this code to reset your Sable password",
    ),
}


def _hash_code(code: str, otp_id) -> str:
    message = f"{otp_id}:{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def _send_code(user: User, purpose: str, code: str) -> None:
    subject, lead = _PURPOSE_COPY[purpose]
    send_mail(
        subject,
        f"{lead}: {code}\n\nThe code expires in ten minutes. If you did not request it, ignore this email.",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
    )


def issue_otp(user: User, purpose: str) -> bool:
    """Create and email a fresh code. Returns False when rate limited."""
    now = timezone.now()
    recent = EmailOTP.objects.filter(user=user, purpose=purpose)
    latest = recent.order_by("-created_at").first()
    if latest is not None and now - latest.created_at < OTP_RESEND_COOLDOWN:
        return False
    if recent.filter(created_at__gte=now - timedelta(hours=1)).count() >= OTP_MAX_PER_HOUR:
        return False
    recent.filter(used_at__isnull=True).update(used_at=now)
    code = f"{secrets.randbelow(1_000_000):06d}"
    row = EmailOTP.objects.create(
        user=user,
        purpose=purpose,
        code_hash="",
        expires_at=now + OTP_TTL,
    )
    row.code_hash = _hash_code(code, row.id)
    row.save(update_fields=["code_hash"])
    _send_code(user, purpose, code)
    return True


def verify_otp(user: User, purpose: str, code: str) -> bool:
    """Consume the newest unused code when it matches. Failed tries are capped."""
    raw = str(code or "").strip()
    now = timezone.now()
    row = (
        EmailOTP.objects.filter(user=user, purpose=purpose, used_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if row is None or row.expires_at <= now or row.attempts >= OTP_MAX_ATTEMPTS:
        return False
    if not hmac.compare_digest(row.code_hash, _hash_code(raw, row.id)):
        EmailOTP.objects.filter(pk=row.pk).update(attempts=F("attempts") + 1)
        return False
    EmailOTP.objects.filter(user=user, purpose=purpose, used_at__isnull=True).update(used_at=now)
    return True
