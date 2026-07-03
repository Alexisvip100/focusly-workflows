"""
Centralizado de importación de todos los modelos SQLAlchemy.

Este archivo re-exporta todos los modelos de sus subcarpetas para proporcionar
una interfaz consistente y simplificada para importar modelos en toda la aplicación.

Uso:
    from app.models import Task, User, Workspace
    from app.models.models import Conversation, Message
"""

# AI Models
from app.models.AI.conversation import Conversation
from app.models.AI.message import Message
from app.models.AI.userMemory import UserMemory

# Focus Session Models
from app.models.FocusSession.focusSession import FocusSession

# Notification Models
from app.models.Notification.notification import Notification

# ProjectGroup Models
from app.models.ProjectGroup.projectGroup import ProjectGroup

# Tag Models
from app.models.Tag.tag import Tag

# Task Models
from app.models.Task.task import Task

# TimeBlock Models
from app.models.TimeBlock.timeBlock import TimeBlock

# User Models
from app.models.User.user import User

# Workspace Models
from app.models.Workspace.workspace import Workspace

# Export all models
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
