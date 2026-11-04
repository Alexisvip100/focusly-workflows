from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.modules.notification.services import push_service
from app.routes.common import get_current_user_id

router = APIRouter(prefix="/push", tags=["push"])


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=512)
    auth: str = Field(min_length=1, max_length=512)


class SubscribeBody(BaseModel):
    """What the browser's PushSubscription.toJSON() gives."""

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushKeys
    # The device's IANA time zone; an unknown one is dropped, not an error
    timeZone: str | None = Field(default=None, max_length=64)

    @field_validator("timeZone")
    @classmethod
    def known_time_zone(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            return None
        return value


class UnsubscribeBody(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)


@router.get("/public-key")
async def get_public_key():
    """The key browsers subscribe with. Public by design; enabled=false
    tells the app push isn't set up on this server, so it doesn't try."""
    return {
        "enabled": push_service.is_configured(),
        "publicKey": settings.VAPID_PUBLIC_KEY if push_service.is_configured() else None,
    }


@router.post("/subscriptions")
async def subscribe(
    body: SubscribeBody,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if not push_service.is_configured():
        raise HTTPException(status_code=503, detail="Push notifications are not configured")
    # Push services only ever hand out https endpoints
    if not body.endpoint.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid push endpoint")
    await push_service.save_subscription(
        db,
        current_user_id,
        body.endpoint,
        body.keys.p256dh,
        body.keys.auth,
        (request.headers.get("user-agent") or "")[:300] or None,
        body.timeZone,
    )
    return {"success": True}


@router.delete("/subscriptions")
async def unsubscribe(
    body: UnsubscribeBody,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    removed = await push_service.remove_subscription(db, current_user_id, body.endpoint)
    return {"success": True, "removed": removed}
