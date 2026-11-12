import os

os.environ.setdefault("SABLE_TESTING", "1")
os.environ.setdefault("DJANGO_DEBUG", "true")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production-use!!")
os.environ.setdefault("DATABASE_URL", "postgres://recruit:recruit@127.0.0.1:5432/recruit")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/1")
os.environ.setdefault("AI_PROVIDER", "deterministic")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("USE_LOCMEM_CACHE", "true")
os.environ.setdefault("OCR_ENABLED", "false")
os.environ.setdefault("ALLOW_UNSCANNED_UPLOADS", "true")
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1")
