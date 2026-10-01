from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.config import settings

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
    pool_recycle=1800,
)

# Create session factory
async_session_local = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Declarative base
Base = declarative_base()


# Dependency to get db session
async def get_db():
    async with async_session_local() as session:
        try:
            yield session
        finally:
            await session.close()


from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator


@asynccontextmanager
async def transaction_scope(db: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    """Ensures an atomic transaction block. Uses savepoints (begin_nested)
    if a transaction is already active, or begins a new transaction if not.
    Commits automatically on normal exit, and rolls back on exception.
    """
    if db.in_transaction():
        async with db.begin_nested():
            yield db
    else:
        async with db.begin():
            yield db


from typing import Any


def safe_attr(instance: Any, key: str, default: Any = None) -> Any:
    """Safely retrieves an attribute from a model instance without triggering
    SQLAlchemy's synchronous lazy loader (_load_expired) which crashes with
    MissingGreenlet in async environments.
    """
    if instance is None:
        return default
    if isinstance(instance, dict):
        return instance.get(key, default)
    from sqlalchemy import inspect
    state = inspect(instance, raiseerr=False)
    if state and (state.expired or key in state.unloaded or key in state.expired_attributes):
        return default
    return getattr(instance, key, default)

