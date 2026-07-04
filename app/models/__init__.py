"""
Paquete de modelos SQLAlchemy para Focusly Workflows.

Este paquete contiene todos los modelos de base de datos organizados por dominio.
Proporciona dos formas de importar modelos:

1. Desde el módulo centralizado:
    from app.models.models import Task, User, Workspace

2. Directamente del paquete (recomendado):
    from app.models import Task, User, Workspace
"""

from app.modules.user.models.user import User
from app.modules.workspace.models.workspace import Workspace
from app.modules.ai.models.conversation import Conversation
from app.modules.ai.models.message import Message
from app.modules.ai.models.user_memory import UserMemory
from app.modules.task.models.time_block import TimeBlock
from app.modules.task.models.focus_session import FocusSession
from app.modules.notification.models.notification import Notification
from app.modules.task.models.tag import Tag
from app.modules.workspace.models.project_group import ProjectGroup
from app.modules.task.models.task import Task

__all__ = [
    # AI Models
    "Conversation",
    "Message",
    "UserMemory",
    # Focus Session Models
    "FocusSession",
    # Notification Models
    "Notification",
    # ProjectGroup Models
    "ProjectGroup",
    # Tag Models
    "Tag",
    # Task Models
    "Task",
    # TimeBlock Models
    "TimeBlock",
    # User Models
    "User",
    # Workspace Models
    "Workspace",
]
