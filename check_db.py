import asyncio

from sqlalchemy import select

from app.database import async_session_local
from app.models.models import Folder, ProjectGroup, Workspace


async def main():
    async with async_session_local() as session:
        # Check Project Groups
        result = await session.execute(select(ProjectGroup))
        groups = result.scalars().all()
        print("--- PROJECT GROUPS ---")
        for g in groups:
            print(f"ID: {g.id}, Name: {g.name}, UserID: {g.userId}")

        # Check Folders
        result = await session.execute(select(Folder))
        folders = result.scalars().all()
        print("\n--- FOLDERS ---")
        for f in folders:
            print(f"ID: {f.id}, Name: {f.name}, GroupID: {f.groupId}")

        # Check Workspaces
        result = await session.execute(select(Workspace))
        workspaces = result.scalars().all()
        print("\n--- WORKSPACES ---")
        for w in workspaces:
            print(
                f"ID: {w.id}, Title: {w.title}, FolderID: {w.folderId}, GroupID: {w.groupId}"
            )


if __name__ == "__main__":
    asyncio.run(main())
