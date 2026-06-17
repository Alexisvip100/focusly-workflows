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
    
class Workspace(Base):
    __tablename__ = "Workspace"

    id = Column(String, primary_key=True, index=True)
    userId = Column(String, nullable=False, index=True)
    taskId = Column(String, nullable=True)
    title = Column(String, nullable=False)
    emoji = Column(String, nullable=True)
    background_color = Column(String, nullable=True)
    card_show_background = Column(Boolean, nullable=True)
    folderId = Column(String, nullable=True)
    groupId = Column(String, nullable=True)
    content = Column(String, nullable=False)
    saveStatus = Column(Boolean, nullable=True, default=False)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

class Folder(Base):
    __tablename__ = "Folder"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    userId = Column(String, nullable=False, index=True)
    color = Column(String, nullable=True)
    groupId = Column(String, nullable=True)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

class ProjectGroup(Base):
    __tablename__ = "ProjectGroup"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    userId = Column(String, nullable=False, index=True)
    color = Column(String, nullable=True)
    emoji = Column(String, nullable=True)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

class Tag(Base):
    __tablename__ = "Tag"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    userId = Column(String, nullable=True)

class Notification(Base):
    __tablename__ = "Notification"

    id = Column(String, primary_key=True, index=True)
    userId = Column(String, nullable=False, index=True)
    relatedTaskId = Column(String, nullable=True)
    type = Column(String, nullable=False)
    scheduledAt = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="pending")
    title = Column(String, nullable=False)
    body = Column(String, nullable=False)
    createdAt = Column(DateTime, default=func.now(), nullable=False)
    updatedAt = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

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
