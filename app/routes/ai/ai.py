from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import httpx
import json

from app.config import settings
from app.routes.common import get_current_user_id

router = APIRouter(prefix="/ai", tags=["ai"])

class MessageSchema(BaseModel):
    role: str
    content: str

class ChatRequestSchema(BaseModel):
    messages: List[MessageSchema]
    task: Optional[Dict[str, Any]] = None
    model: Optional[str] = "gemini-2.5-flash-lite"

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

async def stream_gemini(payload: dict, model: str):
    api_key = settings.GOOGLE_GENERATIVE_AI_API_KEY
    if not api_key:
        yield "Error: GOOGLE_GENERATIVE_AI_API_KEY is not set in backend settings."
        return

    selected_model = model or "gemini-2.5-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:streamGenerateContent?key={api_key}"
    parser = GeminiStreamParser()
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("POST", url, json=payload, timeout=60.0) as r:
                if r.status_code != 200:
                    error_text = await r.aread()
                    yield f"Error calling Gemini API: {r.status_code} - {error_text.decode('utf-8', errors='ignore')}"
                    return
                
                async for chunk in r.aiter_text():
                    for text in parser.feed(chunk):
                        yield text
        except Exception as e:
            yield f"Streaming error: {str(e)}"

@router.post("/chat")
async def chat_endpoint(
    body: ChatRequestSchema,
    current_user_id: str = Depends(get_current_user_id)
):
    # Formulate system instruction based on task metadata
    system_instruction_text = (
        "You are Focusly AI, a highly intelligent and helpful task management companion. "
        "Your goal is to assist the user in analyzing, understanding, planning, and executing their tasks. "
        "Be direct, polite, concise, structured, and prioritize actionable insights. "
        "Feel free to suggest task breakdowns, clear sub-steps, or resource organization. "
        "Always respond in clean, well-formatted Markdown (e.g. use bolding, bullet points, headers). "
    )
    
    task = body.task
    if task:
        system_instruction_text += (
            f"\nThe user is currently viewing/focusing on this task:\n"
            f"- Title: {task.get('title', 'Untitled')}\n"
            f"- Notes/Description: {task.get('description') or 'No description provided'}\n"
            f"- Current Status: {task.get('status', 'N/A')}\n"
            f"- Priority Level: {task.get('priority_level', 'N/A')}\n"
            f"- Estimate Timer: {task.get('estimate_timer', 0)} seconds\n"
            f"- Accumulated/Real Timer: {task.get('real_timer', 0)} seconds\n"
            f"- Deadline: {task.get('deadline') or 'None'}\n"
        )
        
        links = task.get("links", [])
        if links:
            system_instruction_text += "\nAssociated Links:\n"
            for link in links:
                system_instruction_text += f"- [{link.get('title', 'Link')}]({link.get('url', '#')})\n"
                
    # Format messages for Gemini API contents
    gemini_contents = []
    for msg in body.messages:
        role = "model" if msg.role == "assistant" else "user"
        gemini_contents.append({
            "role": role,
            "parts": [{"text": msg.content}]
        })
        
    payload = {
        "contents": gemini_contents,
        "systemInstruction": {
            "parts": [{"text": system_instruction_text}]
        }
    }
    
    model_name = body.model or "gemini-2.5-flash-lite"
    return StreamingResponse(stream_gemini(payload, model_name), media_type="text/plain")
