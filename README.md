# Sable

Sable is a recruitment desk for an agency that works with more than one client company. Recruiters keep candidate files, review resume extractions, paste a job description, and rank people they are allowed to see. Client users only see candidates a recruiter has shared with their company.

The repository has two projects:

- `be/` — Django, Django REST Framework, PostgreSQL (full-text search and pgvector), Celery, Redis
- `fe/` — React, TypeScript, Vite

## Local setup

You need Python 3.12, Node 22, PostgreSQL 16 with the `vector` and `pg_trgm` extensions, and Redis.

```bash
cp .env.example .env
# Point DATABASE_URL and REDIS_URL at your local Postgres and Redis.

cd be
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python manage.py migrate
DJANGO_DEBUG=true .venv/bin/python manage.py seed_demo
```

`seed_demo` creates Northwind Search and refuses to run when `DJANGO_DEBUG` is not true.

| Email | Role | Password |
| --- | --- | --- |
| ada@sable.test | Agency admin | Harbor-Desk-19 |
| ravi@sable.test | Recruiter | Harbor-Desk-19 |
| client@sable.test | Harbour Labs client admin | Harbor-Desk-19 |
| otherclient@sable.test | Southwind Logistics client admin | Harbor-Desk-19 |

Optional synthetic file for search load tests (dev only, default 10,000 people):

```bash
cd be
DJANGO_DEBUG=true .venv/bin/python manage.py seed_load --count 10000
```

## Run the desk

Three processes. From a shell with the variables in `.env` loaded and `DJANGO_DEBUG=true`:

```bash
# API
cd be && .venv/bin/python manage.py runserver 127.0.0.1:43124

# Background parsing, embeddings, and matching
cd be && .venv/bin/celery -A config worker --loglevel=info

# UI
cd fe && npm install && npm run dev
```

Open [http://127.0.0.1:43123](http://127.0.0.1:43123). The Vite server proxies `/api` to port 43124.

For a one-command stack (Postgres with pgvector, Redis, API, worker, and the built UI):

```bash
docker compose up --build
```

The UI is published on port 43123 and the API on 43124. Set `AI_PROVIDER=deterministic` in `.env` only for local debug. Production startup rejects that provider.

## Tests

```bash
cd be && .venv/bin/python -m pytest
cd fe && npm test
cd fe && npx playwright test
```

Playwright expects the API and UI to already be running. The extraction eval harness is `be/evals/harness.py`, exercised by `be/tests/test_eval.py`.

## Recruitment workflow

- Any agency member can post a requisition and work it. Each requisition declares `interview_levels` (0–5) for the rounds after screening; the job page shows who posted it and who is assigned.
- A submission starts with an in-app screening interview that is always recorded with `mode=ui`. Screening must pass before L1 unlocks, and each level must pass in order. An offer or hire is blocked until screening and every declared level have passed.
- A client can receive submissions and shares only while it has `plan=paid` or an admin-granted `plan=free` (with `free_access_reason` recorded). Agency admins set the plan on the client page; recruiters can read it but not change it.
- `Track record` reports effort (JDs, resumes, submissions, interviews) and achievement (screening and level passes, offers, placements, ratings) from the audit trail. Agency admins see the whole desk; recruiters see their own.
- Agency admins can test the hosted model from Settings. A successful call is cached for 30 days and the screen then reports that live hosted calls have been tested.

## AI configuration

Resume parsing, job-description analysis, embeddings, match explanations, candidate summaries, and natural-language search plans go through one adapter:

`extract_resume_fields`, `analyze_job_description`, `generate_embedding`, `generate_match_explanation`, `generate_candidate_summary`, plus search interpretation.

Set `AI_PROVIDER=hosted`, `AI_API_KEY`, `AI_MODEL`, and `AI_EMBEDDING_MODEL`. The hosted adapter speaks an OpenAI-compatible chat and embeddings API (`AI_BASE_URL`, default `https://api.openai.com/v1`) and asks for JSON that matches a versioned schema. Calls have a timeout, bounded retries with jitter, a per-minute rate limit, and a concurrency cap. Usage stores provider, model, prompt version, schema version, and token counts. Keys stay in the environment. Resume text is wrapped as untrusted data and is not written to logs.

When `AI_API_KEY` is missing, the hosted adapter fails with a clear configuration error.

`AI_PROVIDER=deterministic` is a labeled local stand-in for development and tests. It is not a hosted model. It is refused when `DJANGO_DEBUG` is false. The health and settings screens say when the live provider has not been called.

This repository was exercised with the deterministic provider and with a mocked HTTP contract for the hosted adapter. A live hosted model was not called here, so this README does not claim that a particular vendor account works.

## Resume storage (MinIO)

Resumes go through one private-storage adapter. `STORAGE_BACKEND=local` writes under `be/var/media` for development. Use `minio` for self-hosted S3-compatible storage or `s3` for AWS.

MinIO is part of the Docker stack:

```bash
docker compose up -d minio
```

The API endpoint is `http://127.0.0.1:9000` and the console is `http://127.0.0.1:9001`; the compose credentials (`sable` / `sable-minio-dev`) are local placeholders and must be changed for a real deployment. MinIO publishes images on Quay; override with `MINIO_IMAGE` if your network uses a mirror. The full stack points the API and worker at `minio:9000` inside the network, while presigned download links are signed against `127.0.0.1:9000` so the browser can fetch them.

To use MinIO with the host-run API (`start.bat`), set in `.env`:

```bash
STORAGE_BACKEND=minio
S3_ENDPOINT_URL=http://127.0.0.1:9000
S3_PUBLIC_ENDPOINT_URL=http://127.0.0.1:9000
S3_BUCKET=sable-resumes
S3_ACCESS_KEY_ID=sable
S3_SECRET_ACCESS_KEY=sable-minio-dev
S3_REGION=us-east-1
S3_ADDRESSING_STYLE=path
S3_CREATE_BUCKET=true
```

`start.bat` starts the MinIO container only when `.env` selects `minio` or `s3`. MinIO needs path-style addressing, and `S3_CREATE_BUCKET=true` creates `S3_BUCKET` on first use. The API and worker must see the same bucket and keys.

With `minio` or `s3`, downloads are short-lived presigned URLs signed for `S3_PUBLIC_ENDPOINT_URL` (`DOWNLOAD_URL_TTL_SECONDS`, default 120). The link is issued only after a permission check. With `local`, the API returns a signed proxy link and re-checks permission when the bytes are sent. `/api/v1/health/` reports `storage: ok` only when the bucket is reachable.

## Production

`DJANGO_DEBUG=false` refuses to boot unless `DJANGO_SECRET_KEY` (at least 32 characters), `DATABASE_URL`, `REDIS_URL`, `ALLOWED_HOSTS`, `AI_PROVIDER=hosted`, `AI_API_KEY`, and storage settings are present. Serve the API with the Gunicorn command in `be/Dockerfile`. Put the built frontend behind a proxy that forwards `/api/` and allows resume uploads (the sample nginx config allows 20 MB).

Use private object storage (`STORAGE_BACKEND=minio` or `s3` with `S3_ENDPOINT_URL` when self-hosted, `S3_BUCKET`, and keys). Downloads are short-lived signed URLs; the local backend falls back to a signed proxy link.

Set `CLAMAV_HOST` so uploads are scanned. Without it, production rejects unscanned files unless `ALLOW_UNSCANNED_UPLOADS=true`. Set `OCR_ENABLED=true` only where Tesseract and Poppler are installed; scanned images are otherwise refused.

Run Celery workers and beat. Beat checks saved-search notifications hourly and retention daily.

## Backup and recovery

Postgres is the system of record. Take logical backups with `pg_dump` and store them with the private resume bucket (or the local media directory in development). With MinIO, mirror `S3_BUCKET` with `mc mirror` to a separate volume or bucket. Restore the database, then restore object keys to the same paths recorded on `ResumeDocument`. Redis holds queues and cache only; it does not need to be restored for correctness. After a restore, run `manage.py migrate` before serving traffic.

Retention deletes a candidate only after a deletion request is older than the organization’s `retention_days`. Preview with `POST /api/v1/admin/retention/` and `"dry_run": true`.

## Privacy

Access is role-based and limited to one organization. Client users see a candidate only through an active share, and only the contact details, compensation, and resume that share includes. Recruiter-private notes are separate from client-visible feedback. Ranking does not use protected characteristics. Scores are decision support (`sable-score-v1`), not probabilities and not hiring decisions. Consent records and an audit log cover shares, downloads, and deletions. The product is built with India’s DPDP Act in mind: state a purpose, record consent, minimize what a client receives, and delete on request after the retention window.

## API

JSON lives under `/api/v1/`. Interactive docs are at `/api/docs/`. Errors use `{ "error": { "code", "message", "details" } }`.

## Known limitations

- The hosted model path is implemented and covered by a mocked contract test. It has not been called against a live account in this environment.
- `.doc` text extraction depends on `antiword`. Broken or unusual Word files fail the parse and can be retried or corrected by hand.
- Name-only duplicate hints never merge records. Email, phone, and LinkedIn collisions block confirm until a person acknowledges them.
- Client users can reject a submission or place it on hold. Other stage changes stay with the agency.
- The deterministic provider extracts from headings and patterns. It will miss unusual layouts that a hosted model might read, and it must not be described as that model.
