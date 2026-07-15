from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from app.models import Conversation, Message, UserMemory
from app.redis import cache
from datetime import datetime

def serialize_conversation(c: Conversation) -> dict:
    return {
        "id": c.id,
        "userId": c.userId,
        "title": c.title,
        "summary": c.summary,
        "createdAt": c.createdAt.isoformat() if c.createdAt else None,
        "updatedAt": c.updatedAt.isoformat() if c.updatedAt else None
    }

def deserialize_conversation(data: dict) -> Conversation:
    created_at = datetime.fromisoformat(data["createdAt"]) if data.get("createdAt") else None
    updated_at = datetime.fromisoformat(data["updatedAt"]) if data.get("updatedAt") else None
    c = Conversation(
        id=data["id"],
        userId=data["userId"],
        title=data["title"],
        summary=data["summary"]
    )
    c.createdAt = created_at
    c.updatedAt = updated_at
    return c

def serialize_message(m: Message) -> dict:
    return {
        "id": m.id,
        "conversationId": m.conversationId,
        "role": m.role,
        "content": m.content,
        "tokenUsage": m.tokenUsage,
        "createdAt": m.createdAt.isoformat() if m.createdAt else None
    }

def deserialize_message(data: dict) -> Message:
    created_at = datetime.fromisoformat(data["createdAt"]) if data.get("createdAt") else None
    m = Message(
        id=data["id"],
        conversationId=data["conversationId"],
        role=data["role"],
        content=data["content"],
        tokenUsage=data["tokenUsage"]
    )
    m.createdAt = created_at
    return m

class ConversationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, conversation: Conversation) -> Conversation:
        self.db.add(conversation)
        await self.db.flush()
        await self.db.refresh(conversation)
        await cache.set(f"conversation:id:{conversation.id}", serialize_conversation(conversation))
        await cache.delete(f"conversations:user:{conversation.userId}")
        return conversation

    async def get_by_id(self, conv_id: str) -> Conversation | None:
        cached = await cache.get(f"conversation:id:{conv_id}")
        if cached:
            return deserialize_conversation(cached)
        result = await self.db.execute(select(Conversation).where(Conversation.id == conv_id))
        conversation = result.scalars().first()
        if conversation:
            await cache.set(f"conversation:id:{conversation.id}", serialize_conversation(conversation))
        return conversation

    async def get_all_by_user(self, user_id: str) -> list[Conversation]:
        cached = await cache.get(f"conversations:user:{user_id}")
        if cached is not None:
            return [deserialize_conversation(c) for c in cached]
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.userId == user_id)
            .order_by(Conversation.updatedAt.desc())
        )
        conversations = list(result.scalars().all())
        await cache.set(f"conversations:user:{user_id}", [serialize_conversation(c) for c in conversations])
        return conversations

    async def save(self, conversation: Conversation) -> Conversation:
        if conversation not in self.db:
            conversation = await self.db.merge(conversation)
        await self.db.flush()
        await self.db.refresh(conversation)
        await cache.set(f"conversation:id:{conversation.id}", serialize_conversation(conversation))
        await cache.delete(f"conversations:user:{conversation.userId}")
        return conversation

    async def delete(self, conversation: Conversation) -> None:
        if conversation not in self.db:
            conversation = await self.db.merge(conversation)
        await self.db.delete(conversation)
        await self.db.flush()
        await cache.delete(f"conversation:id:{conversation.id}")
        await cache.delete(f"conversations:user:{conversation.userId}")
        await cache.delete(f"conversation:messages:{conversation.id}")


class MessageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, message: Message) -> Message:
        self.db.add(message)
        await self.db.flush()
        await self.db.refresh(message)
        await cache.delete(f"conversation:messages:{message.conversationId}")
        return message

    async def get_by_id(self, msg_id: str) -> Message | None:
        result = await self.db.execute(select(Message).where(Message.id == msg_id))
        return result.scalars().first()

    async def get_by_conversation_id(self, conversation_id: str) -> list[Message]:
        cached = await cache.get(f"conversation:messages:{conversation_id}")
        if cached is not None:
            return [deserialize_message(m) for m in cached]
        result = await self.db.execute(
            select(Message)
            .where(Message.conversationId == conversation_id)
            .order_by(Message.createdAt.asc())
        )
        messages = list(result.scalars().all())
        await cache.set(f"conversation:messages:{conversation_id}", [serialize_message(m) for m in messages], expire_seconds=3600)
        return messages

    async def delete_by_conversation_id(self, conversation_id: str) -> None:
        await self.db.execute(
            delete(Message).where(Message.conversationId == conversation_id)
        )
        await self.db.flush()
        await cache.delete(f"conversation:messages:{conversation_id}")

    async def delete_many(self, messages: list[Message]) -> None:
        if not messages:
            return
        ids = [m.id for m in messages]
        await self.db.execute(
            delete(Message).where(Message.id.in_(ids))
        )
        await self.db.flush()
        conv_id = messages[0].conversationId
        await cache.delete(f"conversation:messages:{conv_id}")

    async def delete(self, message: Message) -> None:
        conversation_id = message.conversationId
        if message not in self.db:
            message = await self.db.merge(message)
        await self.db.delete(message)
        await self.db.commit()
        await cache.delete(f"conversation:messages:{conversation_id}")


class UserMemoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, memory: UserMemory) -> UserMemory:
        self.db.add(memory)
        await self.db.flush()
        await self.db.refresh(memory)
        return memory

    async def get_by_id(self, memory_id: str) -> UserMemory | None:
        result = await self.db.execute(select(UserMemory).where(UserMemory.id == memory_id))
        return result.scalars().first()

    async def get_all_by_user(self, user_id: str) -> list[UserMemory]:
        result = await self.db.execute(select(UserMemory).where(UserMemory.userId == user_id))
        return list(result.scalars().all())

    async def save(self, memory: UserMemory) -> UserMemory:
        if memory not in self.db:
            memory = await self.db.merge(memory)
        await self.db.flush()
        await self.db.refresh(memory)
        return memory

    async def delete(self, memory: UserMemory) -> None:
        if memory not in self.db:
            memory = await self.db.merge(memory)
        await self.db.delete(memory)
        await self.db.flush()
