"""
Paquete centralizado de modelos de dominio para Focusly Workflows (DDD).
"""

from app.modules.user.domain.entities.user import User
from app.modules.workspace.domain.entities.workspace import Workspace
from app.modules.workspace.domain.entities.project_group import ProjectGroup
from app.modules.ai.domain.entities.conversation import Conversation
from app.modules.ai.domain.entities.message import Message
from app.modules.ai.domain.entities.user_memory import UserMemory
from app.modules.task.domain.entities.time_block import TimeBlock
from app.modules.task.domain.entities.focus_session import FocusSession
from app.modules.task.domain.entities.tag import Tag
from app.modules.task.domain.entities.task import Task
from app.modules.notification.domain.entities.notification import Notification
from app.modules.automation.domain.entities.automation_log import AutomationLog

__all__ = [
    # AI Entities
    "Conversation",
    "Message",
    "UserMemory",
    # Automation Entities
    "AutomationLog",
    # Focus Session Entities
    "FocusSession",
    # Notification Entities
    "Notification",
    # ProjectGroup Entities
    "ProjectGroup",
    # Tag Entities
    "Tag",
    # Task Entities
    "Task",
    # TimeBlock Entities
    "TimeBlock",
    # User Entities
    "User",
    # Workspace Entities
    "Workspace",
]
