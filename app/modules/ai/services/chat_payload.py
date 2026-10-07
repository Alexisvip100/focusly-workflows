import re
from typing import Any

from .action_parser import extract_actions, strip_action_tag

# What the model sees of the conversation. The summarizer folds older
# messages into Conversation.summary, so the stored ones are the recent part;
# of those, the last few go whole and the older ones shortened: attached files
# and action payloads were already acted on, so a mention of them is enough.
HISTORY_WINDOW = 20
FULL_RECENT_MESSAGES = 4
OLD_MESSAGE_CHARS = 900
MAX_ACTIONS_LISTED = 8

_FILE_BLOCK = re.compile(
    r"(?:===|---)\s*ATTACHED FILE:\s*([^\n\r]+?)\s*(?:===|---)\n?[\s\S]*?"
    r"(?:(?:===|---)\s*END OF FILE\s*(?:===|---)|$)",
    re.IGNORECASE,
)


def has_attachments(text: str) -> bool:
    return "ATTACHED FILE:" in (text or "")


def compact_attachments(text: str) -> str:
    """Attached files as a one-line mention: they were read on their turn."""
    return _FILE_BLOCK.sub(
        lambda m: f"[Attached file: {m.group(1).strip()} — already reviewed]",
        text or "",
    ).strip()


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _action_label(action: dict[str, Any]) -> str:
    payload = action.get("payload") or {}
    name = payload.get("title") or payload.get("name") or payload.get("id") or ""
    return (
        f"{action.get('type')} «{_truncate(str(name), 60)}»"
        if name
        else str(action.get("type"))
    )


def compact_assistant_message(text: str) -> str:
    """An older reply: its words, shortened, and which actions it proposed."""
    actions = extract_actions(text or "")
    body = _truncate(strip_action_tag(text or ""), OLD_MESSAGE_CHARS)
    if not actions:
        return body
    labels = [_action_label(a) for a in actions[:MAX_ACTIONS_LISTED]]
    if len(actions) > MAX_ACTIONS_LISTED:
        labels.append(f"+{len(actions) - MAX_ACTIONS_LISTED} more")
    return f"{body}\n(Proposed actions: {'; '.join(labels)})".strip()


def compact_user_message(text: str) -> str:
    return _truncate(compact_attachments(text), OLD_MESSAGE_CHARS)


def build_history(messages: list[tuple[str, str]]) -> list[dict[str, str]]:
    """The conversation for the model: the last HISTORY_WINDOW messages, the
    older ones shortened, starting with the user and without two turns of the
    same role in a row (Claude rejects that; Gemini handles it worse)."""
    window = [(r, c) for r, c in messages if (c or "").strip()][-HISTORY_WINDOW:]
    cut = len(window) - FULL_RECENT_MESSAGES

    history: list[dict[str, str]] = []
    for i, (role, content) in enumerate(window):
        role = "user" if role == "user" else "assistant"
        if i < cut:
            content = (
                compact_user_message(content)
                if role == "user"
                else compact_assistant_message(content)
            )
        if not history and role != "user":
            continue
        if history and history[-1]["role"] == role:
            history[-1]["content"] += "\n\n" + content
        else:
            history.append({"role": role, "content": content})
    return history
