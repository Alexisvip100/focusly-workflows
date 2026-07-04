from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import User

class UsersService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user_data: dict[str, Any]) -> User:
        user = User(
            id=user_data.get("id"),
            email=user_data.get("email"),
            name=user_data.get("name"),
            picture=user_data.get("picture"),
            role=user_data.get("role", "user"),
            bio=user_data.get("bio"),
            authProvider=user_data.get("authProvider"),
            googleRefreshToken=user_data.get("googleRefreshToken"),
            subscriptionStatus=user_data.get("subscriptionStatus", "free"),
            settings=user_data.get("settings"),
            externalId=user_data.get("externalId"),
            fcmToken=user_data.get("fcmToken")
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def findOne(self, id: str) -> User | None:
        result = await self.db.execute(select(User).where(User.id == id))
        return result.scalars().first()

    async def findByEmail(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalars().first()

    async def find(self) -> list[User]:
        result = await self.db.execute(select(User))
        return list(result.scalars().all())

    async def update(self, id: str, update_data: dict[str, Any]) -> User | None:
        result = await self.db.execute(select(User).where(User.id == id))
        user = result.scalars().first()
        if not user:
            return None

        for key, value in update_data.items():
            if hasattr(user, key) and value is not None:
                setattr(user, key, value)

        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def updateGoogleRefreshToken(self, id: str, token: str) -> None:
        result = await self.db.execute(select(User).where(User.id == id))
        user = result.scalars().first()
        if user:
            user.googleRefreshToken = token
            await self.db.commit()
