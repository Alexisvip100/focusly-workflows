from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException, Depends, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, safe_attr
from app.routes.common import get_current_user_id
from app.modules.auth.routes import clear_auth_cookies
from app.modules.user.legal import CURRENT_TERMS_VERSION, terms_fields
from app.modules.user.services.users_service import UsersService
from app.modules.user.services.account_deletion_service import (
    AccountDeletionService,
)
from app.modules.storage.services.storage_service import (
    resolve_avatar_url,
    delete_avatar_object,
    is_avatar_key_owned_by,
)

router = APIRouter(prefix="/users", tags=["users"])


class CreateUserSchema(BaseModel):
    email: EmailStr
    name: str | None = None
    picture: str | None = None
    role: str | None = "user"
    bio: str | None = None
    authProvider: str | None = None
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
    subscriptionStatus: str | None = None
    settings: dict[str, Any] | None = None
    externalId: str | None = None
    fcmToken: str | None = None


def get_users_service(db: AsyncSession = Depends(get_db)) -> UsersService:
    return UsersService(db)


def get_account_deletion_service(
    db: AsyncSession = Depends(get_db),
) -> AccountDeletionService:
    return AccountDeletionService(db)


def map_user_to_dict(user: Any) -> dict[str, Any]:
    created_at = safe_attr(user, "createdAt")
    updated_at = safe_attr(user, "updatedAt")
    return {
        "id": safe_attr(user, "id"),
        "email": safe_attr(user, "email"),
        "name": safe_attr(user, "name"),
        "picture": resolve_avatar_url(safe_attr(user, "picture")),
        "role": safe_attr(user, "role"),
        "bio": safe_attr(user, "bio"),
        "authProvider": safe_attr(user, "authProvider"),
        "subscriptionStatus": safe_attr(user, "subscriptionStatus", "free"),
        "settings": safe_attr(user, "settings"),
        "fcmToken": safe_attr(user, "fcmToken"),
        **terms_fields(user),
        "createdAt": (
            created_at.isoformat()
            if created_at and hasattr(created_at, "isoformat")
            else (str(created_at) if created_at else None)
        ),
        "updatedAt": (
            updated_at.isoformat()
            if updated_at and hasattr(updated_at, "isoformat")
            else (str(updated_at) if updated_at else None)
        ),
    }


@router.post("", response_model=dict[str, Any])
async def create_user(
    body: CreateUserSchema,
    current_user_id: str = Depends(get_current_user_id),
    users_service: UsersService = Depends(get_users_service),
):
    current_user = await users_service.findOne(current_user_id)
    if not current_user or current_user.role != "admin":
        raise HTTPException(
            status_code=403, detail="Admin privileges required to create users manually"
        )
    try:
        user_data = body.model_dump()
        user_data["id"] = str(uuid.uuid4())
        user = await users_service.create(user_data)
        return map_user_to_dict(user)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=list[dict[str, Any]])
async def find_all_users(
    current_user_id: str = Depends(get_current_user_id),
    users_service: UsersService = Depends(get_users_service),
):
    current_user = await users_service.findOne(current_user_id)
    if not current_user or current_user.role != "admin":
        raise HTTPException(
            status_code=403, detail="Admin privileges required"
        )
    users = await users_service.find()
    return [map_user_to_dict(u) for u in users]


@router.get("/{id}/public-profile", response_model=dict[str, Any])
async def find_public_profile(
    id: str,
    current_user_id: str = Depends(get_current_user_id),
    users_service: UsersService = Depends(get_users_service),
):
    user = await users_service.findOne(id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User with ID {id} not found")
    return {
        "id": user.id,
        "name": user.name,
        "picture": resolve_avatar_url(user.picture),
        "bio": user.bio,
    }


@router.get("/{id}", response_model=dict[str, Any])
async def find_user(
    id: str,
    current_user_id: str = Depends(get_current_user_id),
    users_service: UsersService = Depends(get_users_service),
):
    current_user = await users_service.findOne(current_user_id)
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found")

    if id != current_user_id and current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view this user profile",
        )

    user = current_user if id == current_user_id else await users_service.findOne(id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User with ID {id} not found")
    return map_user_to_dict(user)


@router.patch("/{id}", response_model=dict[str, Any])
async def update_user(
    id: str,
    body: UpdateUserSchema,
    current_user_id: str = Depends(get_current_user_id),
    users_service: UsersService = Depends(get_users_service),
):
    current_user = await users_service.findOne(current_user_id)
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found")

    is_admin = current_user.role == "admin"
    if id != current_user_id and not is_admin:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to modify this user account",
        )

    target_user = current_user if id == current_user_id else await users_service.findOne(id)
    if not target_user:
        raise HTTPException(status_code=404, detail=f"User with ID {id} not found")

    update_data = body.model_dump(exclude_unset=True)
    if not is_admin:
        if "role" in update_data and update_data["role"] != target_user.role:
            raise HTTPException(
                status_code=403,
                detail="Forbidden: Only administrators can modify user roles",
            )
        if (
            "subscriptionStatus" in update_data
            and update_data["subscriptionStatus"] != target_user.subscriptionStatus
        ):
            raise HTTPException(
                status_code=403,
                detail="Forbidden: Only administrators can modify subscription status",
            )
        # Discard redundant echoes so update query never touches them
        update_data.pop("role", None)
        update_data.pop("subscriptionStatus", None)

    # A bare storage key must be one issued to this user; otherwise a user
    # could adopt another user's key and then get it deleted on next change.
    new_picture = update_data.get("picture")
    if (
        new_picture
        and not new_picture.startswith(("http://", "https://"))
        and not is_avatar_key_owned_by(new_picture, id)
    ):
        raise HTTPException(status_code=400, detail="Invalid picture")

    previous_picture = target_user.picture

    user = await users_service.update(id, update_data)
    if not user:
        raise HTTPException(status_code=404, detail=f"User with ID {id} not found")

    # Only delete objects we own (bare MinIO keys under this user's prefix) —
    # never an absolute URL like a Google profile photo, nor a key stored
    # before ownership was validated — and only once the new value is safely
    # persisted, so a failed update never orphans the still-current photo.
    if (
        "picture" in update_data
        and previous_picture
        and previous_picture != update_data.get("picture")
        and is_avatar_key_owned_by(previous_picture, id)
    ):
        delete_avatar_object(previous_picture)

    return map_user_to_dict(user)


@router.post("/{id}/accept-terms", response_model=dict[str, Any])
async def accept_terms(
    id: str,
    current_user_id: str = Depends(get_current_user_id),
    users_service: UsersService = Depends(get_users_service),
):
    # Acceptance is personal: not even an admin may accept on someone's behalf.
    if id != current_user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only accept the terms for your own account",
        )

    user = await users_service.update(
        id,
        {
            "termsVersion": CURRENT_TERMS_VERSION,
            "termsAcceptedAt": datetime.now(timezone.utc).replace(tzinfo=None),
        },
    )
    if not user:
        raise HTTPException(status_code=404, detail=f"User with ID {id} not found")
    return map_user_to_dict(user)


@router.delete("/{id}", response_model=dict[str, Any])
async def delete_user(
    id: str,
    response: Response,
    current_user_id: str = Depends(get_current_user_id),
    users_service: UsersService = Depends(get_users_service),
    deletion_service: AccountDeletionService = Depends(get_account_deletion_service),
):
    current_user = await users_service.findOne(current_user_id)
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found")

    if id != current_user_id and current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to delete this user account",
        )

    target_user = current_user if id == current_user_id else await users_service.findOne(id)
    if not target_user:
        raise HTTPException(status_code=404, detail=f"User with ID {id} not found")

    await deletion_service.delete_account(target_user)

    if id == current_user_id:
        clear_auth_cookies(response)
    return {"success": True}
