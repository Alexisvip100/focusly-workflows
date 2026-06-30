import httpx
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from app.routes.common import get_current_user_id
from app.config import settings

router = APIRouter(prefix="/ai/planner", tags=["ai-planner"])

# ─── Request/Response Schemas ───────────────────────────────────────────────────

class OrganizeTasksRequest(BaseModel):
    tasks: List[Dict[str, Any]]

class CalendarPlannerRequest(BaseModel):
    tasks: List[Dict[str, Any]]
    free_slots: List[Dict[str, Any]]

class WeeklyPlannerRequest(BaseModel):
    tasks: List[Dict[str, Any]]
    availability: Optional[Dict[str, Any]] = None

class TaskImproveRequest(BaseModel):
    title: str
    description: Optional[str] = ""
    mode: str  # subtasks, estimate, priority, all

# ─── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/organize")
async def organize_tasks(
    body: OrganizeTasksRequest,
    current_user_id: str = Depends(get_current_user_id),
):
    url = f"{settings.FOCUSLY_AI_URL}/ai/planner/organize"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json={"tasks": body.tasks}, timeout=30.0)
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"focusly-ai service returned code {r.status_code}")
            return r.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delegate tasks organization to focusly-ai: {str(e)}")

@router.post("/calendar")
async def calendar_planner(
    body: CalendarPlannerRequest,
    current_user_id: str = Depends(get_current_user_id),
):
    url = f"{settings.FOCUSLY_AI_URL}/ai/planner/calendar"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                url,
                json={"tasks": body.tasks, "free_slots": body.free_slots},
                timeout=30.0
            )
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"focusly-ai service returned code {r.status_code}")
            return r.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delegate calendar planning to focusly-ai: {str(e)}")

@router.post("/weekly")
async def weekly_planner(
    body: WeeklyPlannerRequest,
    current_user_id: str = Depends(get_current_user_id),
):
    url = f"{settings.FOCUSLY_AI_URL}/ai/planner/weekly"
    availability = body.availability or {"working_hours": "09:00 - 18:00"}
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                url,
                json={"tasks": body.tasks, "availability": availability},
                timeout=30.0
            )
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"focusly-ai service returned code {r.status_code}")
            return r.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delegate weekly planning to focusly-ai: {str(e)}")

@router.post("/improve")
async def task_improve(
    body: TaskImproveRequest,
    current_user_id: str = Depends(get_current_user_id),
):
    url = f"{settings.FOCUSLY_AI_URL}/ai/planner/improve"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                url,
                json={"title": body.title, "description": body.description, "mode": body.mode},
                timeout=30.0
            )
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"focusly-ai service returned code {r.status_code}")
            return r.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delegate task improvements to focusly-ai: {str(e)}")

