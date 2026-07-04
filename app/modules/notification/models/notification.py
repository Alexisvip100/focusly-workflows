from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, BigInteger, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class Notification(Base):
    __tablename__ = "Notification"

    id = Column(String, primary_key=True, index=True)
    userId = Column(String, nullable=False, index=True)
    relatedTaskId = Column(String, nullable=True)
    type = Column(String, nullable=False)
    scheduledAt = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="pending")
    title = Column(String, nullable=False)
    body = Column(String, nullable=False)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
