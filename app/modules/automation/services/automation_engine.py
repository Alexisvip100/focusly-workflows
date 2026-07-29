"""
automation_engine.py — Motor de automatización para el trigger on_save.

¿QUÉ hace?
  Cuando el workspace se guarda, este motor:
    1. Llama a todo_detector para encontrar ítems TODO en el contenido
    2. Por cada TODO:
       a. Calcula su hash SHA-256
       b. Busca en AutomationLog si ese hash ya fue procesado
       c. Si NO existe → crea una Task en la DB vinculada al workspace
       d. Guarda el hash en AutomationLog para no repetirlo
    3. Emite un evento Socket.io al frontend con los resultados
       ("se crearon N tareas automáticamente")

¿POR QUÉ está separado del detector?
  Separación de responsabilidades:
    - todo_detector.py → SOLO saber QUÉ hay en el texto
    - automation_engine.py → DECIDIR qué hacer y EJECUTAR

¿CUÁNDO se llama?
  Desde workspaces_service.py, al final del método `update()`,
  solo si el campo `content` fue parte del update.

Flujo completo:
  Usuario escribe "TODO: Revisar UI"
       ↓
  Workspace se guarda (debounce 1s)
       ↓
  workspaces_service.update() llama run_todo_automation()
       ↓
  todo_detector detecta "Revisar UI" con hash "abc123"
       ↓
  ¿Existe "abc123" en AutomationLog para este workspace? NO
       ↓
  Se crea Task(title="Revisar UI", workspaceId=ws.id, ...)
       ↓
  Se guarda AutomationLog(todoHash="abc123", taskId=new_task.id)
       ↓
  Socket.io emite "automation_triggered" al frontend
       ↓
  Frontend muestra toast: "⚡ 1 tarea creada automáticamente"
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.modules.task.models.task import Task
from app.modules.automation.models.automation_log import AutomationLog
from app.modules.automation.services.todo_detector import detect_todos
from app.sockets.realtime import realtime_gateway


async def run_todo_automation(
    workspace_id: str,
    user_id: str,
    content: str,
    db: AsyncSession,
) -> list[dict]:
    """
    Ejecuta la automatización TODO para un workspace recién guardado.

    Args:
        workspace_id : ID del workspace guardado
        user_id      : ID del usuario dueño del workspace
        content      : El contenido del workspace (JSON BlockNote)
        db           : Sesión de base de datos activa

    Returns:
        Lista de dicts con las tareas creadas:
        [{"taskId": "...", "taskTitle": "..."}]
        Vacía si no se creó ninguna tarea.
    """
    import logging
    logger = logging.getLogger("automation")

    # ─── DEBUG: Ver exactamente qué llega ────────────────────────────────────
    logger.warning(f"[AUTOMATION] workspace_id={workspace_id}")
    logger.warning(f"[AUTOMATION] content preview: {content[:300]}")
    # ─────────────────────────────────────────────────────────────────────────

    # ─── 1. Detectar todos los ítems TODO en el contenido ────────────────────
    todo_items = detect_todos(content)

    logger.warning(f"[AUTOMATION] todos detectados: {todo_items}")

    if not todo_items:
        return []  # No hay TODOs → nada que hacer

    created_tasks: list[dict] = []

    for todo in todo_items:

        # ─── 2. Verificar si este TODO ya fue procesado (anti-duplicado) ─────
        existing = await db.execute(
            select(AutomationLog).where(
                AutomationLog.workspaceId == workspace_id,
                AutomationLog.todoHash == todo.hash,
            )
        )
        if existing.scalars().first():
            # Ya fue procesado antes → skip
            continue

        # ─── 3. Crear la tarea en la DB ───────────────────────────────────────
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        new_task = Task(
            id=task_id,
            userId=user_id,
            workspaceId=workspace_id,          # Vinculada al workspace
            title=todo.text,
            notesEncrypted=f"## Creada automáticamente desde Workspace\n\n**TODO detectado:** {todo.text}",
            estimateTimer=1800,                 # 30 minutos por defecto
            realTimer=0.0,
            priorityLevel=2,                   # Medium por defecto
            category="General",
            color="#6366f1",                   # Indigo — color de automatización
            status="Backlog",
            deadline=now,
            use_ai=False,
            source="automation",               # Identifica tareas creadas por workflow
            notified=False,
            lastMinuteNotified=False,
            tags=[],
            links=[],
            collaborators=[],
            filters={},
            createdAt=now,
            updatedAt=now,
        )
        db.add(new_task)

        # ─── 4. Registrar en AutomationLog ────────────────────────────────────
        log_entry = AutomationLog(
            workspaceId=workspace_id,
            userId=user_id,
            todoHash=todo.hash,
            taskTitle=todo.text,
            taskId=task_id,
        )
        db.add(log_entry)

        created_tasks.append({
            "taskId": task_id,
            "taskTitle": todo.text,
        })

    if not created_tasks:
        return []

    # ─── 5. Commit de todos los cambios juntos ────────────────────────────────
    await db.commit()

    # ─── 6. Notificar al frontend vía Socket.io ───────────────────────────────
    # El frontend escucha el evento "automation_triggered" y muestra un toast
    try:
        await realtime_gateway.emit_automation_result(
            user_id=user_id,
            workspace_id=workspace_id,
            tasks_created=created_tasks,
        )
    except Exception:
        pass  # El socket nunca debe bloquear el guardado

    return created_tasks
