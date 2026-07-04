from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.database import get_db
from app.modules.user.services.users_service import UsersService

router = APIRouter(prefix="/users", tags=["users"])

class CreateUserSchema(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    picture: Optional[str] = None
    role: Optional[str] = "user"
    bio: Optional[str] = None
    authProvider: Optional[str] = None
    googleRefreshToken: Optional[str] = None
    subscriptionStatus: Optional[str] = "free"
    settings: Optional[Dict[str, Any]] = None
    externalId: Optional[str] = None
    fcmToken: Optional[str] = None

class UpdateUserSchema(BaseModel):
    name: Optional[str] = None
    picture: Optional[str] = None
    role: Optional[str] = None
    bio: Optional[str] = None
    authProvider: Optional[str] = None
    googleRefreshToken: Optional[str] = None
    subscriptionStatus: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    externalId: Optional[str] = None
    fcmToken: Optional[str] = None

def get_users_service(db: AsyncSession = Depends(get_db)) -> UsersService:
    return UsersService(db)

def map_user_to_dict(user) -> Dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
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

@router.post("", response_model=Dict[str, Any])
async def create_user(
    body: CreateUserSchema,
    users_service: UsersService = Depends(get_users_service)
):
    try:
        user_data = body.model_dump()
        user_data["id"] = str(uuid.uuid4())
        user = await users_service.create(user_data)
        return map_user_to_dict(user)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("", response_model=List[Dict[str, Any]])
async def find_all_users(
    users_service: UsersService = Depends(get_users_service)
):
    users = await users_service.find()
    return [map_user_to_dict(u) for u in users]

@router.get("/{id}", response_model=Dict[str, Any])
async def find_user(
    id: str,
    users_service: UsersService = Depends(get_users_service)
):
    user = await users_service.findOne(id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User with ID {id} not found")
    return map_user_to_dict(user)

@router.patch("/{id}", response_model=Dict[str, Any])
async def update_user(
    id: str,
    body: UpdateUserSchema,
    users_service: UsersService = Depends(get_users_service)
):
    update_data = body.model_dump(exclude_unset=True)
    user = await users_service.update(id, update_data)
    if not user:
        raise HTTPException(status_code=404, detail=f"User with ID {id} not found")
    return map_user_to_dict(user)
