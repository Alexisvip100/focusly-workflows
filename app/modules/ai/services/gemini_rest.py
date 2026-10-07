import os

import httpx

# Background Gemini calls (memories, summaries) without the SDK: the version
# installed here can't cap the thinking, which newer models do by default and
# bill as output.

LIGHT_MODEL = os.getenv("AI_GEMINI_LIGHT_MODEL", "gemini-3.5-flash-lite").strip()
API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def no_thinking(model: str) -> dict[str, str | int]:
    """Gemini 2.x takes a token budget; Gemini 3 and later a level."""
    if model.startswith("gemini-2"):
        return {"thinkingBudget": 0}
    return {"thinkingLevel": "minimal"}


async def generate_text(
    prompt: str, *, timeout: float, model: str = LIGHT_MODEL
) -> str:
    """One answer from the light model, without thinking. Raises on errors."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            API_URL.format(model=model),
            params={"key": api_key},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"thinkingConfig": no_thinking(model)},
            },
            timeout=timeout,
        )
    response.raise_for_status()
    candidates = response.json().get("candidates") or []
    parts = (
        (candidates[0].get("content") or {}).get("parts") or [] if candidates else []
    )
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
