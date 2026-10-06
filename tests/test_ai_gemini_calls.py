import asyncio
from types import SimpleNamespace

import pytest

from app.modules.ai.services import embeddings, memory, router, summarizer


def fake_client(delay: float, text: str = "simple"):
    """A genai client whose async calls take `delay` seconds."""

    async def generate_content(**kwargs):
        await asyncio.sleep(delay)
        return SimpleNamespace(text=text)

    async def embed_content(**kwargs):
        await asyncio.sleep(delay)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2])])

    models = SimpleNamespace(
        generate_content=generate_content, embed_content=embed_content
    )
    return SimpleNamespace(aio=SimpleNamespace(models=models))


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")

    def install(delay: float, text: str = "simple"):
        for module in (router, embeddings, memory, summarizer):
            monkeypatch.setattr(
                module.genai, "Client", lambda api_key: fake_client(delay, text)
            )

    return install


class TestGeminiCallsDontFreezeTheServer:
    @pytest.mark.anyio
    async def test_other_requests_keep_running_while_gemini_answers(self, gemini):
        gemini(0.2)
        ticks = 0

        async def other_request():
            nonlocal ticks
            for _ in range(10):
                await asyncio.sleep(0.01)
                ticks += 1

        result, _ = await asyncio.gather(router.classify_query("hola"), other_request())
        assert result == "simple"
        # The loop kept serving while classify_query waited on Gemini.
        assert ticks == 10

    @pytest.mark.anyio
    async def test_a_slow_gemini_is_given_up(self, gemini, monkeypatch):
        gemini(1.0)
        monkeypatch.setattr(router, "CLASSIFY_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(embeddings, "EMBEDDING_TIMEOUT_SECONDS", 0.05)
        assert await router.classify_query("hola") == "complex"
        assert await embeddings.generate_embedding("hola") == []

    @pytest.mark.anyio
    async def test_embeddings_come_back(self, gemini):
        gemini(0)
        assert await embeddings.generate_embedding("hola") == [0.1, 0.2]
