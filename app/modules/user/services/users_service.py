from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User
from app.modules.user.repository import UsersRepository

class UsersService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = UsersRepository(db)

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
        return await self.repository.create(user)

    async def findOne(self, id: str) -> User | None:
        return await self.repository.get_by_id(id)

    async def findByEmail(self, email: str) -> User | None:
        return await self.repository.get_by_email(email)

    async def find(self) -> list[User]:
        return await self.repository.get_all()

    async def update(self, id: str, update_data: dict[str, Any]) -> User | None:
        user = await self.repository.get_by_id(id)
        if not user:
            return None

        for key, value in update_data.items():
            if hasattr(user, key) and value is not None:
                setattr(user, key, value)

        return await self.repository.save(user)

    async def updateGoogleRefreshToken(self, id: str, token: str) -> None:
        user = await self.repository.get_by_id(id)
        if user:
            user.googleRefreshToken = token
            await self.repository.save(user)

