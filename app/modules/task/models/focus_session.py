from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class FocusSession(Base):
    __tablename__ = "FocusSession"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    userId: Mapped[str] = mapped_column(String, nullable=False, index=True)
    taskId: Mapped[str] = mapped_column(String, nullable=False)
    startedAt: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    endedAt: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    durationMinutes: Mapped[int] = mapped_column(Integer, nullable=False)
    distractionCount: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    wasSuccessful: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    createdAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
