import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(
            text('ALTER TABLE "Task" ADD COLUMN IF NOT EXISTS time_logs JSON')
        )
    print("Migration applied: Task.time_logs")


if __name__ == "__main__":
    try:
        asyncio.run(migrate())
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)
