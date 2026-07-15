import os
from sqlalchemy.ext.asyncio import AsyncSession
from google import genai
from app.modules.ai.repository import ConversationRepository, MessageRepository
from .prompts import SUMMARIZATION_PROMPT

async def check_and_summarize(conversation_id: str, db: AsyncSession, threshold: int = 20):
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
        text_to_summarize += f"{m.role}: {m.content}\n"
        
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return
        
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"{SUMMARIZATION_PROMPT}\n\n{text_to_summarize}",
        )
        new_summary = response.text.strip()
        
        # 4. Update Conversation summary
        conversation.summary = new_summary
        await conv_repo.save(conversation)
        
        # 5. Delete summarized messages
        for m in messages_to_summarize:
            # Delete without manual commit in the loop to save roundtrips
            # But the MessageRepository.delete commits immediately.
            # So let's call it.
            await msg_repo.delete(m)
            
    except Exception:
        pass
