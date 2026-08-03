from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class Workspace(Base):
    __tablename__ = "Workspace"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    userId: Mapped[str] = mapped_column(String, nullable=False, index=True)
    taskId: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    emoji: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    background_color: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    card_show_background: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    groupId: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(String, nullable=False)
    saveStatus: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, default=False
    )
    createdAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
