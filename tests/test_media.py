from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import fastapi_app
from app.modules.storage.services import media_service
from app.modules.storage.services.media_service import get_media_url, is_media_filename

client = TestClient(fastapi_app)

SIGN = (
    "app.modules.storage.services.media_service.s3_public_client.generate_presigned_url"
)
WINDOW = "app.modules.storage.services.media_service.settings.MEDIA_URL_WINDOW_SECONDS"


@pytest.fixture(autouse=True)
def clear_cache():
    media_service._cache.clear()
    yield
    media_service._cache.clear()


def test_is_media_filename():
    assert is_media_filename("tasks-hero-light.webm")
    assert is_media_filename("weekly-planner-dark-poster.webp")
    assert is_media_filename("insights-golden-dark.mp4")
    for bad in [
        "../secret.webm",
        "a/b.webm",
        "Tasks.webm",
        "x.exe",
        "x.webm.png",
        "",
        ".webm",
    ]:
        assert not is_media_filename(bad)


def test_get_media_url_reuses_the_link_within_a_window():
    with patch(WINDOW, 3600), patch(SIGN, side_effect=["signed-1", "signed-2"]) as sign:
        url1, cache1 = get_media_url("tasks-hero-light.webm", now=7200 + 100)
        url2, cache2 = get_media_url("tasks-hero-light.webm", now=7200 + 3000)
        assert (url1, url2) == ("signed-1", "signed-1")
        assert (cache1, cache2) == (3500, 600)
        assert sign.call_count == 1

        # Signed for the rest of this window plus one more
        _, kwargs = sign.call_args
        assert kwargs["ExpiresIn"] == 3500 + 3600
        assert kwargs["Params"]["Key"] == "media/videos/tasks-hero-light.webm"

        # Next window: a new link
        url3, _ = get_media_url("tasks-hero-light.webm", now=10800 + 5)
        assert url3 == "signed-2"


def test_get_media_url_rejects_other_objects():
    with pytest.raises(ValueError):
        get_media_url("../avatars/user1/avatar.png")


def test_route_redirects_to_the_signed_link():
    with patch(SIGN, return_value="https://bucket.example/media/videos/x.webm?sig=1"):
        response = client.get(
            "/media/videos/tasks-hero-light.webm", follow_redirects=False
        )
    assert response.status_code == 302
    assert (
        response.headers["location"]
        == "https://bucket.example/media/videos/x.webm?sig=1"
    )
    assert response.headers["cache-control"].startswith("public, max-age=")


def test_route_404s_for_names_outside_the_site_videos():
    with patch(SIGN) as sign:
        assert (
            client.get("/media/videos/Avatar.PNG", follow_redirects=False).status_code
            == 404
        )
        assert (
            client.get(
                "/media/videos/..%2Fsecret.webm", follow_redirects=False
            ).status_code
            == 404
        )
    sign.assert_not_called()
