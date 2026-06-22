from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import Conversation, Message
from .prompts import SYSTEM_PROMPT
from .memory import search_memories

async def build_context(user_id: str, conversation_id: str, query: str, db: AsyncSession) -> str:
    """
    Builds the full prompt context for the LLM.
    """
    context = f"{SYSTEM_PROMPT}\n\n"
    
    # 1. Fetch relevant memories
    memories = await search_memories(user_id, query, db)
    if memories:
        context += f"--- USER MEMORIES ---\n{memories}\n\n"
        
    # 2. Fetch conversation summary
    conv_result = await db.execute(select(Conversation).filter(Conversation.id == conversation_id))
    conversation = conv_result.scalar_one_or_none()
    
    if conversation and conversation.summary:
        context += f"--- PREVIOUS CONVERSATION SUMMARY ---\n{conversation.summary}\n\n"
        
    # 3. Fetch recent messages
    if conversation:
        msg_result = await db.execute(
            select(Message)
            .filter(Message.conversationId == conversation_id)
            .order_by(Message.createdAt.desc())
            .limit(10)
        )
        recent_messages = msg_result.scalars().all()
        # They come out desc, so reverse them for chronological
        recent_messages.reverse()
        
        if recent_messages:
            context += "--- RECENT MESSAGES ---\n"
            for m in recent_messages:
                context += f"{m.role}: {m.content}\n"
    
    context += f"\nUser Query: {query}\n"
    return context
