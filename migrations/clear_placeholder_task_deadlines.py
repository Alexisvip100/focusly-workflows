import argparse
import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


# Before deadlines could be NULL, a task created without a date got "now" as
# its deadline. Those placeholder dates make undated tasks look due on the day
# they were created, then overdue.
#
# Only Backlog tasks are touched: in the app, "Backlog without a start time"
# is the no-date inbox, so their deadline was never a date the user picked.
# A deadline within PLACEHOLDER_SECONDS of the creation time is treated as the
# placeholder. Run make_task_deadline_nullable.py first.
#
# Dry run by default (prints how many tasks match); pass --apply to change them.

PLACEHOLDER_SECONDS = 120

COUNT_SQL = """
    SELECT COUNT(*) FROM "Task"
    WHERE "deletedAt" IS NULL
      AND status = 'Backlog'
      AND deadline IS NOT NULL
      AND estimated_start_date IS NULL
      AND (source IS NULL OR source <> 'google')
      AND ABS(EXTRACT(EPOCH FROM (deadline - "createdAt"))) <= :seconds
"""

UPDATE_SQL = """
    UPDATE "Task" SET deadline = NULL
    WHERE "deletedAt" IS NULL
      AND status = 'Backlog'
      AND deadline IS NOT NULL
      AND estimated_start_date IS NULL
      AND (source IS NULL OR source <> 'google')
      AND ABS(EXTRACT(EPOCH FROM (deadline - "createdAt"))) <= :seconds
"""


async def migrate(apply: bool):
    async with engine.begin() as conn:
        params = {"seconds": PLACEHOLDER_SECONDS}
        count = (await conn.execute(text(COUNT_SQL), params)).scalar()
        if not apply:
            print(f"Dry run: {count} task(s) would lose their placeholder deadline")
            return
        await conn.execute(text(UPDATE_SQL), params)
    print(f"Migration applied: cleared {count} placeholder deadline(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true", help="change the tasks (default: dry run)"
    )
    args = parser.parse_args()
    try:
        asyncio.run(migrate(args.apply))
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)
