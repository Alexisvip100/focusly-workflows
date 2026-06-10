import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import async_session_local
from app.graphql.queries import Query
from app.models.models import User
from sqlalchemy.future import select

class DummyInfo:
    def __init__(self, db, user_id):
        self.context = {
            "db": db,
            "user_id": user_id
        }

async def main():
    async with async_session_local() as db:
        user_res = await db.execute(select(User))
        user = user_res.scalars().first()
        if not user:
            print("No user found")
            return

        query_resolver = Query()
        info = DummyInfo(db, user.id)

        # Let's test the resolver get_tasks_by_user without filters
        print("\n--- RESOLVER WITHOUT FILTERS ---")
        tasks = await query_resolver.get_tasks_by_user(info, user.id)
        for t in tasks:
            print(f"Task: {t.title}, estimated_start_date: {t.estimated_start_date}, deadline: {t.deadline}")

        # Let's test the resolver get_tasks_by_user with filters
        # resembling the frontend's monthly dateRange for June 2026:
        # start: 2026-05-25T00:00:00.000Z
        # end: 2026-07-07T23:59:59.000Z
        from app.graphql import types
        import strawberry

        # We construct filters object
        # Since strawberry types might have constructor or field types
        filters = types.TaskFilterInput(
            status=None,
            priorityLevel=None,
            category=None,
            startDate="2026-05-25T00:00:00.000Z",
            endDate="2026-07-07T23:59:59.000Z",
            searchTerm=None
        )

        print("\n--- RESOLVER WITH FILTERS ---")
        try:
            tasks_filtered = await query_resolver.get_tasks_by_user(info, user.id, filters=filters)
            for t in tasks_filtered:
                print(f"Task: {t.title}, estimated_start_date: {t.estimated_start_date}, deadline: {t.deadline}")
        except Exception as e:
            print(f"Error calling resolver: {e}")

if __name__ == "__main__":
    asyncio.run(main())
