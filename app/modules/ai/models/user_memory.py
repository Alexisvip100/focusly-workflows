from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class UserMemory(Base):
    __tablename__ = "UserMemory"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    userId: Mapped[str] = mapped_column(String, nullable=False, index=True)
    memory: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
