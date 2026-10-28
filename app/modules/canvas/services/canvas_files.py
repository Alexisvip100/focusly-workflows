import re

from app.config import settings
from app.modules.storage.services.storage_service import (
    s3_client,
    s3_public_client,
)

# Images pasted into a canvas live in object storage, not in the canvas row:
# a single photo is megabytes, and the scene is rewritten on every autosave.
# The row keeps only which files a scene uses; their bytes go straight
# between the browser and the bucket, through short-lived signed links.

ALLOWED_CANVAS_FILE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_CANVAS_FILE_BYTES = 10 * 1024 * 1024
UPLOAD_URL_EXPIRY_SECONDS = 300
READ_URL_EXPIRY_SECONDS = 3600

# Excalidraw's file ids: a content hash or a nanoid
_FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def is_canvas_file_id(file_id: str) -> bool:
    return bool(_FILE_ID_RE.fullmatch(file_id))


def _prefix(user_id: str, canvas_id: str) -> str:
    return f"canvas/{user_id}/{canvas_id}/"


def canvas_file_key(user_id: str, canvas_id: str, file_id: str) -> str:
    if not is_canvas_file_id(file_id):
        raise ValueError(f"Invalid canvas file id: {file_id!r}")
    return _prefix(user_id, canvas_id) + file_id


def generate_canvas_file_upload_url(
    user_id: str, canvas_id: str, file_id: str, mime_type: str, size: int
) -> str:
    """A signed PUT for one image of a canvas. Its type and exact size are
    part of the signature, so the browser can't upload anything else."""
    if mime_type not in ALLOWED_CANVAS_FILE_TYPES:
        raise ValueError(
            f"Image type '{mime_type}' can't be saved in a canvas "
            f"(allowed: {', '.join(sorted(ALLOWED_CANVAS_FILE_TYPES))})"
        )
    if size <= 0 or size > MAX_CANVAS_FILE_BYTES:
        raise ValueError(
            f"Canvas images can be up to {MAX_CANVAS_FILE_BYTES // (1024 * 1024)} MB"
        )
    return s3_public_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.MINIO_BUCKET_CANVAS,
            "Key": canvas_file_key(user_id, canvas_id, file_id),
            "ContentType": mime_type,
            "ContentLength": size,
        },
        ExpiresIn=UPLOAD_URL_EXPIRY_SECONDS,
    )


def generate_canvas_file_read_url(
    user_id: str, canvas_id: str, file_id: str
) -> str:
    return s3_public_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.MINIO_BUCKET_CANVAS,
            "Key": canvas_file_key(user_id, canvas_id, file_id),
        },
        ExpiresIn=READ_URL_EXPIRY_SECONDS,
    )


def _delete_prefix(prefix: str) -> None:
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(
        Bucket=settings.MINIO_BUCKET_CANVAS, Prefix=prefix
    ):
        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if keys:
            s3_client.delete_objects(
                Bucket=settings.MINIO_BUCKET_CANVAS,
                Delete={"Objects": keys, "Quiet": True},
            )


def delete_canvas_files(user_id: str, canvas_id: str) -> None:
    """Best-effort: every image of one canvas. Storage being down must not
    fail the deletion of the canvas itself."""
    try:
        _delete_prefix(_prefix(user_id, canvas_id))
    except Exception:
        pass


def delete_user_canvas_files(user_id: str) -> None:
    """Best-effort: every canvas image of a user, on account deletion."""
    if not user_id:
        return
    try:
        _delete_prefix(f"canvas/{user_id}/")
    except Exception:
        pass
