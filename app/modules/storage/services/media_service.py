import re
import threading
import time

from app.config import settings
from app.modules.storage.services.storage_service import s3_public_client

# The public site's loop videos and their posters, kept in the media bucket
# under this prefix. The bucket stays private: browsers get a signed link.
MEDIA_PREFIX = "media/videos/"

# Only names the site uses ("tasks-hero-light.webm", "...-poster.webp"), so
# the endpoint can't be used to read any other object in the bucket.
_FILENAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.(?:webm|mp4|webp)$")

# A signed link is reused for a whole window: SigV4 stamps the signing time
# into the URL, so signing on every request would give each visit a new URL
# and defeat the browser cache. One entry per file per process.
_cache: dict[str, tuple[int, str]] = {}
_lock = threading.Lock()


def is_media_filename(filename: str) -> bool:
    return bool(_FILENAME_RE.fullmatch(filename))


def get_media_url(filename: str, now: float | None = None) -> tuple[str, int]:
    """Signed GET link for a site video and the seconds a browser may cache it.

    The link is the same for every request in the current window and stays
    valid one window past its end, so a tab that cached it near the end of a
    window can still (re)load the file.
    """
    if not is_media_filename(filename):
        raise ValueError(f"Invalid media file name: {filename!r}")

    # A link lives up to two windows and SigV4 caps links at 7 days.
    window = min(max(60, settings.MEDIA_URL_WINDOW_SECONDS), 3 * 24 * 3600)
    now = time.time() if now is None else now
    window_id = int(now // window)
    window_end = (window_id + 1) * window
    cache_seconds = max(1, int(window_end - now))

    with _lock:
        cached = _cache.get(filename)
        if cached and cached[0] == window_id:
            return cached[1], cache_seconds

        url = s3_public_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.MINIO_BUCKET_MEDIA,
                "Key": MEDIA_PREFIX + filename,
            },
            ExpiresIn=cache_seconds + window,
        )
        _cache[filename] = (window_id, url)
        return url, cache_seconds
