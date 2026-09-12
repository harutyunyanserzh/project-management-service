"""AWS Lambda function triggered by S3 ObjectCreated events.

Responsibility (per project spec): "calculation of sum of project file's
size and apply limit". On every new upload, this function:

1. Parses the project id out of the object's key (keys are namespaced as
   projects/{project_id}/documents/{document_id}/{filename} by the app's
   storage service -- see app/services/storage.py).
2. Sums the size of every object under that project's prefix.
3. If the total exceeds MAX_PROJECT_STORAGE_BYTES, deletes the object that
   was just uploaded (the one that pushed the project over the limit) and
   logs why.

This intentionally does NOT talk to the application's Postgres database --
Lambda functions in a default (non-VPC) configuration cannot reach a
database sitting behind a VPC/security group without extra networking
setup, which is out of scope here. The enforcement lives entirely at the
storage layer: if a Lambda deletes the object, a subsequent
GET /document/{id} download will simply 404, and the corresponding
DB row can be cleaned up via a periodic reconciliation job or accepted as
an inconsistency documented in the README for this iteration.
"""

import logging
import os
import re
from urllib.parse import unquote_plus

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

MAX_PROJECT_STORAGE_BYTES = int(os.environ.get("MAX_PROJECT_STORAGE_BYTES", 100 * 1024 * 1024))

KEY_PATTERN = re.compile(r"^projects/(?P<project_id>[^/]+)/documents/")


def _project_prefix_from_key(key: str) -> str | None:
    match = KEY_PATTERN.match(key)
    if not match:
        return None
    return f"projects/{match.group('project_id')}/"


def _sum_prefix_size(bucket: str, prefix: str) -> int:
    total = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            total += obj["Size"]
    return total


def handler(event, context=None):
    results = []

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])

        prefix = _project_prefix_from_key(key)
        if prefix is None:
            logger.warning("Key %s does not match expected project layout; skipping", key)
            continue

        total_bytes = _sum_prefix_size(bucket, prefix)
        logger.info(
            "Project prefix %s now totals %d bytes (limit %d)",
            prefix,
            total_bytes,
            MAX_PROJECT_STORAGE_BYTES,
        )

        if total_bytes > MAX_PROJECT_STORAGE_BYTES:
            logger.warning(
                "Project %s exceeded storage limit (%d > %d). Deleting offending object %s",
                prefix,
                total_bytes,
                MAX_PROJECT_STORAGE_BYTES,
                key,
            )
            s3.delete_object(Bucket=bucket, Key=key)
            results.append({"key": key, "action": "deleted_over_limit", "total_bytes": total_bytes})
        else:
            results.append({"key": key, "action": "ok", "total_bytes": total_bytes})

    return {"results": results}
