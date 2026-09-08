import json
import re
from typing import Any


def fallback_extract_payload(action_type: str, raw_segment: str) -> dict[str, Any] | None:
    """Fallback extractor when raw_segment contains unescaped quotes inside JSON strings."""
    try:
        if action_type == "CREATE_WORKSPACE":
            title_m = re.search(r'"title"\s*:\s*"([^"]+)"', raw_segment)
            title = title_m.group(1) if title_m else "Espacio de Trabajo"

            content = ""
            content_idx = raw_segment.find('"content": "')
            if content_idx != -1:
                start_content = content_idx + len('"content": "')
                pg_idx = raw_segment.find('"project_group_id"')
                if pg_idx != -1:
                    before_pg = raw_segment[:pg_idx].rstrip()
                    if before_pg.endswith(","):
                        before_pg = before_pg[:-1].rstrip()
                    if before_pg.endswith('"'):
                        before_pg = before_pg[:-1]
                    content = before_pg[start_content:]
                else:
                    end_idx = raw_segment.rfind("}]")
                    if end_idx == -1:
                        end_idx = raw_segment.rfind("}")
                    if end_idx != -1:
                        before_end = raw_segment[:end_idx].rstrip()
                        if before_end.endswith('"'):
                            before_end = before_end[:-1]
                        content = before_end[start_content:]
                    else:
                        content = raw_segment[start_content:]

                content = content.replace(r"\n", "\n").replace(r'\"', '"').replace(r"\\", "\\")

            pg_m = re.search(r'"project_group_id"\s*:\s*"([^"]+)"', raw_segment)
            pg_id = pg_m.group(1) if pg_m else None

            payload: dict[str, Any] = {"title": title, "content": content}
            if pg_id:
                payload["project_group_id"] = pg_id
            return payload

        if action_type == "CREATE_TASK":
            title_m = re.search(r'"title"\s*:\s*"([^"]+)"', raw_segment)
            title = title_m.group(1) if title_m else "Nueva Tarea"

            timer_m = re.search(r'"estimate_timer"\s*:\s*(\d+)', raw_segment)
            estimate_timer = int(timer_m.group(1)) if timer_m else 30

            prio_m = re.search(r'"priority_level"\s*:\s*(\d+)', raw_segment)
            priority_level = int(prio_m.group(1)) if prio_m else 1

            dl_m = re.search(r'"deadline"\s*:\s*"([^"]+)"', raw_segment)
            deadline = dl_m.group(1) if dl_m else None

            notes = ""
            notes_idx = raw_segment.find('"notes_encrypted": "')
            if notes_idx != -1:
                start_notes = notes_idx + len('"notes_encrypted": "')
                end_idx = raw_segment.rfind("}]")
                if end_idx == -1:
                    end_idx = raw_segment.rfind("}")
                if end_idx != -1:
                    before_end = raw_segment[:end_idx].rstrip()
                    if before_end.endswith('"'):
                        before_end = before_end[:-1]
                    notes = before_end[start_notes:]
                else:
                    notes = raw_segment[start_notes:]
                notes = notes.replace(r"\n", "\n").replace(r'\"', '"').replace(r"\\", "\\")

            payload = {
                "title": title,
                "estimate_timer": estimate_timer,
                "priority_level": priority_level,
                "notes_encrypted": notes,
            }
            if deadline:
                payload["deadline"] = deadline
            return payload

    except Exception:
        pass
    return None


def extract_actions(text: str) -> list[dict[str, Any]]:
    """Extracts every `[ACTION: ...]` tag in the text, in order.

    Uses balanced brace counting to properly support nested objects and arrays,
    falling back to resilient regex-based extraction if unescaped quotes or missing
    brackets occur.
    """
    actions: list[dict[str, Any]] = []
    action_prefix = "[ACTION:"
    cursor = 0

    while cursor < len(text):
        start_idx = text.find(action_prefix, cursor)
        if start_idx == -1:
            break

        after_prefix = start_idx + len(action_prefix)
        brace_start = text.find("{", after_prefix)
        if brace_start == -1:
            break

        action_type = text[after_prefix:brace_start].strip()
        if not action_type:
            cursor = brace_start + 1
            continue

        depth = 0
        in_string = False
        escape = False
        brace_end = -1

        for i in range(brace_start, len(text)):
            char = text[i]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        brace_end = i
                        break

        if brace_end == -1:
            direct_close = text.find("}]", brace_start)
            if direct_close != -1:
                brace_end = direct_close

        tag_end = -1
        if brace_end != -1:
            tag_end = text.find("]", brace_end)
            if tag_end == -1:
                tag_end = brace_end
        else:
            conv_match = re.search(r'"(?:\s*\}|)\s*\]?\s*\n\n(?=[¡¿A-Za-z])', text[brace_start:])
            next_action = text.find(action_prefix, brace_start)
            if conv_match and (next_action == -1 or conv_match.start() < next_action - brace_start):
                tag_end = brace_start + conv_match.start() + len(conv_match.group(0)) - 2
                brace_end = brace_start + conv_match.start()
            elif next_action != -1:
                tag_end = next_action
                brace_end = tag_end

        if brace_end == -1 or tag_end == -1:
            break

        payload_raw = text[brace_start : brace_end + 1]
        try:
            payload = json.loads(payload_raw)
            actions.append({"type": action_type, "payload": payload})
        except json.JSONDecodeError:
            fallback = fallback_extract_payload(action_type, payload_raw)
            if fallback:
                actions.append({"type": action_type, "payload": fallback})

        cursor = tag_end + 1

    return actions


def strip_action_tag(text: str) -> str:
    """Strips every `[ACTION: ...]` tag from text cleanly and aggressively,

    ensuring no internal action protocols, JSON blocks, or unclosed tags
    ever leak to the user.
    """
    # 1. Standard tags ending in }]
    cleaned = re.sub(r"\[ACTION:\s*[A-Z_]+[\s\S]*?\}\]", "", text)
    # 2. Tags ending in } followed by newline or next action
    cleaned = re.sub(r"\[ACTION:\s*[A-Z_]+[\s\S]*?\}(?=\s*(?:\n|$|\[ACTION:))", "", cleaned)
    # 3. Tags that ended at a known field followed by conversational text
    cleaned = re.sub(
        r'\[ACTION:\s*[A-Z_]+[\s\S]*?(?="project_group_id":\s*"[^"]*")"project_group_id":\s*"[^"]*"',
        "",
        cleaned,
    )
    # 4. Any unclosed [ACTION: ... ending before a double newline and conversational text
    cleaned = re.sub(r"\[ACTION:\s*[A-Z_]+[\s\S]*?\n\n(?=[¡¿A-Za-z#*])", "", cleaned)
    # 5. Any residual unclosed [ACTION: ... reaching the end of the text
    cleaned = re.sub(r"\[ACTION:\s*[A-Z_]+[\s\S]*$", "", cleaned)
    # 6. Clean up orphan closing tokens
    cleaned = re.sub(r"^\s*\}\]\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*\}\]\s*", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
