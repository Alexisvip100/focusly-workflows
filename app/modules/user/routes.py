from fastapi import APIRouter, HTTPException, Depends
from typing import Any
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.database import get_db
from app.modules.user.services.users_service import UsersService
from app.modules.storage.services.storage_service import (
    resolve_avatar_url,
    delete_avatar_object,
)

router = APIRouter(prefix="/users", tags=["users"])


class CreateUserSchema(BaseModel):
    email: EmailStr
    name: str | None = None
    picture: str | None = None
    role: str | None = "user"
    bio: str | None = None
    authProvider: str | None = None
    googleRefreshToken: str | None = None
    subscriptionStatus: str | None = "free"
    settings: dict[str, Any] | None = None
    externalId: str | None = None
    fcmToken: str | None = None


class UpdateUserSchema(BaseModel):
    name: str | None = None
    picture: str | None = None
    role: str | None = None
    bio: str | None = None
    authProvider: str | None = None
    googleRefreshToken: str | None = None
    subscriptionStatus: str | None = None
    settings: dict[str, Any] | None = None
    externalId: str | None = None
    fcmToken: str | None = None


def get_users_service(db: AsyncSession = Depends(get_db)) -> UsersService:
    return UsersService(db)


def map_user_to_dict(user) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": resolve_avatar_url(user.picture),
        "role": user.role,
        "bio": user.bio,
        "authProvider": user.authProvider,
        "subscriptionStatus": user.subscriptionStatus,
        "settings": user.settings,
        "fcmToken": user.fcmToken,
        "createdAt": user.createdAt.isoformat() if user.createdAt else None,
        "updatedAt": user.updatedAt.isoformat() if user.updatedAt else None,
        "googleRefreshToken": user.googleRefreshToken,
    }


@router.post("", response_model=dict[str, Any])
async def create_user(
    body: CreateUserSchema, users_service: UsersService = Depends(get_users_service)
):
    try:
        user_data = body.model_dump()
        user_data["id"] = str(uuid.uuid4())
        user = await users_service.create(user_data)
        return map_user_to_dict(user)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=list[dict[str, Any]])
async def find_all_users(users_service: UsersService = Depends(get_users_service)):
    users = await users_service.find()
    return [map_user_to_dict(u) for u in users]


@router.get("/{id}", response_model=dict[str, Any])
async def find_user(id: str, users_service: UsersService = Depends(get_users_service)):
    user = await users_service.findOne(id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User with ID {id} not found")
    return map_user_to_dict(user)


@router.patch("/{id}", response_model=dict[str, Any])
async def update_user(
    id: str,
    body: UpdateUserSchema,
    users_service: UsersService = Depends(get_users_service),
):
    update_data = body.model_dump(exclude_unset=True)

    previous_picture = None
    if "picture" in update_data:
        existing_user = await users_service.findOne(id)
        previous_picture = existing_user.picture if existing_user else None

    user = await users_service.update(id, update_data)
    if not user:
        raise HTTPException(status_code=404, detail=f"User with ID {id} not found")

    # Only delete objects we own (bare MinIO keys) — never an absolute URL
    # like a Google profile photo — and only once the new value is safely
    # persisted, so a failed update never orphans the still-current photo.
    if (
        previous_picture
        and previous_picture != update_data.get("picture")
        and not previous_picture.startswith(("http://", "https://"))
    ):
        delete_avatar_object(previous_picture)

    return map_user_to_dict(user)
