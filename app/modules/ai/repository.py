from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from app.models import Conversation, Message, UserMemory

class ConversationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, conversation: Conversation) -> Conversation:
        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def get_by_id(self, conv_id: str) -> Conversation | None:
        result = await self.db.execute(select(Conversation).where(Conversation.id == conv_id))
        return result.scalars().first()

    async def get_all_by_user(self, user_id: str) -> list[Conversation]:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.userId == user_id)
            .order_by(Conversation.updatedAt.desc())
        )
        return list(result.scalars().all())

    async def save(self, conversation: Conversation) -> Conversation:
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def delete(self, conversation: Conversation) -> None:
        await self.db.delete(conversation)
        await self.db.commit()


class MessageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, message: Message) -> Message:
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def get_by_id(self, msg_id: str) -> Message | None:
        result = await self.db.execute(select(Message).where(Message.id == msg_id))
        return result.scalars().first()

    async def get_by_conversation_id(self, conversation_id: str) -> list[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.conversationId == conversation_id)
            .order_by(Message.createdAt.asc())
        )
        return list(result.scalars().all())

    async def delete_by_conversation_id(self, conversation_id: str) -> None:
        await self.db.execute(
            delete(Message).where(Message.conversationId == conversation_id)
        )
        await self.db.commit()

    async def delete(self, message: Message) -> None:
        await self.db.delete(message)
        # Note: commit is left to the caller if batching, or done immediately:
        await self.db.commit()


class UserMemoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, memory: UserMemory) -> UserMemory:
        self.db.add(memory)
        await self.db.commit()
        await self.db.refresh(memory)
        return memory

    async def get_by_id(self, memory_id: str) -> UserMemory | None:
        result = await self.db.execute(select(UserMemory).where(UserMemory.id == memory_id))
        return result.scalars().first()

    async def get_all_by_user(self, user_id: str) -> list[UserMemory]:
        result = await self.db.execute(select(UserMemory).where(UserMemory.userId == user_id))
        return list(result.scalars().all())

    async def save(self, memory: UserMemory) -> UserMemory:
        await self.db.commit()
        await self.db.refresh(memory)
        return memory

    async def delete(self, memory: UserMemory) -> None:
        await self.db.delete(memory)
        await self.db.commit()
