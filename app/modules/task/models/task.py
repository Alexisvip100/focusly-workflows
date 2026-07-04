from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON
from sqlalchemy.sql import func
from app.database import Base



class Task(Base):
    __tablename__ = "Task"

    id = Column(String, primary_key=True, index=True)
    userId = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    notesEncrypted = Column(String, nullable=False)
    estimateTimer = Column(Integer, nullable=True)
    realTimer = Column(Float, nullable=True)
    duration = Column(DateTime, nullable=True)
    priorityLevel = Column(Integer, nullable=False, default=2)
    category = Column(String, nullable=True)
    color = Column(String, nullable=True)
    estimated_start_date = Column(DateTime, nullable=True)
    estimated_end_date = Column(DateTime, nullable=True)
    deadline = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="Todo")
    completedAt = Column(DateTime, nullable=True)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    deletedAt = Column(DateTime, nullable=True)
    tags = Column(JSON, nullable=True)
    filters = Column(JSON, nullable=True)
    links = Column(JSON, nullable=True)
    task_type = Column(String, nullable=True)
    google_event_id = Column(String, nullable=True, index=True)
    source = Column(String, nullable=True)
    sync_status = Column(String, nullable=True)
    collaborators = Column(JSON, nullable=True)
    notified = Column(Boolean, nullable=True, default=False)
    lastMinuteNotified = Column(Boolean, nullable=True, default=False)
    use_ai = Column(Boolean, nullable=True, default=False)
    workspaceId = Column(String, nullable=True)
    is_owner = Column(Boolean, nullable=True, default=False)
  