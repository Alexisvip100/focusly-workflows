from sqlalchemy import Column, String
from app.database import Base



class Tag(Base):
    __tablename__ = "Tag"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    userId = Column(String, nullable=True)
