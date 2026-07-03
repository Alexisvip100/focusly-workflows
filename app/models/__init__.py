"""
Paquete de modelos SQLAlchemy para Focusly Workflows.

Este paquete contiene todos los modelos de base de datos organizados por dominio.
Proporciona dos formas de importar modelos:

1. Desde el módulo centralizado:
    from app.models.models import Task, User, Workspace

2. Directamente del paquete (recomendado):
    from app.models import Task, User, Workspace
"""

from app.models.models import (
    # AI Models
    Conversation,
    Message,
    UserMemory,
    # Focus Session Models
    FocusSession,
    # Notification Models
    Notification,
    # ProjectGroup Models
    ProjectGroup,
    # Tag Models
    Tag,
    # Task Models
    Task,
    # TimeBlock Models
    TimeBlock,
    # User Models
    User,
    # Workspace Models
    Workspace,
)

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
