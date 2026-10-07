import os
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.ai.repository import ConversationRepository, MessageRepository
from .chat_payload import compact_assistant_message, compact_user_message
from .gemini_rest import generate_text
from .prompts import SUMMARIZATION_PROMPT

# A background extra after each reply: never worth holding a request for.
GEMINI_TIMEOUT_SECONDS = 30


async def check_and_summarize(
    conversation_id: str, db: AsyncSession, threshold: int = 20
):
    """
    Checks if conversation length exceeds threshold. If so, summarizes older messages,
    updates conversation summary, and keeps only the most recent messages.
    """
    msg_repo = MessageRepository(db)
    conv_repo = ConversationRepository(db)

    # 1. Count messages
    messages = await msg_repo.get_by_conversation_id(conversation_id)

    if len(messages) <= threshold:
        return

    # 2. Get conversation
    conversation = await conv_repo.get_by_id(conversation_id)
    if not conversation:
        return

    # 3. Build text to summarize
    text_to_summarize = ""
    if conversation.summary:
        text_to_summarize += f"Previous Summary: {conversation.summary}\n\n"

    text_to_summarize += "New Messages:\n"
    # Summarize all but the last 5 messages
    messages_to_summarize = messages[:-5]
    for m in messages_to_summarize:
        # Without attached files and action payloads: what was said and done.
        content = (
            compact_user_message(m.content)
            if m.role == "user"
            else compact_assistant_message(m.content)
        )
        text_to_summarize += f"{m.role}: {content}\n"

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return

    try:
        # Async, so the server keeps serving everyone else meanwhile.
        new_summary = await generate_text(
            f"{SUMMARIZATION_PROMPT}\n\n{text_to_summarize}",
            timeout=GEMINI_TIMEOUT_SECONDS,
        )
        if not new_summary:
            return

        # 4. Update Conversation summary
        conversation.summary = new_summary

        try:
            await conv_repo.save(conversation)

            # 5. Delete summarized messages using batch delete
            await msg_repo.delete_many(messages_to_summarize)

            await db.commit()
        except Exception as e:
            await db.rollback()
            raise e

    except Exception:
        pass
