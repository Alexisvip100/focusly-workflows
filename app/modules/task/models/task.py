from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class Task(Base):
    __tablename__ = "Task"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    userId: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    notesEncrypted: Mapped[str] = mapped_column(String, nullable=False)
    estimateTimer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    realTimer: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    priorityLevel: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    estimated_start_date: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    estimated_end_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="Todo")
    completedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    deletedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tags: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    filters: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    links: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    task_type: Mapped[str | None] = mapped_column(String, nullable=True)
    google_event_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    sync_status: Mapped[str | None] = mapped_column(String, nullable=True)
    collaborators: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    notified: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    lastMinuteNotified: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=False
    )
    use_ai: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    workspaceId: Mapped[str | None] = mapped_column(String, nullable=True)
    is_owner: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
