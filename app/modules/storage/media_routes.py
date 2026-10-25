from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from app.modules.storage.services.media_service import get_media_url, is_media_filename

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/videos/{filename}")
async def get_site_video(filename: str):
    """The public site's loop videos: redirects to a signed link, so the file
    itself streams from the bucket (with Range support) and never through
    this service. Public on purpose: the videos are on the marketing pages.
    """
    if not is_media_filename(filename):
        raise HTTPException(status_code=404, detail="Media not found")

    url, cache_seconds = get_media_url(filename)
    # Cached redirect → same signed URL → the browser reuses the video it has.
    return RedirectResponse(
        url,
        status_code=302,
        headers={"Cache-Control": f"public, max-age={cache_seconds}"},
    )
