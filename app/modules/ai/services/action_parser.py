import json
import re
from typing import Any

# Mirrors focusly-front/src/utils/lumina/lumina.ts — kept in sync so the
# server-side view of a message's action always agrees with what the
# frontend would have parsed out of the raw LLM text.
ACTION_PATTERN = re.compile(r"\[ACTION:\s*([A-Z_]+)\s*(\{.*?\})\]", re.DOTALL)


def extract_actions(text: str) -> list[dict[str, Any]]:
    """Extracts every `[ACTION: ...]` tag in the text, in order.

    A plan spanning several days/weeks (e.g. a month-long research plan)
    legitimately emits one tag per task — never assume there's only one.
    """
    actions: list[dict[str, Any]] = []
    for match in ACTION_PATTERN.finditer(text):
        action_type, payload_raw = match.groups()
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            continue
        actions.append({"type": action_type, "payload": payload})
    return actions


def strip_action_tag(text: str) -> str:
    return ACTION_PATTERN.sub("", text).strip()
