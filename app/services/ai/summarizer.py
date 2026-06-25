import os

from google import genai
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.models import Conversation, Message

from .prompts import SUMMARIZATION_PROMPT


async def check_and_summarize(
    conversation_id: str, db: AsyncSession, threshold: int = 20
):
    """
    Checks if conversation length exceeds threshold. If so, summarizes older messages,
    updates conversation summary, and keeps only the most recent messages.
    """
    # 1. Count messages
    result = await db.execute(
        select(Message)
        .filter(Message.conversationId == conversation_id)
        .order_by(Message.createdAt.asc())
    )
    messages = result.scalars().all()

    if len(messages) <= threshold:
        return

    # 2. Get conversation
    conv_result = await db.execute(
        select(Conversation).filter(Conversation.id == conversation_id)
    )
    conversation = conv_result.scalar_one_or_none()
    if not conversation:
        return

    # 3. Build text to summarize
    # Include existing summary if any
    text_to_summarize = ""
    if conversation.summary:
        text_to_summarize += f"Previous Summary: {conversation.summary}\n\n"

    text_to_summarize += "New Messages:\n"
    # Summarize all but the last 5 messages
    messages_to_summarize = messages[:-5]
    for m in messages_to_summarize:
        text_to_summarize += f"{m.role}: {m.content}\n"

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return

    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{SUMMARIZATION_PROMPT}\n\n{text_to_summarize}",
        )
        new_summary = response.text.strip()

        # 4. Update Conversation summary
        conversation.summary = new_summary

        # 5. Delete summarized messages
        for m in messages_to_summarize:
            await db.delete(m)

        await db.commit()
    except Exception as e:
        print(f"Summarization error: {e}")
