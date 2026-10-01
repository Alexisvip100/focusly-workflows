from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import User
from app.redis import cache
from datetime import datetime


def _safe_attr(user: User, key: str, default=None):
    state = inspect(user, raiseerr=False)
    if state and key in state.unloaded:
        return default
    return getattr(user, key, default)


def serialize_user(user: User) -> dict:
    created_at = _safe_attr(user, "createdAt")
    updated_at = _safe_attr(user, "updatedAt")
    last_sync_at = _safe_attr(user, "lastSyncAt")

    return {
        "id": user.id,
        "email": user.email,
        "name": _safe_attr(user, "name"),
        "picture": _safe_attr(user, "picture"),
        "role": _safe_attr(user, "role"),
        "bio": _safe_attr(user, "bio"),
        "authProvider": _safe_attr(user, "authProvider"),
        "googleRefreshToken": _safe_attr(user, "googleRefreshToken"),
        "subscriptionStatus": _safe_attr(user, "subscriptionStatus", "free"),
        "settings": _safe_attr(user, "settings"),
        "externalId": _safe_attr(user, "externalId"),
        "fcmToken": _safe_attr(user, "fcmToken"),
        "passwordHash": _safe_attr(user, "passwordHash"),
        "lastSyncAt": last_sync_at.isoformat() if last_sync_at else None,
        "googleCalendarSyncToken": _safe_attr(user, "googleCalendarSyncToken"),
        "googleChannelId": _safe_attr(user, "googleChannelId"),
        "googleResourceId": _safe_attr(user, "googleResourceId"),
        "googleChannelExpiration": _safe_attr(user, "googleChannelExpiration"),
        "createdAt": created_at.isoformat() if created_at else None,
        "updatedAt": updated_at.isoformat() if updated_at else None,
    }


def deserialize_user(data: dict) -> User:
    created_at = (
        datetime.fromisoformat(data["createdAt"])
        if data.get("createdAt")
        else datetime.now()
    )
    updated_at = (
        datetime.fromisoformat(data["updatedAt"])
        if data.get("updatedAt")
        else datetime.now()
    )
    last_sync_at = (
        datetime.fromisoformat(data["lastSyncAt"]) if data.get("lastSyncAt") else None
    )
    google_channel_exp = data.get("googleChannelExpiration")
    user = User(
        id=data["id"],
        email=data["email"],
        name=data["name"],
        picture=data["picture"],
        role=data["role"],
        bio=data["bio"],
        authProvider=data["authProvider"],
        googleRefreshToken=data["googleRefreshToken"],
        subscriptionStatus=data["subscriptionStatus"],
        settings=data["settings"],
        externalId=data["externalId"],
        fcmToken=data["fcmToken"],
    )
    user.passwordHash = data.get("passwordHash")
    user.lastSyncAt = last_sync_at
    user.googleCalendarSyncToken = data.get("googleCalendarSyncToken")
    user.googleChannelId = data.get("googleChannelId")
    user.googleResourceId = data.get("googleResourceId")
    user.googleChannelExpiration = google_channel_exp
    user.createdAt = created_at
    user.updatedAt = updated_at
    return user


class UsersRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user: User, commit: bool = False) -> User:
        self.db.add(user)
        if commit:
            await self.db.commit()
            await self.db.refresh(user)
        else:
            await self.db.flush()
        await cache.set(f"user:id:{user.id}", serialize_user(user))
        await cache.set(f"user:email:{user.email}", serialize_user(user))
        return user

    async def get_by_id(self, user_id: str) -> User | None:
        cached = await cache.get(f"user:id:{user_id}")
        if cached:
            return deserialize_user(cached)
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user:
            await cache.set(f"user:id:{user.id}", serialize_user(user))
            await cache.set(f"user:email:{user.email}", serialize_user(user))
        return user

    async def get_by_email(self, email: str) -> User | None:
        cached = await cache.get(f"user:email:{email}")
        if cached:
            return deserialize_user(cached)
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalars().first()
        if user:
            await cache.set(f"user:id:{user.id}", serialize_user(user))
            await cache.set(f"user:email:{user.email}", serialize_user(user))
        return user

    async def get_all(self) -> list[User]:
        result = await self.db.execute(select(User))
        return list(result.scalars().all())

    async def save(self, user: User, commit: bool = False) -> User:
        if user not in self.db:
            user = await self.db.merge(user)
        if commit:
            await self.db.commit()
            await self.db.refresh(user)
        else:
            await self.db.flush()
        await cache.set(f"user:id:{user.id}", serialize_user(user))
        await cache.set(f"user:email:{user.email}", serialize_user(user))
        return user

    async def delete(self, user: User, commit: bool = False) -> None:
        if user not in self.db:
            user = await self.db.merge(user)
        await self.db.delete(user)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        await cache.delete(f"user:id:{user.id}")
        await cache.delete(f"user:email:{user.email}")
