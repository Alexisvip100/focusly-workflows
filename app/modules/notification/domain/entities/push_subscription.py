from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class PushSubscription(Base):
    """One browser or installed app that receives a user's push notifications
    while Focusly is closed. The endpoint (the push service's URL for that
    device) identifies it; p256dh and auth are the keys its payloads are
    encrypted with."""

    __tablename__ = "PushSubscription"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    userId: Mapped[str] = mapped_column(String, nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String, nullable=False)
    auth: Mapped[str] = mapped_column(String, nullable=False)
    userAgent: Mapped[str | None] = mapped_column(String, nullable=True)
    # The device's IANA time zone ("America/Mexico_City"), so pushes meant
    # for a time of day (the morning summary) arrive at the user's hour.
    timeZone: Mapped[str | None] = mapped_column(String, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
