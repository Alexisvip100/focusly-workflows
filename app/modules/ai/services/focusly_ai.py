import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# focusly-ai ends the reply with this character and the token usage as JSON
# when asked (include_usage). Never part of the model's text.
USAGE_MARKER = "\x1e"


def focusly_ai_headers() -> dict[str, str]:
    """focusly-ai only answers requests that carry the shared token."""
    token = settings.FOCUSLY_AI_INTERNAL_TOKEN
    return {"X-Internal-Token": token} if token else {}


class UsageTrailer:
    """Splits a focusly-ai stream into the reply text and the usage trailer,
    which may arrive split across chunks."""

    def __init__(self) -> None:
        self._in_trailer = False
        self._trailer = ""

    def feed(self, chunk: str) -> str:
        """The part of the chunk that is reply text."""
        if self._in_trailer:
            self._trailer += chunk
            return ""
        text, marker, rest = chunk.partition(USAGE_MARKER)
        if marker:
            self._in_trailer = True
            self._trailer = rest
        return text

    @property
    def usage(self) -> dict[str, Any] | None:
        if not self._trailer:
            return None
        try:
            usage = json.loads(self._trailer)
        except json.JSONDecodeError:
            logger.warning("Unreadable usage trailer from focusly-ai")
            return None
        return usage if isinstance(usage, dict) else None


def total_tokens(usage: dict[str, Any] | None) -> int:
    """What a reply cost: prompt, answer and thinking tokens."""
    if not usage:
        return 0
    return sum(int(usage.get(k) or 0) for k in ("input", "output", "thoughts"))
