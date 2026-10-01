import json
import time
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, EndpointConnectionError

from app.config import settings

ALLOWED_AVATAR_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
PRESIGNED_URL_EXPIRY_SECONDS = 300

_region = "auto" if "storageapi.dev" in settings.MINIO_ENDPOINT else "us-east-1"

s3_client = boto3.client(
    "s3",
    endpoint_url=settings.MINIO_ENDPOINT,
    aws_access_key_id=settings.MINIO_ROOT_USER,
    aws_secret_access_key=settings.MINIO_ROOT_PASSWORD,
    config=Config(signature_version="s3v4"),
    region_name=_region,
)

# SigV4 signs the Host header, so a presigned URL must be generated against
# the host the browser will actually call.
# In local dev: internal MINIO_ENDPOINT ("minio:9000") is not reachable from host, so we use MINIO_PUBLIC_ENDPOINT ("localhost:9000").
# In production with cloud S3 (Tigris/AWS): MINIO_ENDPOINT ("https://...") is directly reachable by both backend and browser.
_upload_endpoint = (
    settings.MINIO_ENDPOINT
    if settings.MINIO_ENDPOINT.startswith("https://")
    else settings.MINIO_PUBLIC_ENDPOINT
)

s3_public_client = boto3.client(
    "s3",
    endpoint_url=_upload_endpoint,
    aws_access_key_id=settings.MINIO_ROOT_USER,
    aws_secret_access_key=settings.MINIO_ROOT_PASSWORD,
    config=Config(signature_version="s3v4"),
    region_name=_region,
)


def ensure_avatars_bucket_ready(
    max_attempts: int = 5, retry_delay_seconds: float = 2.0
) -> None:
    """Idempotently create the avatars bucket and mark it public-read-only.
    Safe to call on every app startup — mirrors the existing
    `Base.metadata.create_all` pattern in app/main.py's lifespan.

    Retries on connection errors: `minio` isn't in this service's
    `depends_on` in docker-compose.yml (it's a soft dependency — only the
    avatar feature needs it, not the rest of the API), and even where a
    `depends_on` exists, that only waits for the container to start, not for
    MinIO to actually be accepting connections yet. Without a retry, a cold
    `docker compose up` or host reboot can hit this before MinIO is ready and
    crash the whole app on startup. The caller (app/main.py's lifespan) also
    treats a final failure here as non-fatal, so the rest of the API still
    comes up even if MinIO never becomes reachable.

    CORS is NOT configured here: MinIO doesn't implement the standard S3
    `PutBucketCors` REST API that boto3 calls, nor does `mc cors set` work on
    current MinIO releases — both return "NotImplemented". CORS is instead
    configured server-wide via the MINIO_API_CORS_ALLOW_ORIGIN env var on the
    minio service in docker-compose.yml.
    """
    if not settings.MINIO_ROOT_USER:
        return

    bucket = settings.MINIO_BUCKET_AVATARS

    for attempt in range(1, max_attempts + 1):
        try:
            try:
                s3_client.head_bucket(Bucket=bucket)
            except ClientError:
                s3_client.create_bucket(Bucket=bucket)

            try:
                s3_client.put_bucket_policy(
                    Bucket=bucket,
                    Policy=json.dumps(
                        {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Principal": "*",
                                    "Action": ["s3:GetObject"],
                                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                                }
                            ],
                        }
                    ),
                )
            except Exception:
                # Tigris and some S3 providers don't implement put_bucket_policy
                pass
            return
        except EndpointConnectionError:
            if attempt == max_attempts:
                raise
            time.sleep(retry_delay_seconds)


def resolve_avatar_url(picture: str | None) -> str | None:
    """Expand a stored `picture` value into something a browser can load.

    `picture` may be an absolute external URL (a Google profile photo, set
    once at account creation and never touched by us) or a bare MinIO/S3 object
    key (e.g. "{user_id}/{uuid}.png") — only the DB, never the storage host,
    should be the source of truth for which user owns which object, so we
    keep the stored value host-agnostic and expand it here, at the one place
    every API response flows through, instead of baking MINIO_PUBLIC_ENDPOINT
    into the database.
    """
    if not picture:
        return picture
    if picture.startswith("http://") or picture.startswith("https://"):
        return picture

    endpoint = settings.MINIO_PUBLIC_ENDPOINT.rstrip("/")
    if endpoint.endswith("/uploads/avatar"):
        return f"{endpoint}/{picture}"
    if "storageapi.dev" in settings.MINIO_ENDPOINT or "railway.app" in endpoint:
        return f"{endpoint}/uploads/avatar/{picture}"

    return f"{endpoint}/{settings.MINIO_BUCKET_AVATARS}/{picture}"


def get_avatar_object(object_key: str) -> tuple[bytes, str] | None:
    """Fetch avatar image bytes and content type from storage.
    Returns (bytes, content_type) or None if not found.
    """
    try:
        response = s3_client.get_object(
            Bucket=settings.MINIO_BUCKET_AVATARS,
            Key=object_key,
        )
        content_type = response.get("ContentType", "image/jpeg")
        body = response["Body"].read()
        return body, content_type
    except Exception:
        return None


def generate_avatar_upload_url(user_id: str, content_type: str) -> dict[str, str]:
    if content_type not in ALLOWED_AVATAR_CONTENT_TYPES:
        raise ValueError(
            f"Content type '{content_type}' not allowed for avatars "
            f"(allowed: {', '.join(sorted(ALLOWED_AVATAR_CONTENT_TYPES))})"
        )

    extension = content_type.split("/")[-1]
    object_key = f"{user_id}/{uuid.uuid4()}.{extension}"

    upload_url = s3_public_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.MINIO_BUCKET_AVATARS,
            "Key": object_key,
            "ContentType": content_type,
        },
        ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
    )

    return {
        "upload_url": upload_url,
        # The key is what gets persisted in the DB (host-agnostic); the
        # preview URL is only for the frontend to render an immediate
        # preview before the profile is actually saved.
        "object_key": object_key,
        "preview_url": resolve_avatar_url(object_key),
    }


def delete_avatar_object(object_key: str) -> None:
    """Best-effort delete of a replaced avatar. Never call with an absolute
    URL (e.g. a Google photo) — only with a bare object key we own.
    """
    try:
        s3_client.delete_object(
            Bucket=settings.MINIO_BUCKET_AVATARS, Key=object_key
        )
    except ClientError:
        pass
