from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import User
from app.redis import cache
from datetime import datetime

def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "role": user.role,
        "bio": user.bio,
        "authProvider": user.authProvider,
        "googleRefreshToken": user.googleRefreshToken,
        "subscriptionStatus": user.subscriptionStatus,
        "settings": user.settings,
        "externalId": user.externalId,
        "fcmToken": user.fcmToken,
        "passwordHash": user.passwordHash,
        "lastSyncAt": user.lastSyncAt.isoformat() if user.lastSyncAt else None,
        "googleCalendarSyncToken": user.googleCalendarSyncToken,
        "googleChannelId": user.googleChannelId,
        "googleResourceId": user.googleResourceId,
        "googleChannelExpiration": user.googleChannelExpiration,
        "createdAt": user.createdAt.isoformat() if user.createdAt else None,
        "updatedAt": user.updatedAt.isoformat() if user.updatedAt else None
    }

def deserialize_user(data: dict) -> User:
    created_at = datetime.fromisoformat(data["createdAt"]) if data.get("createdAt") else None
    updated_at = datetime.fromisoformat(data["updatedAt"]) if data.get("updatedAt") else None
    last_sync_at = datetime.fromisoformat(data["lastSyncAt"]) if data.get("lastSyncAt") else None
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
        fcmToken=data["fcmToken"]
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

    async def create(self, user: User) -> User:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
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

    async def save(self, user: User) -> User:
        if user not in self.db:
            user = await self.db.merge(user)
        await self.db.commit()
        await self.db.refresh(user)
        await cache.set(f"user:id:{user.id}", serialize_user(user))
        await cache.set(f"user:email:{user.email}", serialize_user(user))
        return user

    async def delete(self, user: User) -> None:
        if user not in self.db:
            user = await self.db.merge(user)
        await self.db.delete(user)
        await self.db.commit()
        await cache.delete(f"user:id:{user.id}")
        await cache.delete(f"user:email:{user.email}")
