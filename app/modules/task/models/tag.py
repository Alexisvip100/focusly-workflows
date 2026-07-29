from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Tag(Base):
    __tablename__ = "Tag"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    userId: Mapped[str | None] = mapped_column(String, nullable=True)
