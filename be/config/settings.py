"""Sable settings.

Production refuses to boot when required configuration is missing or when the
deterministic dev AI provider is selected. Copy `.env.example` for local work.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR / ".env")


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


SABLE_TESTING = _flag("SABLE_TESTING")
DEBUG = _flag("DJANGO_DEBUG", "false")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
REDIS_URL = os.environ.get("REDIS_URL", "")
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]

AI_PROVIDER = os.environ.get("AI_PROVIDER", "deterministic" if DEBUG or SABLE_TESTING else "").strip().lower()
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")
AI_EMBEDDING_MODEL = os.environ.get("AI_EMBEDDING_MODEL", "text-embedding-3-small")
AI_EMBEDDING_DIMENSIONS = int(os.environ.get("AI_EMBEDDING_DIMENSIONS", "1536"))
AI_TIMEOUT_SECONDS = float(os.environ.get("AI_TIMEOUT_SECONDS", "30"))
AI_MAX_RETRIES = int(os.environ.get("AI_MAX_RETRIES", "3"))
AI_RATE_LIMIT_PER_MINUTE = int(os.environ.get("AI_RATE_LIMIT_PER_MINUTE", "30"))
AI_MAX_CONCURRENCY = int(os.environ.get("AI_MAX_CONCURRENCY", "4"))
AI_JSON_MODE = os.environ.get("AI_JSON_MODE", "json_schema")
AI_COST_PER_1K_INPUT = os.environ.get("AI_COST_PER_1K_INPUT", "")
AI_COST_PER_1K_OUTPUT = os.environ.get("AI_COST_PER_1K_OUTPUT", "")

STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local").strip().lower()
STORAGE_LOCAL_ROOT = Path(os.environ.get("STORAGE_LOCAL_ROOT", str(BASE_DIR / "var" / "media")))
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY", "")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")
S3_ENDPOINT_URL = S3_ENDPOINT_URL.rstrip("/")
# Clients sign URLs against the endpoint they are configured with. MinIO in Docker is
# reachable as http://minio:9000 from the API but not from the browser, so presigned
# links are generated against the public endpoint instead.
S3_PUBLIC_ENDPOINT_URL = os.environ.get("S3_PUBLIC_ENDPOINT_URL", S3_ENDPOINT_URL).rstrip("/")
S3_ADDRESSING_STYLE = os.environ.get(
    "S3_ADDRESSING_STYLE", "path" if STORAGE_BACKEND == "minio" else "auto"
).strip().lower()
S3_CREATE_BUCKET = _flag("S3_CREATE_BUCKET", "true" if STORAGE_BACKEND == "minio" else "false")
DOWNLOAD_URL_TTL_SECONDS = int(os.environ.get("DOWNLOAD_URL_TTL_SECONDS", "120"))

OCR_ENABLED = _flag("OCR_ENABLED", "false")
ALLOW_UNSCANNED_UPLOADS = _flag("ALLOW_UNSCANNED_UPLOADS", "true" if DEBUG else "false")
CLAMAV_HOST = os.environ.get("CLAMAV_HOST", "")
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
MAX_ZIP_FILES = int(os.environ.get("MAX_ZIP_FILES", "30"))
MAX_ZIP_UNCOMPRESSED_BYTES = int(os.environ.get("MAX_ZIP_UNCOMPRESSED_BYTES", str(50 * 1024 * 1024)))
MAX_ZIP_COMPRESSION_RATIO = int(os.environ.get("MAX_ZIP_COMPRESSION_RATIO", "100"))
MAX_JD_CHARS = int(os.environ.get("MAX_JD_CHARS", "20000"))
MAX_RESUME_CHARS_TO_AI = int(os.environ.get("MAX_RESUME_CHARS_TO_AI", "20000"))

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = _flag("EMAIL_USE_TLS", "true")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "sable@localhost")
PASSWORD_RESET_URL = os.environ.get("PASSWORD_RESET_URL", "http://127.0.0.1:43123/reset-password")
INTERVIEW_JOIN_URL = os.environ.get("INTERVIEW_JOIN_URL", "http://127.0.0.1:43123/interview")
INTERVIEW_JOIN_TTL_SECONDS = int(os.environ.get("INTERVIEW_JOIN_TTL_SECONDS", str(30 * 24 * 3600)))


def _fail_prod_config() -> None:
    if DEBUG or SABLE_TESTING:
        missing = []
        if not SECRET_KEY:
            missing.append("DJANGO_SECRET_KEY")
        if not DATABASE_URL:
            missing.append("DATABASE_URL")
        if missing:
            raise RuntimeError(
                "Missing configuration: " + ", ".join(missing) + ". Copy .env.example to .env."
            )
        return
    missing = []
    if not SECRET_KEY:
        missing.append("DJANGO_SECRET_KEY")
    elif SECRET_KEY.startswith("change-me") or len(SECRET_KEY) < 32:
        missing.append("DJANGO_SECRET_KEY (must be a unique secret of at least 32 characters)")
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if not REDIS_URL:
        missing.append("REDIS_URL")
    if not ALLOWED_HOSTS:
        missing.append("ALLOWED_HOSTS")
    if AI_PROVIDER in {"", "deterministic", "dev", "test"}:
        missing.append("AI_PROVIDER=hosted (deterministic provider is debug/test only)")
    elif AI_PROVIDER == "hosted" and not AI_API_KEY:
        missing.append("AI_API_KEY")
    elif AI_PROVIDER not in {"hosted"}:
        missing.append("AI_PROVIDER (use hosted)")
    if STORAGE_BACKEND in {"s3", "minio"} and not all([S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY]):
        missing.append("S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY")
    elif STORAGE_BACKEND == "minio" and not S3_ENDPOINT_URL:
        missing.append("S3_ENDPOINT_URL (required for MinIO)")
    elif STORAGE_BACKEND not in {"s3", "minio", "local"}:
        missing.append("STORAGE_BACKEND (local, s3, or minio)")
    if S3_ADDRESSING_STYLE not in {"auto", "path", "virtual"}:
        missing.append("S3_ADDRESSING_STYLE (auto, path, or virtual)")
    if not DEBUG and EMAIL_BACKEND.endswith("smtp.EmailBackend") and not EMAIL_HOST:
        missing.append("EMAIL_HOST")
    if missing:
        raise RuntimeError(
            "Refusing to start with incomplete production configuration: " + "; ".join(missing)
        )


_fail_prod_config()

if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "be"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    "apps.common",
    "apps.accounts",
    "apps.audit",
    "apps.clients",
    "apps.candidates",
    "apps.resumes",
    "apps.jobs",
    "apps.search",
    "apps.pipeline",
    "apps.processing",
    "apps.ai",
    "apps.billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.common.middleware.RequestIdMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=60)}
DATABASES["default"]["ENGINE"] = "django.db.backends.postgresql"

AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "var" / "static"
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

if _flag("USE_LOCMEM_CACHE"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "sable"}}
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL or "redis://127.0.0.1:6379/0",
        }
    }

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        "anon": "30/min",
        "user": "240/min",
        "login": "10/min",
        "upload": "60/hour",
        "ai": "60/hour",
    },
    "EXCEPTION_HANDLER": "apps.common.exceptions.custom_exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Sable Recruitment API",
    "DESCRIPTION": "Multi-tenant recruitment CRM. Scores are decision support, not probabilities.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://127.0.0.1:43123,http://localhost:43123",
    ).split(",")
    if o.strip()
]
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "origin",
    "x-csrftoken",
    "x-request-id",
    "x-organization-id",
]
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = _flag("DJANGO_SECURE_SSL_REDIRECT", "false")

CELERY_BROKER_URL = REDIS_URL or "redis://127.0.0.1:6379/0"
CELERY_RESULT_BACKEND = REDIS_URL or "redis://127.0.0.1:6379/0"
CELERY_TASK_ALWAYS_EAGER = _flag("CELERY_TASK_ALWAYS_EAGER", "false") or SABLE_TESTING
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_TIME_LIMIT = 180
CELERY_TASK_SOFT_TIME_LIMIT = 150
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    "saved-search-notifications": {
        "task": "apps.search.tasks.notify_saved_searches",
        "schedule": 3600.0,
    },
    "retention-sweep": {
        "task": "apps.candidates.tasks.retention_sweep",
        "schedule": 86400.0,
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact": {"()": "apps.common.logging.RedactFilter"}},
    "formatters": {
        "plain": {"format": "%(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain",
            "filters": ["redact"],
        }
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
