from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class TimeBlock(Base):
    __tablename__ = "TimeBlock"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    userId: Mapped[str] = mapped_column(String, nullable=False, index=True)
    taskId: Mapped[str | None] = mapped_column(String, nullable=True)
    startTime: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    endTime: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    blockType: Mapped[str] = mapped_column(String, nullable=False)
    externalEventId: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    meetingUrl: Mapped[str | None] = mapped_column(String, nullable=True)
    attendees: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
