from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.sql import func
from app.database import Base



class TimeBlock(Base):
    __tablename__ = "TimeBlock"

    id = Column(String, primary_key=True, index=True)
    userId = Column(String, nullable=False, index=True)
    taskId = Column(String, nullable=True)
    startTime = Column(DateTime, nullable=False)
    endTime = Column(DateTime, nullable=False)
    blockType = Column(String, nullable=False)
    externalEventId = Column(String, nullable=True)
    source = Column(String, nullable=False)
    title = Column(String, nullable=False)
    meetingUrl = Column(String, nullable=True)
    attendees = Column(JSON, nullable=True)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
