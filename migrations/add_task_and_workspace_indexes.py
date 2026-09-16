import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine

async def run_migration():
    async with engine.begin() as conn:
        print("Creating index ix_Workspace_taskId...")
        await conn.execute(text('CREATE INDEX IF NOT EXISTS "ix_Workspace_taskId" ON "Workspace" ("taskId");'))
        
        print("Creating index ix_Workspace_groupId...")
        await conn.execute(text('CREATE INDEX IF NOT EXISTS "ix_Workspace_groupId" ON "Workspace" ("groupId");'))

        print("Creating index ix_Task_workspaceId...")
        await conn.execute(text('CREATE INDEX IF NOT EXISTS "ix_Task_workspaceId" ON "Task" ("workspaceId");'))

        print("Creating index ix_Task_active_user...")
        await conn.execute(text('CREATE INDEX IF NOT EXISTS "ix_Task_active_user" ON "Task" ("userId", "createdAt" DESC) WHERE "deletedAt" IS NULL;'))

    print("Indexes created successfully.")


async def run_downgrade():
    async with engine.begin() as conn:
        print("Dropping index ix_Task_active_user...")
        await conn.execute(text('DROP INDEX IF EXISTS "ix_Task_active_user";'))

        print("Dropping index ix_Task_workspaceId...")
        await conn.execute(text('DROP INDEX IF EXISTS "ix_Task_workspaceId";'))

        print("Dropping index ix_Workspace_groupId...")
        await conn.execute(text('DROP INDEX IF EXISTS "ix_Workspace_groupId";'))

        print("Dropping index ix_Workspace_taskId...")
        await conn.execute(text('DROP INDEX IF EXISTS "ix_Workspace_taskId";'))

    print("Indexes dropped successfully.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--downgrade", "-d", "downgrade"):
        asyncio.run(run_downgrade())
    else:
        asyncio.run(run_migration())

