"""Private object storage. Local filesystem in development, S3-compatible (MinIO or S3) in production."""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

_MISSING_BUCKET_CODES = {"404", "NoSuchBucket", "NotFound"}


class StorageError(Exception):
    pass


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        clean = key.replace("\\", "/").lstrip("/")
        if ".." in clean.split("/"):
            raise StorageError("Invalid storage key.")
        path = (self.root / clean).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise StorageError("Invalid storage key.")
        return path

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def open(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise StorageError("Stored object is missing.")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def move(self, src: str, dest: str) -> None:
        data = self.open(src)
        self.save(dest, data)
        self.delete(src)

    def check(self) -> bool:
        return self.root.is_dir()


class S3Storage:
    """S3 API client that also speaks MinIO.

    MinIO is addressed path-style (``http://host:9000/bucket/key``) and its bucket is
    created on demand in development. Presigned links are signed against
    ``S3_PUBLIC_ENDPOINT_URL`` so a browser can reach MinIO inside Docker.
    """

    def __init__(self, client=None, *, ensure_bucket: bool | None = None):
        if not all([settings.S3_BUCKET, settings.S3_ACCESS_KEY_ID, settings.S3_SECRET_ACCESS_KEY]):
            raise StorageError("S3 storage is selected but the bucket or credentials are missing.")
        if settings.STORAGE_BACKEND == "minio" and not settings.S3_ENDPOINT_URL:
            raise StorageError("MinIO storage is selected but S3_ENDPOINT_URL is empty.")
        self.bucket = settings.S3_BUCKET
        self.endpoint_url = settings.S3_ENDPOINT_URL
        self.client = client if client is not None else self._build_client(self.endpoint_url)
        public_endpoint = settings.S3_PUBLIC_ENDPOINT_URL
        self.public_client = (
            self.client
            if not self.endpoint_url or public_endpoint == self.endpoint_url
            else self._build_client(public_endpoint)
        )
        if ensure_bucket is None:
            ensure_bucket = settings.S3_CREATE_BUCKET
        if ensure_bucket:
            self.ensure_bucket()

    def _build_client(self, endpoint_url: str):
        import boto3
        from botocore.config import Config

        return boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            region_name=settings.S3_REGION,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": settings.S3_ADDRESSING_STYLE},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
            ),
        )

    def ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket)
            return
        except ClientError as exc:
            if not _is_missing_bucket(exc):
                raise StorageError("Could not reach the object storage bucket.") from exc
        kwargs = {"Bucket": self.bucket}
        if settings.S3_REGION and settings.S3_REGION != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": settings.S3_REGION}
        try:
            self.client.create_bucket(**kwargs)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise StorageError("Could not create the object storage bucket.") from exc
        logger.info("Created object storage bucket %s", self.bucket)

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def open(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _is_missing_object(exc):
                raise StorageError("Stored object is missing.") from exc
            raise StorageError("Could not read the stored object.") from exc
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def move(self, src: str, dest: str) -> None:
        self.client.copy_object(Bucket=self.bucket, CopySource={"Bucket": self.bucket, "Key": src}, Key=dest)
        self.delete(src)

    def presigned_url(
        self, key: str, expires: int, filename: str, inline: bool = False, content_type: str | None = None
    ) -> str:
        disposition = "inline" if inline else "attachment"
        params = {
            "Bucket": self.bucket,
            "Key": key,
            "ResponseContentDisposition": f'{disposition}; filename="{filename}"',
        }
        if content_type:
            params["ResponseContentType"] = content_type
        return self.public_client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires)

    def check(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


def _is_missing_bucket(exc) -> bool:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    status = str(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
    return code in _MISSING_BUCKET_CODES or status == "404"


def _is_missing_object(exc) -> bool:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    return code in {"NoSuchKey", "404", "NotFound"}


def get_storage():
    if settings.STORAGE_BACKEND in {"s3", "minio"}:
        return S3Storage()
    return LocalStorage(settings.STORAGE_LOCAL_ROOT)
