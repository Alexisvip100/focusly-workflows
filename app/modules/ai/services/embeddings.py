import asyncio
import os
from google import genai

EMBEDDING_TIMEOUT_SECONDS = 10


async def generate_embedding(text: str) -> list[float]:
    """
    Generates a 768-dimensional float array embedding for a text using text-embedding-004.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return []

    client = genai.Client(api_key=api_key)
    try:
        # Async client: the sync one froze the whole server while it waited.
        response = await asyncio.wait_for(
            client.aio.models.embed_content(
                model="text-embedding-004",
                contents=text,
            ),
            timeout=EMBEDDING_TIMEOUT_SECONDS,
        )
        return response.embeddings[0].values
    except Exception:
        return []
