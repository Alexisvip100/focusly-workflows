from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "User"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    picture: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    passwordHash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    authProvider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    googleRefreshToken: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subscriptionStatus: Mapped[str] = mapped_column(
        String, default="free", nullable=False
    )
    settings: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    externalId: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    fcmToken: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    lastSyncAt: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    googleCalendarSyncToken: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    googleChannelId: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    googleResourceId: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    googleChannelExpiration: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
