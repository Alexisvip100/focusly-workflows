from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.canvas.repository import CanvasRepository

# What Lumina reads of a document's canvases: the words on them. A drawing is
# mostly shapes and coordinates, so only its text goes into the prompt, in
# reading order, and capped so one large canvas can't crowd out the rest.
MAX_CHARS_PER_CANVAS = 4000
MAX_CHARS_TOTAL = 12000
# Text on about the same line reads left to right
_LINE_HEIGHT = 24


def scene_text(data: Any) -> list[str]:
    """The text of an Excalidraw scene, top to bottom and left to right:
    text boxes, labels inside shapes and on arrows, and frame names."""
    elements = (data or {}).get("elements") if isinstance(data, dict) else None
    if not isinstance(elements, list):
        return []
    found: list[tuple[float, float, str]] = []
    for el in elements:
        if not isinstance(el, dict) or el.get("isDeleted"):
            continue
        if el.get("type") == "text":
            text = el.get("originalText") or el.get("text")
        elif el.get("type") in ("frame", "magicframe"):
            text = el.get("name")
        else:
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        found.append((el.get("y") or 0, el.get("x") or 0, " ".join(text.split())))
    # Rows: what starts within a line's height of a row's first text joins it
    found.sort(key=lambda item: item[0])
    rows: list[list[tuple[float, float, str]]] = []
    for item in found:
        if rows and item[0] - rows[-1][0][0] < _LINE_HEIGHT:
            rows[-1].append(item)
        else:
            rows.append([item])
    lines: list[str] = []
    for row in rows:
        for _, _, text in sorted(row, key=lambda item: item[1]):
            if text not in lines:
                lines.append(text)
    return lines


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def document_canvases_text(
    db: AsyncSession, workspace_id: str, user_id: str
) -> str:
    """The text of the user's canvases in one of their documents, as a block
    for Lumina's context. Empty when the document has none with text."""
    canvases = await CanvasRepository(db).get_all_by_workspace(workspace_id, user_id)
    blocks: list[str] = []
    used = 0
    for canvas in canvases:
        lines = scene_text(canvas.data)
        if not lines:
            continue
        name = f"{canvas.icon or '🎨'} {canvas.name}"
        body = _clip("\n".join(f"- {line}" for line in lines), MAX_CHARS_PER_CANVAS)
        block = (
            f'Canvas "{name}" (linked in the document as [{name}](#canvas-{canvas.id})):\n'
            f"{body}\n"
        )
        if used + len(block) > MAX_CHARS_TOTAL:
            blocks.append(f"({len(canvases) - len(blocks)} more canvases not included)\n")
            break
        blocks.append(block)
        used += len(block)
    if not blocks:
        return ""
    return (
        "\n\n--- CANVASES IN THIS DOCUMENT ---\n"
        "The text written on the drawings (whiteboards) of this document, in "
        "reading order. They're part of the document: use them when the user "
        "asks about it.\n" + "\n".join(blocks)
    )
