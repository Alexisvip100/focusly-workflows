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


def generate_avatar_upload_url(user_id: str, content_type: str) -> dict[str, str]:
    if content_type not in ALLOWED_AVATAR_CONTENT_TYPES:
        raise ValueError(
            f"Content type '{content_type}' not allowed for avatars "
            f"(allowed: {', '.join(sorted(ALLOWED_AVATAR_CONTENT_TYPES))})"
        )

    extension = content_type.split("/")[-1]
    object_key = f"{user_id}/{uuid.uuid4()}.{extension}"
    bucket = settings.MINIO_BUCKET_AVATARS

    upload_url = s3_public_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": bucket,
            "Key": object_key,
            "ContentType": content_type,
        },
        ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
    )

    public_url = f"{settings.MINIO_PUBLIC_ENDPOINT}/{bucket}/{object_key}"

    return {"upload_url": upload_url, "public_url": public_url}
