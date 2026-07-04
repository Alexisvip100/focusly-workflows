from fastapi import APIRouter, HTTPException, Depends
from typing import Any
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.task.services.time_blocks_service import TimeBlocksService

router = APIRouter(prefix="/time-blocks", tags=["time-blocks"])

class CreateTimeBlockSchema(BaseModel):
    userId: str
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

@router.post("", response_model=str)
async def create_time_block(
    body: CreateTimeBlockSchema,
    tb_service: TimeBlocksService = Depends(get_time_blocks_service)
):
    try:
        block_id = await tb_service.create(body.model_dump())
        return block_id
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("", response_model=list[dict[str, Any]])
async def find_all_time_blocks(
    tb_service: TimeBlocksService = Depends(get_time_blocks_service)
):
    return await tb_service.find_all()

@router.get("/{id}", response_model=dict[str, Any])
async def find_time_block(
    id: str,
    tb_service: TimeBlocksService = Depends(get_time_blocks_service)
):
    try:
        return await tb_service.find_one(id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/user/{userId}", response_model=list[dict[str, Any]])
async def find_all_by_user(
    userId: str,
    tb_service: TimeBlocksService = Depends(get_time_blocks_service)
):
    return await tb_service.find_all_by_user(userId)
