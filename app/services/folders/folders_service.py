import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from app.models.models import Folder, Workspace
from app.schemas.folders import FolderCreateSchema
from typing import Optional as Opt

class FoldersService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, create_input: Dict[str, Any], user_id: str) -> Folder:
        folder_id = str(uuid.uuid4())
        group_id = create_input.pop("groupId", None)
        folder_data = FolderCreateSchema(**create_input)
        
        folder = Folder(
            id=folder_id,
            userId=user_id,
            groupId=group_id,
            **folder_data.model_dump()
        )
        
        self.db.add(folder)
        await self.db.commit()
        await self.db.refresh(folder)
        return folder

    async def find_all(self, user_id: str, group_id: Opt[str] = None) -> List[Folder]:
        query = select(Folder).where(Folder.userId == user_id)
        if group_id is not None:
            query = query.where(Folder.groupId == group_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def find_one(self, id: str, user_id: str) -> Folder:
        result = await self.db.execute(select(Folder).where(Folder.id == id))
        folder = result.scalars().first()
        if not folder or folder.userId != user_id:
            raise ValueError(f"Folder with ID {id} not found")
        return folder

    async def update(self, id: str, update_input: Dict[str, Any], user_id: str) -> Folder:
        result = await self.db.execute(select(Folder).where(Folder.id == id))
        folder = result.scalars().first()
        if not folder or folder.userId != user_id:
            raise ValueError(f"Folder with ID {id} not found")

        if "name" in update_input:
            folder.name = update_input["name"]
        if "color" in update_input:
            folder.color = update_input["color"]
        if "groupId" in update_input:
            folder.groupId = update_input["groupId"]

        folder.updatedAt = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(folder)
        return folder

    async def remove(self, id: str, user_id: str) -> bool:
        result = await self.db.execute(select(Folder).where(Folder.id == id))
        folder = result.scalars().first()
        if not folder or folder.userId != user_id:
            raise ValueError(f"Folder with ID {id} not found")

        # Disassociate workspaces
        await self.db.execute(
            update(Workspace).where(Workspace.folderId == id).values(folderId=None, updatedAt=datetime.utcnow())
        )

        await self.db.delete(folder)
        await self.db.commit()
        return True

    async def get_total_folders(self, user_id: str) -> int:
        from sqlalchemy import func
        result = await self.db.execute(select(func.count(Folder.id)).where(Folder.userId == user_id))
        return result.scalar() or 0
