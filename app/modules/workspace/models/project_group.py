from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from app.database import Base



class ProjectGroup(Base):
    __tablename__ = "ProjectGroup"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    userId = Column(String, nullable=False, index=True)
    color = Column(String, nullable=True)
    emoji = Column(String, nullable=True)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
