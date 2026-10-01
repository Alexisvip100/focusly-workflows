from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app.main import fastapi_app
from app.modules.storage.services.storage_service import (
    resolve_avatar_url,
    generate_avatar_upload_url,
    get_avatar_object,
    delete_avatar_object,
    ensure_avatars_bucket_ready,
)

client = TestClient(fastapi_app)


def test_resolve_avatar_url():
    # None or empty
    assert resolve_avatar_url(None) is None
    assert resolve_avatar_url("") == ""

    # External URLs (Google OAuth etc.)
    assert (
        resolve_avatar_url("https://lh3.googleusercontent.com/photo.jpg")
        == "https://lh3.googleusercontent.com/photo.jpg"
    )
    assert (
        resolve_avatar_url("http://example.com/pic.png")
        == "http://example.com/pic.png"
    )

    # Relative key with standard endpoint
    with patch(
        "app.modules.storage.services.storage_service.settings.MINIO_ENDPOINT",
        "http://localhost:9000",
    ), patch(
        "app.modules.storage.services.storage_service.settings.MINIO_PUBLIC_ENDPOINT",
        "http://localhost:9000",
    ), patch(
        "app.modules.storage.services.storage_service.settings.MINIO_BUCKET_AVATARS",
        "avatars",
    ):
        assert (
            resolve_avatar_url("user1/avatar.png")
            == "http://localhost:9000/avatars/user1/avatar.png"
        )

    # Cloud S3 / Railway production endpoint routing
    with patch(
        "app.modules.storage.services.storage_service.settings.MINIO_ENDPOINT",
        "https://t3.storageapi.dev",
    ), patch(
        "app.modules.storage.services.storage_service.settings.MINIO_PUBLIC_ENDPOINT",
        "https://focusly-workflows-production.up.railway.app",
    ):
        assert (
            resolve_avatar_url("user1/avatar.png")
            == "https://focusly-workflows-production.up.railway.app/uploads/avatar/user1/avatar.png"
        )


def test_generate_avatar_upload_url():
    with patch(
        "app.modules.storage.services.storage_service.s3_public_client.generate_presigned_url"
    ) as mock_presign:
        mock_presign.return_value = "https://t3.storageapi.dev/bucket/presigned-url"
        result = generate_avatar_upload_url("user-123", "image/png")

        assert result["upload_url"] == "https://t3.storageapi.dev/bucket/presigned-url"
        assert result["object_key"].startswith("user-123/")
        assert result["object_key"].endswith(".png")


def test_get_avatar_object():
    with patch(
        "app.modules.storage.services.storage_service.s3_client.get_object"
    ) as mock_get:
        mock_body = MagicMock()
        mock_body.read.return_value = b"fake-png-bytes"
        mock_get.return_value = {
            "ContentType": "image/png",
            "Body": mock_body,
        }

        res = get_avatar_object("user-123/file.png")
        assert res is not None
        body, ctype = res
        assert body == b"fake-png-bytes"
        assert ctype == "image/png"


def test_get_avatar_route_success():
    with patch(
        "app.modules.storage.routes.get_avatar_object"
    ) as mock_get_avatar:
        mock_get_avatar.return_value = (b"image-data", "image/jpeg")

        response = client.get("/uploads/avatar/user-123/test.jpg")
        assert response.status_code == 200
        assert response.content == b"image-data"
        assert response.headers["content-type"] == "image/jpeg"
        assert "immutable" in response.headers.get("cache-control", "")


def test_get_avatar_route_not_found():
    with patch(
        "app.modules.storage.routes.get_avatar_object"
    ) as mock_get_avatar:
        mock_get_avatar.return_value = None

        response = client.get("/uploads/avatar/user-123/missing.jpg")
        assert response.status_code == 404


def test_get_avatar_route_path_traversal():
    response = client.get("/uploads/avatar/..%2Fuser/test.jpg")
    assert response.status_code in (400, 404)


def test_ensure_avatars_bucket_ready_handles_tigris_policy_gracefully():
    with patch(
        "app.modules.storage.services.storage_service.settings.MINIO_ROOT_USER",
        "some-user",
    ), patch(
        "app.modules.storage.services.storage_service.s3_client.head_bucket"
    ) as mock_head, patch(
        "app.modules.storage.services.storage_service.s3_client.put_bucket_policy"
    ) as mock_policy:
        mock_policy.side_effect = ClientError(
            {"Error": {"Code": "NotImplemented", "Message": "Unknown command"}},
            "PutBucketPolicy",
        )

        # Should not raise exception
        ensure_avatars_bucket_ready(max_attempts=1)
        mock_head.assert_called_once()
        mock_policy.assert_called_once()
