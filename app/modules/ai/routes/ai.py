from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any
import httpx
import json
import uuid

from sqlalchemy.future import select
from app.config import settings
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.routes.common import get_current_user_id
from app.models import Conversation, Message

from app.modules.ai.services.context_builder import build_context
from app.modules.ai.services.router import classify_query
from app.modules.ai.services.memory import extract_and_save_memory
from app.modules.ai.services.summarizer import check_and_summarize

router = APIRouter(prefix="/ai", tags=["ai"])

class MessageSchema(BaseModel):
    role: str
    content: str

class ChatRequestSchema(BaseModel):
    messages: list[MessageSchema]
    task: dict[str, Any] | None = None
    model: str | None = None
    conversationId: str | None = None

class GeminiStreamParser:
    def __init__(self):
        self.buffer = ""

    def feed(self, chunk: str):
        self.buffer += chunk
        self.buffer = self.buffer.lstrip("[\r\n, ")
        
        while self.buffer:
            if not self.buffer.startswith("{"):
                self.buffer = self.buffer.lstrip("\r\n, ]")
                if not self.buffer:
                    break
                if not self.buffer.startswith("{"):
                    self.buffer = ""
                    break
            
            brace_count = 0
            in_string = False
            escape = False
            end_idx = -1
            
            for idx, char in enumerate(self.buffer):
                if char == '"' and not escape:
                    in_string = not in_string
                elif char == '\\' and in_string:
                    escape = not escape
                else:
                    escape = False
                
                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            end_idx = idx
                            break
            
            if end_idx != -1:
                obj_str = self.buffer[:end_idx + 1]
                self.buffer = self.buffer[end_idx + 1:].lstrip("\r\n, ")
                try:
                    obj = json.loads(obj_str)
                    candidates = obj.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        if parts:
                            text = parts[0].get("text", "")
                            if text:
                                yield text
                except Exception:
                    pass
            else:
                break

async def background_post_chat_tasks(user_id: str, conversation_id: str, user_message: str, assistant_message: str, db: AsyncSession):
    try:
        # Save assistant message
        ast_msg = Message(
            id=str(uuid.uuid4()),
            conversationId=conversation_id,
            role="assistant",
            content=assistant_message,
            tokenUsage=0
        )
        db.add(ast_msg)
        await db.commit()
        
        # Memory Extraction
        await extract_and_save_memory(user_id, user_message, db)
        
        # Summarizer Check
        await check_and_summarize(conversation_id, db)
        
    except Exception:
        pass

async def stream_gemini_and_save(
    messages: list[dict[str, str]],
    system_context: str,
    model: str,
    background_tasks: BackgroundTasks,
    user_id: str,
    conversation_id: str,
    user_message: str,
    db_factory
):
    url = f"{settings.FOCUSLY_AI_URL}/ai/chat"
    payload = {
        "messages": messages,
        "system_context": system_context,
        "model": model
    }
    
    full_assistant_response = ""
    
    async with httpx.AsyncClient() as client:
        try:
            # We connect to focusly-ai's /chat endpoint, which returns clean text/plain stream
            async with client.stream("POST", url, json=payload, timeout=60.0) as r:
                if r.status_code != 200:
                    error_text = await r.aread()
                    yield f"Error calling focusly-ai service: {r.status_code} - {error_text.decode('utf-8', errors='ignore')}"
                    return
                
                async for chunk in r.aiter_text():
                    full_assistant_response += chunk
                    yield chunk
        except Exception as e:
            yield f"\nStreaming error from focusly-ai: {str(e)}"
            
    # Enqueue background tasks with a fresh db session
    async for new_db in db_factory():
        background_tasks.add_task(background_post_chat_tasks, user_id, conversation_id, user_message, full_assistant_response, new_db)
        break

from app.modules.insights.services.behavioral_analyzer import BehavioralAnalyzer

@router.post("/analyze-patterns")
async def analyze_patterns_endpoint(
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    analyzer = BehavioralAnalyzer(db)
    signals = await analyzer.collect_signals(current_user_id)

    from app.models import User
    user_result = await db.execute(select(User).where(User.id == current_user_id))
    user_record = user_result.scalars().first()
    user_name = user_record.name if user_record and user_record.name else "ahí"

    url = f"{settings.FOCUSLY_AI_URL}/ai/analyze-patterns"
    payload = {
        "user_name": user_name,
        "hour_buckets": signals['hour_buckets'],
        "task_stats": signals['task_stats'],
        "session_stats": signals['session_stats'],
        "top_productive_hours": signals['top_productive_hours'],
        "work_style_hint": signals['work_style_hint']
    }

    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, timeout=30.0)
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"focusly-ai service returned code {r.status_code}")
            return r.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error proxying patterns analysis to focusly-ai: {str(e)}")

@router.post("/chat")
async def chat_endpoint(
    body: ChatRequestSchema,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    if not body.messages:
        raise HTTPException(status_code=400, detail="Messages array cannot be empty")
        
    # We only care about the latest user message since we have state in DB
    latest_user_message = body.messages[-1].content
    
    # 1. Get or create conversation for user
    conversation_id = body.conversationId
    if conversation_id:
        conv_result = await db.execute(
            select(Conversation)
            .filter(Conversation.id == conversation_id)
            .filter(Conversation.userId == current_user_id)
        )
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        title_snippet = latest_user_message[:30] + ("..." if len(latest_user_message) > 30 else "")
        conversation = Conversation(
            id=str(uuid.uuid4()),
            userId=current_user_id,
            title=title_snippet,
            summary=""
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        
    # 2. Save user message
    user_msg = Message(
        id=str(uuid.uuid4()),
        conversationId=conversation.id,
        role="user",
        content=latest_user_message,
        tokenUsage=0
    )
    db.add(user_msg)
    await db.commit()

    # 3. Router logic
    complexity = classify_query(latest_user_message)
    selected_model = body.model or ("gemini-2.5-flash" if complexity == "complex" else "gemini-2.5-flash-lite")

    # 4. Context Builder
    system_context = await build_context(current_user_id, conversation.id, latest_user_message, db)

    task = body.task
    if task:
        system_context += (
            f"\n\nThe user is currently viewing/focusing on this task:\n"
            f"- Title: {task.get('title', 'Untitled')}\n"
            f"- Notes/Description: {task.get('description') or 'No description provided'}\n"
            f"- Current Status: {task.get('status', 'N/A')}\n"
        )
        links = task.get("links", [])
        if links:
            system_context += "\nAssociated Links:\n"
            for link in links:
                system_context += f"- [{link.get('title', 'Link')}]({link.get('url', '#')})\n"
                
    # Prepare payload for focusly-ai endpoint
    messages_payload = [{"role": m.role, "content": m.content} for m in body.messages]
    
    return StreamingResponse(
        stream_gemini_and_save(
            messages_payload,
            system_context,
            selected_model,
            background_tasks,
            current_user_id,
            conversation.id,
            latest_user_message,
            get_db
        ),
        media_type="text/plain"
    )

@router.get("/conversations")
async def get_conversations(
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Conversation)
        .filter(Conversation.userId == current_user_id)
        .order_by(Conversation.updatedAt.desc())
    )
    conversations = result.scalars().all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "summary": c.summary,
            "createdAt": c.createdAt.isoformat(),
            "updatedAt": c.updatedAt.isoformat()
        }
        for c in conversations
    ]

@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    # Verify ownership
    conv_result = await db.execute(
        select(Conversation)
        .filter(Conversation.id == conversation_id)
        .filter(Conversation.userId == current_user_id)
    )
    conversation = conv_result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    result = await db.execute(
        select(Message)
        .filter(Message.conversationId == conversation_id)
        .order_by(Message.createdAt.asc())
    )
    messages = result.scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "createdAt": m.createdAt.isoformat()
        }
        for m in messages
    ]

@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    conv_result = await db.execute(
        select(Conversation)
        .filter(Conversation.id == conversation_id)
        .filter(Conversation.userId == current_user_id)
    )
    conversation = conv_result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    from sqlalchemy import delete
    await db.execute(delete(Message).where(Message.conversationId == conversation_id))
    await db.execute(delete(Conversation).where(Conversation.id == conversation_id))
    await db.commit()
    return {"status": "success", "message": "Conversation deleted"}
