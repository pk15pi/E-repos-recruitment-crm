import logging
import re


class RedactFilter(logging.Filter):
    """Drop secrets and anything that looks like a bearer token or resume dump."""

    _patterns = (
        re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.I),
        re.compile(r"(AI_API_KEY|SECRET_KEY|PASSWORD|api_key)\s*[=:]\s*\S+", re.I),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for pattern in self._patterns:
            redacted = pattern.sub("[redacted]", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        if len(record.msg) > 2000:
            record.msg = str(record.msg)[:2000] + "…"
            record.args = ()
        return True
