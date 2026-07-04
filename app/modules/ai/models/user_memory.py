from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, BigInteger, ForeignKey
from sqlalchemy.sql import func
from app.database import Base



class UserMemory(Base):
    __tablename__ = "UserMemory"

    id = Column(String, primary_key=True, index=True)
    userId = Column(String, nullable=False, index=True)
    memory = Column(String, nullable=False)
    category = Column(String, nullable=False)
    importance = Column(Integer, default=1, nullable=False)
    embedding = Column(JSON, nullable=True)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
