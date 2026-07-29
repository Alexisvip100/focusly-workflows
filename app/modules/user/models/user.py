from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "User"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    picture: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    bio: Mapped[str | None] = mapped_column(String, nullable=True)
    passwordHash: Mapped[str | None] = mapped_column(String, nullable=True)
    authProvider: Mapped[str | None] = mapped_column(String, nullable=True)
    googleRefreshToken: Mapped[str | None] = mapped_column(String, nullable=True)
    subscriptionStatus: Mapped[str] = mapped_column(
        String, default="free", nullable=False
    )
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    externalId: Mapped[str | None] = mapped_column(String, nullable=True)
    fcmToken: Mapped[str | None] = mapped_column(String, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    lastSyncAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    googleCalendarSyncToken: Mapped[str | None] = mapped_column(String, nullable=True)
    googleChannelId: Mapped[str | None] = mapped_column(String, nullable=True)
    googleResourceId: Mapped[str | None] = mapped_column(String, nullable=True)
    googleChannelExpiration: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
