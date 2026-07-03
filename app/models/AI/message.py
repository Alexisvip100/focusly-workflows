from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, BigInteger, ForeignKey
from sqlalchemy.sql import func
from app.database import Base



class Message(Base):
    __tablename__ = "Message"

    id = Column(String, primary_key=True, index=True)
    conversationId = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    tokenUsage = Column(Integer, nullable=True, default=0)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
