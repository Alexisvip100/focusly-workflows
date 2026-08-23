from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routes.common import get_current_user_id
from app.modules.storage.services.storage_service import generate_avatar_upload_url

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
