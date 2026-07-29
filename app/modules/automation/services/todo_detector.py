"""
todo_detector.py — Detector de ítems TODO en el contenido de un Workspace.

¿QUÉ hace?
  El workspace guarda su contenido como un JSON de BlockNote (lista de bloques).
  Este módulo extrae el TEXTO PLANO de esos bloques y busca patrones TODO.

¿QUÉ patrones detecta?
  1. "TODO: Revisar el diseño"   → prefijo explícito TODO:
  2. "- [ ] Revisar el diseño"   → checkbox markdown (estilo GitHub)
  3. "☐ Revisar el diseño"       → símbolo unicode de checkbox vacío

¿QUÉ devuelve?
  Una lista de objetos TodoItem con:
    - text  : el texto limpio del TODO (sin el prefijo)
    - hash  : SHA-256 del texto, usado para detectar duplicados

¿POR QUÉ usamos hash?
  Si el usuario guarda el mismo workspace dos veces sin cambiar el TODO,
  el hash ya estará en AutomationLog → no creamos tarea duplicada.

Ejemplo:
  content = '[{"type": "paragraph", "content": [{"text": "TODO: Diseñar el login"}]}]'
  detectar_todos(content)
  → [TodoItem(text="Diseñar el login", hash="a3f9...")]
"""

import json
import re
import hashlib
from dataclasses import dataclass


@dataclass
class TodoItem:
    text: str  # Texto limpio del TODO (lo que se usará como título de tarea)
    hash: str  # SHA-256 del texto → para deduplicación


# Patrones que reconocemos como TODO
_PATTERNS = [
    re.compile(r"^TODO:\s*(.+)", re.IGNORECASE),  # TODO: texto
    re.compile(r"^-\s*\[\s*\]\s*(.+)"),  # - [ ] texto
    re.compile(r"^☐\s*(.+)"),  # ☐ texto (unicode checkbox)
]


def _extract_text_from_block(block: dict) -> str:
    """
    Extrae el texto plano de un bloque BlockNote.

    BlockNote guarda cada bloque así:
      {
        "type": "paragraph",
        "content": [
          {"type": "text", "text": "Hola mundo"},
          {"type": "text", "text": " más texto"}
        ]
      }

    También puede tener bloques anidados en "children".
    Esta función extrae todo el texto concatenado.
    """
    parts = []

    # Texto directo en content
    content = block.get("content", [])
    if isinstance(content, list):
        for inline in content:
            if isinstance(inline, dict) and inline.get("type") == "text":
                parts.append(inline.get("text", ""))

    # Bloques anidados (por ejemplo, items dentro de una lista)
    children = block.get("children", [])
    if isinstance(children, list):
        for child in children:
            parts.append(_extract_text_from_block(child))

    return " ".join(p for p in parts if p).strip()


def _make_hash(text: str) -> str:
    """Genera un hash SHA-256 del texto para usarlo como ID de deduplicación."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def detect_todos(content: str) -> list[TodoItem]:
    """
    Punto de entrada principal.

    Args:
        content: El campo `content` del Workspace tal como viene de la DB.
                 Puede ser:
                   - JSON string de BlockNote: '[{"type":"paragraph",...}]'
                   - Texto plano (fallback por si acaso)
                   - Cadena vacía / None

    Returns:
        Lista de TodoItem encontrados. Vacía si no hay nada.
    """
    if not content or not content.strip():
        return []

    # Intentar parsear como JSON de BlockNote
    try:
        blocks = json.loads(content)
        if not isinstance(blocks, list):
            return []
    except (json.JSONDecodeError, TypeError):
        # Si no es JSON, tratarlo como texto plano línea por línea
        blocks = [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            for line in content.splitlines()
        ]

    todos: list[TodoItem] = []

    for block in blocks:
        if not isinstance(block, dict):
            continue

        line = _extract_text_from_block(block).strip()
        if not line:
            continue

        # Comprobar cada patrón
        for pattern in _PATTERNS:
            match = pattern.match(line)
            if match:
                task_title = match.group(1).strip()
                if task_title:
                    todos.append(
                        TodoItem(
                            text=task_title,
                            hash=_make_hash(task_title),
                        )
                    )
                break  # Un bloque → máximo un TODO

    return todos
