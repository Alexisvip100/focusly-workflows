from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, BigInteger, ForeignKey
from sqlalchemy.sql import func
from app.database import Base



class FocusSession(Base):
    __tablename__ = "FocusSession"

    id = Column(String, primary_key=True, index=True)
    userId = Column(String, nullable=False, index=True)
    taskId = Column(String, nullable=False)
    startedAt = Column(DateTime, nullable=False)
    endedAt = Column(DateTime, nullable=False)
    durationMinutes = Column(Integer, nullable=False)
    distractionCount = Column(Integer, nullable=False, default=0)
    wasSuccessful = Column(Boolean, nullable=False, default=True)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
