import os

from google import genai


def generate_embedding(text: str) -> list[float]:
    """
    Generates a 768-dimensional float array embedding for a text using text-embedding-004.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return []

    client = genai.Client(api_key=api_key)
    try:
        response = client.models.embed_content(
            model="text-embedding-004",
            contents=text,
        )
        return response.embeddings[0].values
    except Exception as e:
        print(f"Embedding error: {e}")
        return []
