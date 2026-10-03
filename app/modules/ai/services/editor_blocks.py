"""Blocks the workspace editor's assistant wraps document text in.

The frontend (focusly-front src/api/AI/editorAssistant.ts) defines the same
markers. A block carries text for the editor's diff review: a whole revised
document or one rewritten fragment. That text belongs in the document, not in
the conversation history, where it would be stored and re-sent every turn.
"""

import re

EDIT_START = "<<<FOCUSLY_PROPOSED_EDIT>>>"
EDIT_END = "<<<END_PROPOSED_EDIT>>>"
REPLACEMENT_START = "<<<FOCUSLY_REPLACEMENT>>>"
REPLACEMENT_END = "<<<END_REPLACEMENT>>>"

# Stored in place of a reply that was nothing but a block.
EDIT_PLACEHOLDER = "✏️"

_BLOCK_PATTERNS = [
    re.compile(re.escape(start) + r"[\s\S]*?(?:" + re.escape(end) + r"|$)")
    for start, end in ((EDIT_START, EDIT_END), (REPLACEMENT_START, REPLACEMENT_END))
]


# A user message quoting part of the document ends in a fence labeled
# `selection` or `before-cursor` (see the frontend's buildScopedMessage).
_QUOTED_FRAGMENT = re.compile(
    r"\n\n(`{3,})(?:selection|before-cursor)\n[\s\S]*?\n\1\s*$"
)


def editor_message_preview(content: str, limit: int = 90) -> str:
    """A one-line preview of a user message, without its quoted fragment."""
    text = _QUOTED_FRAGMENT.sub("", content)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def strip_editor_blocks(text: str) -> str:
    """The reply without its editor blocks (an unterminated block runs to the end)."""
    stripped = text
    for pattern in _BLOCK_PATTERNS:
        stripped = pattern.sub("", stripped)
    stripped = stripped.strip()
    if not stripped and stripped != text.strip():
        return EDIT_PLACEHOLDER
    return stripped
