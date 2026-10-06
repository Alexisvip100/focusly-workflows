from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.plans import FREE_AI_MESSAGE_LIMIT
from app.modules.user.domain.entities.user import User

# Free AI messages, counted on the user row so deleting conversations (or
# clearing the browser) doesn't give them back.


async def consume_ai_message(db: AsyncSession, user_id: str) -> int | None:
    """Counts one free AI message. Returns the new total, or None when the
    limit was already reached. One statement, so two tabs sending at once
    can't both get the last message."""
    used = func.coalesce(User.aiMessagesUsed, 0)
    result = await db.execute(
        update(User)
        .where(User.id == user_id, used < FREE_AI_MESSAGE_LIMIT)
        .values(aiMessagesUsed=used + 1)
        .returning(User.aiMessagesUsed)
        .execution_options(synchronize_session=False)
    )
    new_total = result.scalar_one_or_none()
    await db.commit()
    return new_total


async def refund_ai_message(db: AsyncSession, user_id: str) -> None:
    """Gives back a message counted for a request that was then rejected."""
    used = func.coalesce(User.aiMessagesUsed, 0)
    await db.execute(
        update(User)
        .where(User.id == user_id, used > 0)
        .values(aiMessagesUsed=used - 1)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
