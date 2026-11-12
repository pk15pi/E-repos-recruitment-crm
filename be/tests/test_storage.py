import io
import os
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from botocore.stub import Stubber
from rest_framework.test import APIClient

from apps.common import storage as storage_module
from apps.common.storage import LocalStorage, S3Storage, StorageError, get_storage


def _minio_settings(settings, endpoint="http://127.0.0.1:9000", public=""):
    settings.STORAGE_BACKEND = "minio"
    settings.S3_ENDPOINT_URL = endpoint
    settings.S3_PUBLIC_ENDPOINT_URL = public or endpoint
    settings.S3_BUCKET = "sable-resumes"
    settings.S3_ACCESS_KEY_ID = "sable"
    settings.S3_SECRET_ACCESS_KEY = "sable-minio-dev"
    settings.S3_REGION = "us-east-1"
    settings.S3_ADDRESSING_STYLE = "path"
    settings.S3_CREATE_BUCKET = False


def test_local_storage_round_trip_and_traversal(tmp_path):
    store = LocalStorage(tmp_path)
    store.save("org/1/quarantine/1", b"hello", "text/plain")
    assert store.open("org/1/quarantine/1") == b"hello"
    store.move("org/1/quarantine/1", "org/1/clean/1")
    assert store.open("org/1/clean/1") == b"hello"
    with pytest.raises(StorageError):
        store.open("org/1/quarantine/1")
    store.delete("org/1/clean/1")
    assert store.check() is True
    with pytest.raises(StorageError):
        store.save("../escape", b"x")


def test_minio_storage_uses_path_style_and_public_endpoint(settings):
    _minio_settings(settings, public="http://localhost:9000")
    store = S3Storage()
    assert store.client.meta.endpoint_url == "http://127.0.0.1:9000"
    assert store.client.meta.config.s3 == {"addressing_style": "path"}
    assert store.public_client.meta.endpoint_url == "http://localhost:9000"

    url = store.presigned_url(
        "org/1/quarantine/1", 60, "resume.pdf", inline=True, content_type="application/pdf"
    )
    parsed = urlparse(url)
    assert parsed.netloc == "localhost:9000"
    assert parsed.path == "/sable-resumes/org/1/quarantine/1"
    query = parse_qs(parsed.query)
    assert query["X-Amz-Signature"]
    assert query["X-Amz-Expires"] == ["60"]
    assert query["response-content-disposition"] == ['inline; filename="resume.pdf"']
    assert query["response-content-type"] == ["application/pdf"]


def test_minio_bucket_is_created_when_missing(settings):
    _minio_settings(settings)
    store = S3Storage()
    stubber = Stubber(store.client)
    stubber.add_client_error(
        "head_bucket", service_error_code="404", http_status_code=404, expected_params={"Bucket": "sable-resumes"}
    )
    stubber.add_response("create_bucket", {}, {"Bucket": "sable-resumes"})
    with stubber:
        store.ensure_bucket()
    stubber.assert_no_pending_responses()


def test_existing_bucket_is_not_recreated(settings):
    _minio_settings(settings)
    store = S3Storage()
    stubber = Stubber(store.client)
    stubber.add_response("head_bucket", {}, {"Bucket": "sable-resumes"})
    with stubber:
        store.ensure_bucket()
    stubber.assert_no_pending_responses()


def test_minio_object_operations(settings):
    _minio_settings(settings)
    store = S3Storage()
    stubber = Stubber(store.client)
    stubber.add_response(
        "put_object",
        {},
        {"Bucket": "sable-resumes", "Key": "org/1/clean/1", "Body": b"resume-bytes", "ContentType": "application/pdf"},
    )
    stubber.add_response(
        "get_object",
        {"Body": io.BytesIO(b"resume-bytes")},
        {"Bucket": "sable-resumes", "Key": "org/1/clean/1"},
    )
    stubber.add_response(
        "copy_object",
        {},
        {
            "Bucket": "sable-resumes",
            "CopySource": {"Bucket": "sable-resumes", "Key": "org/1/quarantine/1"},
            "Key": "org/1/clean/1",
        },
    )
    stubber.add_response(
        "delete_object", {}, {"Bucket": "sable-resumes", "Key": "org/1/quarantine/1"}
    )
    with stubber:
        store.save("org/1/clean/1", b"resume-bytes", "application/pdf")
        assert store.open("org/1/clean/1") == b"resume-bytes"
        store.move("org/1/quarantine/1", "org/1/clean/1")
    stubber.assert_no_pending_responses()


def test_missing_object_maps_to_storage_error(settings):
    _minio_settings(settings)
    store = S3Storage()
    stubber = Stubber(store.client)
    stubber.add_client_error(
        "get_object",
        service_error_code="NoSuchKey",
        http_status_code=404,
        expected_params={"Bucket": "sable-resumes", "Key": "gone"},
    )
    with stubber:
        with pytest.raises(StorageError):
            store.open("gone")


def test_check_reports_unreachable_bucket(settings):
    _minio_settings(settings)
    store = S3Storage()
    stubber = Stubber(store.client)
    stubber.add_client_error(
        "head_bucket", service_error_code="AccessDenied", http_status_code=403, expected_params={"Bucket": "sable-resumes"}
    )
    with stubber:
        assert store.check() is False


def test_get_storage_selects_minio(settings):
    _minio_settings(settings)
    assert isinstance(get_storage(), S3Storage)
    settings.STORAGE_BACKEND = "local"
    settings.STORAGE_LOCAL_ROOT = settings.STORAGE_LOCAL_ROOT
    assert isinstance(get_storage(), LocalStorage)


def test_health_reports_storage_failure(monkeypatch, settings, db):
    settings.STORAGE_BACKEND = "local"

    class BrokenStorage:
        def check(self):
            return False

    monkeypatch.setattr(storage_module, "get_storage", lambda: BrokenStorage())
    response = APIClient().get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json()["checks"]["storage"] == "error"


def test_minio_download_issues_presigned_url(monkeypatch, settings, agency, db):
    import apps.resumes.api as resumes_api
    from apps.resumes.models import ResumeDocument
    from tests.conftest import login

    settings.STORAGE_BACKEND = "minio"
    resume = ResumeDocument.objects.create(
        organization=agency["org"],
        uploaded_by=agency["admin"],
        original_filename="Asha Rao.pdf",
        content_type="application/pdf",
        byte_size=10,
        sha256="a" * 64,
        storage_key="org/1/clean/1",
        status=ResumeDocument.Status.CONFIRMED,
    )

    class FakeStorage:
        def presigned_url(self, key, expires, filename, inline=False, content_type=None):
            return f"http://127.0.0.1:9000/sable/{key}?inline={inline}&type={content_type}&ttl={expires}"

    monkeypatch.setattr(resumes_api, "get_storage", lambda: FakeStorage())
    api = APIClient()
    login(api, "ada@sable.test")
    response = api.post(f"/api/v1/resumes/{resume.id}/download/", {"disposition": "inline"}, format="json")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "presigned"
    assert body["url"].startswith("http://127.0.0.1:9000/sable/")
    assert "inline=True" in body["url"]
    assert "type=application/pdf" in body["url"]


@pytest.mark.skipif(not os.environ.get("MINIO_TEST_URL"), reason="MINIO_TEST_URL is not set")
def test_live_minio_round_trip(settings):
    endpoint = os.environ["MINIO_TEST_URL"]
    _minio_settings(settings, endpoint=endpoint)
    settings.S3_BUCKET = os.environ.get("MINIO_TEST_BUCKET", "sable-resumes-test")
    settings.S3_CREATE_BUCKET = True
    store = S3Storage()
    assert store.check() is True
    store.ensure_bucket()
    payload = b"%PDF-1.7 live minio check"
    store.save("org/1/quarantine/live", payload, "application/pdf")
    assert store.open("org/1/quarantine/live") == payload
    url = store.presigned_url("org/1/quarantine/live", 60, "resume.pdf", inline=True, content_type="application/pdf")
    response = requests.get(url, timeout=10)
    assert response.status_code == 200
    assert response.content == payload
    assert 'inline; filename="resume.pdf"' in response.headers["Content-Disposition"]
    store.move("org/1/quarantine/live", "org/1/clean/live")
    assert store.open("org/1/clean/live") == payload
    with pytest.raises(StorageError):
        store.open("org/1/quarantine/live")
    store.delete("org/1/clean/live")
    with pytest.raises(StorageError):
        store.open("org/1/clean/live")
