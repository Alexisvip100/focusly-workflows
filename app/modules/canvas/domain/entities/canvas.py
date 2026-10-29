from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class Canvas(Base):
    __tablename__ = "Canvas"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    userId: Mapped[str] = mapped_column(String, nullable=False, index=True)
    workspaceId: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # An emoji shown before the name; unset means the default one.
    icon: Mapped[str | None] = mapped_column(String, nullable=True)
    # Excalidraw scene: {"elements": [...], "appState": {...}}. JSONB on
    # Postgres; plain JSON elsewhere so the SQLite test databases can build it.
    data: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    # When its preview (a small picture of the drawing) was last replaced;
    # unset while it has none. Also tells clients when to reload it.
    previewAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
