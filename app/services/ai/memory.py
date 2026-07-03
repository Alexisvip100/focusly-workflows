import os
import uuid
import json
import numpy as np
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from google import genai
from app.models import UserMemory
from .embeddings import generate_embedding
from .prompts import MEMORY_EXTRACTION_PROMPT

def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    a_arr = np.array(a)
    b_arr = np.array(b)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))

async def search_memories(user_id: str, query: str, db: AsyncSession, top_k: int = 5) -> str:
    """
    Search relevant memories for a given query.
    """
    query_emb = generate_embedding(query)
    if not query_emb:
        return ""
        
    result = await db.execute(select(UserMemory).filter(UserMemory.userId == user_id))
    all_memories = result.scalars().all()
    
    scored_memories = []
    for m in all_memories:
        if m.embedding:
            sim = cosine_similarity(query_emb, m.embedding)
            scored_memories.append((sim, m))
            
    # Sort by descending similarity
    scored_memories.sort(key=lambda x: x[0], reverse=True)
    
    top_memories = [m[1] for m in scored_memories[:top_k] if m[0] > 0.5] # Threshold
    if not top_memories:
        return ""
        
    context_str = "Important things to remember about the user:\n"
    for m in top_memories:
        context_str += f"- [{m.category}] {m.memory}\n"
    return context_str

async def extract_and_save_memory(user_id: str, message: str, db: AsyncSession):
    """
    Extracts memory from a message using Gemini and saves to DB.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return
        
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"{MEMORY_EXTRACTION_PROMPT}\n\nUser Message: {message}",
        )
        
        # Parse JSON
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()
            
        memories = json.loads(text)
        if not isinstance(memories, list):
            return
            
        for m in memories:
            category = m.get("type", "fact")
            content = m.get("content", "")
            if not content:
                continue
                
            emb = generate_embedding(content)
            
            new_memory = UserMemory(
                id=str(uuid.uuid4()),
                userId=user_id,
                memory=content,
                category=category,
                importance=1,
                embedding=emb
            )
            db.add(new_memory)
            
        await db.commit()
    except Exception as e:
        pass
