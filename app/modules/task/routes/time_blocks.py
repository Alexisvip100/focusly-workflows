from fastapi import APIRouter, HTTPException, Depends
from typing import Any
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routes.common import get_current_user_id
from app.modules.user.services.users_service import UsersService
from app.modules.task.repository import TasksRepository
from app.modules.task.services.time_blocks_service import TimeBlocksService

router = APIRouter(prefix="/time-blocks", tags=["time-blocks"])


class CreateTimeBlockSchema(BaseModel):
    userId: str | None = None
    taskId: str | None = None
    startTime: str
    endTime: str
    blockType: str
    externalEventId: str | None = None
    source: str
    title: str
    meetingUrl: str | None = None
    attendees: list[dict[str, Any]] | None = None


def get_time_blocks_service(db: AsyncSession = Depends(get_db)) -> TimeBlocksService:
    return TimeBlocksService(db)


def get_users_service(db: AsyncSession = Depends(get_db)) -> UsersService:
    return UsersService(db)


def get_tasks_repository(db: AsyncSession = Depends(get_db)) -> TasksRepository:
    return TasksRepository(db)


@router.post("", response_model=str)
async def create_time_block(
    body: CreateTimeBlockSchema,
    current_user_id: str = Depends(get_current_user_id),
    tb_service: TimeBlocksService = Depends(get_time_blocks_service),
    tasks_repository: TasksRepository = Depends(get_tasks_repository),
):
    if body.taskId:
        task = await tasks_repository.get_by_id(body.taskId)
        if not task:
            raise HTTPException(
                status_code=404, detail=f"Task with ID {body.taskId} not found"
            )
        if task.userId != current_user_id:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to link a task belonging to another user",
            )

    try:
        block_data = body.model_dump()
        block_data["userId"] = current_user_id
        block_id = await tb_service.create(block_data)
        return block_id
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=list[dict[str, Any]])
async def find_all_time_blocks(
    current_user_id: str = Depends(get_current_user_id),
    tb_service: TimeBlocksService = Depends(get_time_blocks_service),
    users_service: UsersService = Depends(get_users_service),
):
    current_user = await users_service.findOne(current_user_id)
    if current_user and current_user.role == "admin":
        return await tb_service.find_all()
    return await tb_service.find_all_by_user(current_user_id)


@router.get("/user/{userId}", response_model=list[dict[str, Any]])
async def find_all_by_user(
    userId: str,
    current_user_id: str = Depends(get_current_user_id),
    tb_service: TimeBlocksService = Depends(get_time_blocks_service),
    users_service: UsersService = Depends(get_users_service),
):
    if userId != current_user_id:
        current_user = await users_service.findOne(current_user_id)
        if not current_user or current_user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to view time blocks for this user",
            )
    return await tb_service.find_all_by_user(userId)


@router.get("/{id}", response_model=dict[str, Any])
async def find_time_block(
    id: str,
    current_user_id: str = Depends(get_current_user_id),
    tb_service: TimeBlocksService = Depends(get_time_blocks_service),
    users_service: UsersService = Depends(get_users_service),
):
    try:
        block = await tb_service.find_one(id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

    if block.get("userId") != current_user_id:
        current_user = await users_service.findOne(current_user_id)
        if not current_user or current_user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to access this time block",
            )
    return block
