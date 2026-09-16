import uuid
from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings


def _client():
    """Build a boto3 S3 client.

    S3_ENDPOINT_URL lets development and tests use an S3-compatible service
    instead of real AWS S3.
    """
    return boto3.client(
        "s3",
        region_name=settings.AWS_REGION,
        endpoint_url=settings.S3_ENDPOINT_URL or None,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        aws_session_token=settings.AWS_SESSION_TOKEN,
    )


def build_s3_key(project_id: uuid.UUID, document_id: uuid.UUID, file_name: str) -> str:
    """Namespace every object under its project and document id."""
    return f"projects/{project_id}/documents/{document_id}/{file_name}"


def project_storage_size(project_id: uuid.UUID) -> int:
    """Return the total number of bytes currently stored for a project."""
    prefix = f"projects/{project_id}/"
    total = 0
    paginator = _client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.S3_BUCKET_NAME, Prefix=prefix):
        for obj in page.get("Contents", []):
            total += int(obj.get("Size", 0))
    return total


def upload_file(s3_key: str, fileobj: BinaryIO, content_type: str) -> None:
    _client().upload_fileobj(
        fileobj,
        settings.S3_BUCKET_NAME,
        s3_key,
        ExtraArgs={"ContentType": content_type},
    )


def download_file(s3_key: str) -> tuple[bytes, str]:
    """Returns (raw bytes, content_type). Raises FileNotFoundError if missing."""
    try:
        obj = _client().get_object(Bucket=settings.S3_BUCKET_NAME, Key=s3_key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            raise FileNotFoundError(s3_key) from e
        raise
    return obj["Body"].read(), obj.get("ContentType", "application/octet-stream")


def delete_file(s3_key: str) -> None:
    """Deleting a nonexistent key is a no-op in S3."""
    _client().delete_object(Bucket=settings.S3_BUCKET_NAME, Key=s3_key)
