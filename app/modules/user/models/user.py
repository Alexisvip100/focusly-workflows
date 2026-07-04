from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, BigInteger, ForeignKey
from sqlalchemy.sql import func
from app.database import Base



class User(Base):
    __tablename__ = "User"

    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    picture = Column(String, nullable=True)
    role = Column(String, nullable=True)
    bio = Column(String, nullable=True)
    passwordHash = Column(String, nullable=True)
    authProvider = Column(String, nullable=True)
    googleRefreshToken = Column(String, nullable=True)
    subscriptionStatus = Column(String, default="free", nullable=False)
    settings = Column(JSON, nullable=True)
    externalId = Column(String, nullable=True)
    fcmToken = Column(String, nullable=True)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    lastSyncAt = Column(DateTime, nullable=True)
    googleCalendarSyncToken = Column(String, nullable=True)
    googleChannelId = Column(String, nullable=True)
    googleResourceId = Column(String, nullable=True)
    googleChannelExpiration = Column(BigInteger, nullable=True)
