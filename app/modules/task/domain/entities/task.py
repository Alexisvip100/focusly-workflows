from datetime import datetime
from typing import Any, Optional

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
    estimateTimer: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    realTimer: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    priorityLevel: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    estimated_start_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    estimated_end_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="Todo")
    completedAt: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    deletedAt: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    tags: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    filters: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    links: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    task_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    google_event_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=True
    )
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sync_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    collaborators: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    notified: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, default=False
    )
    lastMinuteNotified: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, default=False
    )
    use_ai: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, default=False
    )
    workspaceId: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_owner: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, default=False
    )
