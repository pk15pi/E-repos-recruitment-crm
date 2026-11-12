"""Call the configured provider, record usage, and enforce limits. Prompts are not logged."""

from __future__ import annotations

import time
from decimal import Decimal

from django.conf import settings

from apps.ai.limits import RateLimitExceeded, allow, provider_slot
from apps.ai.models import AIUsageRecord
from apps.ai.provider import ProviderError, ProviderRateLimitError, get_provider


def execute(organization, operation: str, method: str, *args, **kwargs):
    limit_key = f"{getattr(organization, 'id', 'global')}:{operation}"
    if not allow(limit_key, settings.AI_RATE_LIMIT_PER_MINUTE):
        raise ProviderRateLimitError("The AI rate limit for this minute has been reached.")
    provider = get_provider()
    started = time.monotonic()
    try:
        with provider_slot(getattr(provider, "name", settings.AI_PROVIDER)):
            result = getattr(provider, method)(*args, **kwargs)
    except ProviderError as exc:
        AIUsageRecord.objects.create(
            organization=organization,
            provider=getattr(provider, "name", settings.AI_PROVIDER),
            model=getattr(provider, "model", ""),
            operation=operation,
            status="error",
            error_code=getattr(exc, "code", "provider_error"),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        raise
    usage = result.usage or {}
    AIUsageRecord.objects.create(
        organization=organization,
        provider=result.provider,
        model=result.model,
        operation=operation,
        prompt_version=result.prompt_version,
        schema_version=result.schema_version,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        latency_ms=int(usage.get("latency_ms") or (time.monotonic() - started) * 1000),
        cost_usd=_cost(usage),
        status="ok",
    )
    return result


def _cost(usage: dict):
    if not settings.AI_COST_PER_1K_INPUT and not settings.AI_COST_PER_1K_OUTPUT:
        return None
    incoming = Decimal(settings.AI_COST_PER_1K_INPUT or "0")
    outgoing = Decimal(settings.AI_COST_PER_1K_OUTPUT or "0")
    return (Decimal(int(usage.get("input_tokens") or 0)) / Decimal(1000)) * incoming + (
        Decimal(int(usage.get("output_tokens") or 0)) / Decimal(1000)
    ) * outgoing


class RetryableError(Exception):
    pass
