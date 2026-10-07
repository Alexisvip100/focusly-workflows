import os
import re
import unicodedata
import uuid
import json
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import UserMemory
from app.modules.ai.repository import UserMemoryRepository
from .chat_payload import compact_attachments
from .embeddings import generate_embedding
from .gemini_rest import generate_text
from .prompts import MEMORY_EXTRACTION_PROMPT

# A background extra after each reply: never worth holding a request for.
GEMINI_TIMEOUT_SECONDS = 30
MAX_MESSAGE_CHARS = 2000
# Besides messages that look personal, every this many user messages.
EXTRACT_EVERY_N_MESSAGES = 6

# Phrases people use to tell something about themselves.
_PERSONAL = re.compile(
    r"\b("
    r"recuerda\w*|acuerdate|no olvides|me llamo|soy|trabajo|estudio|vivo|"
    r"prefiero|me gusta\w*|no me gusta\w*|odio|me encanta\w*|suelo|siempre|nunca|"
    r"mi (?:horario|trabajo|jefe|equipo|empresa|rutina|meta|objetivo)|"
    r"mis (?:horarios|metas|objetivos)|"
    r"remember|my name|i am|i'm|i work|i study|i live|i prefer|i like|"
    r"i don't like|i hate|i love|i usually|i always|i never|"
    r"my (?:schedule|job|boss|team|company|routine|goal)"
    r")\b"
)


def worth_extracting(message: str, user_message_count: int) -> bool:
    """Whether a message may hold something to remember about the user."""
    text = unicodedata.normalize("NFKD", (message or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    if _PERSONAL.search(compact_attachments(text)):
        return True
    return user_message_count > 0 and user_message_count % EXTRACT_EVERY_N_MESSAGES == 0


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


async def search_memories(
    user_id: str, query: str, db: AsyncSession, top_k: int = 5
) -> str:
    """
    Search relevant memories for a given query.
    """
    repo = UserMemoryRepository(db)
    all_memories = await repo.get_all_by_user(user_id)
    if not any(m.embedding for m in all_memories):
        return ""

    query_emb = await generate_embedding(compact_attachments(query)[:MAX_MESSAGE_CHARS])
    if not query_emb:
        return ""

    scored_memories = []
    for m in all_memories:
        if m.embedding:
            sim = cosine_similarity(query_emb, m.embedding)
            scored_memories.append((sim, m))

    # Sort by descending similarity
    scored_memories.sort(key=lambda x: x[0], reverse=True)

    top_memories = [m[1] for m in scored_memories[:top_k] if m[0] > 0.5]  # Threshold
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

    # Attached files are documents, not facts about the user.
    message = compact_attachments(message)[:MAX_MESSAGE_CHARS]
    if not message:
        return

    try:
        # Async, so the server keeps serving everyone else meanwhile.
        text = await generate_text(
            f"{MEMORY_EXTRACTION_PROMPT}\n\nUser Message: {message}",
            timeout=GEMINI_TIMEOUT_SECONDS,
        )

        # Parse JSON
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()

        memories = json.loads(text)
        if not isinstance(memories, list):
            return

        repo = UserMemoryRepository(db)
        try:
            for m in memories:
                category = m.get("type", "fact")
                content = m.get("content", "")
                if not content:
                    continue

                emb = await generate_embedding(content)

                new_memory = UserMemory(
                    id=str(uuid.uuid4()),
                    userId=user_id,
                    memory=content,
                    category=category,
                    importance=1,
                    embedding=emb,
                )
                await repo.create(new_memory)
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise e

    except Exception:
        pass
