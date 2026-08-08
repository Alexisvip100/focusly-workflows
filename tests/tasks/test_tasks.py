import pytest
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

class PriorityLevel:
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    URGENT = "URGENT"

class TaskStatus:
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"

@dataclass
class Task:
    id: str
    title: str
    description: Optional[str] = None
    priority: str = PriorityLevel.MEDIUM
    status: str = TaskStatus.TODO
    estimated_minutes: int = 30
    created_at: datetime = field(default_factory=datetime.utcnow)
    def __post_init__(self):
        # Validation rules applied upon task instantiation
        if not self.title or not self.title.strip():
            raise ValueError("Task title cannot be empty")
        if self.estimated_minutes <= 0:
            raise ValueError("Estimated time must be greater than 0 minutes")
    def mark_completed(self):
        """Transitions the task status to COMPLETED."""
        self.status = TaskStatus.COMPLETED
    def update_status(self, new_status: str):
        """Updates the status to a new valid state."""
        valid_statuses = {TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED}
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid status: {new_status}")
        self.status = new_status
        