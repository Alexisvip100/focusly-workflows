from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base



class Workspace(Base):
    __tablename__ = "Workspace"

    id = Column(String, primary_key=True, index=True)
    userId = Column(String, nullable=False, index=True)
    taskId = Column(String, nullable=True)
    title = Column(String, nullable=False)
    emoji = Column(String, nullable=True)
    background_color = Column(String, nullable=True)
    card_show_background = Column(Boolean, nullable=True)
    groupId = Column(String, nullable=True)
    content = Column(String, nullable=False)
    saveStatus = Column(Boolean, nullable=True, default=False)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
