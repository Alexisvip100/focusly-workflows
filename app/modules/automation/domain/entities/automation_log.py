from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class AutomationLog(Base):
    __tablename__ = "AutomationLog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspaceId: Mapped[str] = mapped_column(String, nullable=False, index=True)
    userId: Mapped[str] = mapped_column(String, nullable=False, index=True)
    todoHash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    taskTitle: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    taskId: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
