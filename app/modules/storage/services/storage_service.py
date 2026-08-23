import json
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import settings

ALLOWED_AVATAR_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
PRESIGNED_URL_EXPIRY_SECONDS = 300

s3_client = boto3.client(
    "s3",
    endpoint_url=settings.MINIO_ENDPOINT,
    aws_access_key_id=settings.MINIO_ROOT_USER,
    aws_secret_access_key=settings.MINIO_ROOT_PASSWORD,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)

# SigV4 signs the Host header, so a presigned URL must be generated against
# the same host the browser will actually call — the container-internal
# MINIO_ENDPOINT (e.g. "minio:9000") isn't reachable from outside Docker.
s3_public_client = boto3.client(
    "s3",
    endpoint_url=settings.MINIO_PUBLIC_ENDPOINT,
    aws_access_key_id=settings.MINIO_ROOT_USER,
    aws_secret_access_key=settings.MINIO_ROOT_PASSWORD,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)


def ensure_avatars_bucket_ready() -> None:
    """Idempotently create the avatars bucket and mark it public-read-only.
    Safe to call on every app startup — mirrors the existing
    `Base.metadata.create_all` pattern in app/main.py's lifespan.

    CORS is NOT configured here: MinIO doesn't implement the standard S3
    `PutBucketCors` REST API that boto3 calls, nor does `mc cors set` work on
    current MinIO releases — both return "NotImplemented". CORS is instead
    configured server-wide via the MINIO_API_CORS_ALLOW_ORIGIN env var on the
    minio service in docker-compose.yml.
    """
    bucket = settings.MINIO_BUCKET_AVATARS

    try:
        s3_client.head_bucket(Bucket=bucket)
    except ClientError:
        s3_client.create_bucket(Bucket=bucket)

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


def resolve_avatar_url(picture: str | None) -> str | None:
    """Expand a stored `picture` value into something a browser can load.

    `picture` may be an absolute external URL (a Google profile photo, set
    once at account creation and never touched by us) or a bare MinIO object
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
    return f"{settings.MINIO_PUBLIC_ENDPOINT}/{settings.MINIO_BUCKET_AVATARS}/{picture}"


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
