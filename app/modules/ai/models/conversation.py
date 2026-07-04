from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from app.database import Base



class Conversation(Base):
    __tablename__ = "Conversation"

    id = Column(String, primary_key=True, index=True)
    userId = Column(String, nullable=False, index=True)
    title = Column(String, nullable=True)
    summary = Column(String, nullable=True)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
