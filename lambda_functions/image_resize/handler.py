"""Optional Lambda function (per project spec: "Image resize(optional)").

Triggered by S3 ObjectCreated events. If the uploaded object is an image
(png/jpg/jpeg), generates a thumbnail and stores it alongside the original
under a `thumbnails/` prefix. Non-image objects (the pdf/docx documents this
app actually stores) are ignored -- this function is a placeholder for if
image attachments are added to the project spec later.
"""

import io
import logging
import os
from urllib.parse import unquote_plus

import boto3
from PIL import Image

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

THUMBNAIL_SIZE = (
    int(os.environ.get("THUMBNAIL_WIDTH", "256")),
    int(os.environ.get("THUMBNAIL_HEIGHT", "256")),
)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def _is_image(key: str) -> bool:
    return any(key.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)


def handler(event, context=None):
    results = []

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])

        if key.startswith("thumbnails/"):
            continue  # never re-process our own output

        if not _is_image(key):
            results.append({"key": key, "action": "skipped_not_image"})
            continue

        obj = s3.get_object(Bucket=bucket, Key=key)
        image = Image.open(io.BytesIO(obj["Body"].read()))
        image.thumbnail(THUMBNAIL_SIZE)

        buffer = io.BytesIO()
        image_format = (image.format or "PNG").upper()
        image.save(buffer, format=image_format)
        buffer.seek(0)

        thumb_key = f"thumbnails/{key}"
        s3.put_object(
            Bucket=bucket,
            Key=thumb_key,
            Body=buffer,
            ContentType=obj.get("ContentType", "application/octet-stream"),
        )
        results.append({"key": key, "action": "thumbnail_created", "thumbnail_key": thumb_key})

    return {"results": results}
