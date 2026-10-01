from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.routes.common import get_current_user_id
from app.modules.storage.services.storage_service import (
    generate_avatar_upload_url,
    get_avatar_object,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])


class PresignAvatarUploadSchema(BaseModel):
    content_type: str


@router.post("/avatar/presign")
async def presign_avatar_upload(
    body: PresignAvatarUploadSchema,
    current_user_id: str = Depends(get_current_user_id),
):
    try:
        return generate_avatar_upload_url(current_user_id, body.content_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/avatar/{user_id}/{filename}")
async def get_avatar(user_id: str, filename: str):
    if "/" in filename or "\\" in filename or ".." in filename or ".." in user_id:
        raise HTTPException(status_code=400, detail="Invalid avatar path")

    data = get_avatar_object(f"{user_id}/{filename}")
    if not data:
        raise HTTPException(status_code=404, detail="Avatar not found")
    content, content_type = data
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )
