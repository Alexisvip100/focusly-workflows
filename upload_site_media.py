"""Upload the public site's loop videos to the media bucket.

The files come from focusly-front's public/videos folder (generated there)
and go under media/videos/ in MINIO_BUCKET_MEDIA, where GET /media/videos/
serves them from. Each gets its Content-Type and a year of caching, so a
regenerated video needs a new name (e.g. "-v2") or browsers keep the old one.

Uses this service's storage settings (MINIO_ENDPOINT, MINIO_ROOT_USER, ...):
run it with the production variables to fill the production bucket.

Usage: python upload_site_media.py ../focusly-front/public/videos
"""

import mimetypes
import os
import sys

# Add the current directory to sys.path to allow imports from app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.config import settings
from app.modules.storage.services.media_service import MEDIA_PREFIX, is_media_filename
from app.modules.storage.services.storage_service import s3_client

CONTENT_TYPES = {".webm": "video/webm", ".mp4": "video/mp4", ".webp": "image/webp"}


def upload(folder: str) -> int:
    bucket = settings.MINIO_BUCKET_MEDIA
    names = sorted(n for n in os.listdir(folder) if is_media_filename(n))
    for i, name in enumerate(names, 1):
        ext = os.path.splitext(name)[1]
        s3_client.upload_file(
            os.path.join(folder, name),
            bucket,
            MEDIA_PREFIX + name,
            ExtraArgs={
                "ContentType": CONTENT_TYPES.get(ext)
                or mimetypes.guess_type(name)[0]
                or "application/octet-stream",
                "CacheControl": "public, max-age=31536000, immutable",
            },
        )
        print(f"[{i}/{len(names)}] {name}")
    return len(names)


if __name__ == "__main__":
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
        print(__doc__)
        sys.exit(1)
    try:
        count = upload(sys.argv[1])
    except Exception as e:
        print(f"Error uploading media: {e}")
        sys.exit(1)
    print(f"Uploaded {count} files to {settings.MINIO_BUCKET_MEDIA}/{MEDIA_PREFIX}")
