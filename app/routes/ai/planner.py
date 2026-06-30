from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from app.routes.common import get_current_user_id
from app.services.ai.planner import (
    AIPlannerService,
    TasksOrganizeResponse,
    CalendarPlannerResponse,
    WeeklyPlanResponse,
)

router = APIRouter(prefix="/ai/planner", tags=["ai-planner"])

def get_planner_service() -> AIPlannerService:
    return AIPlannerService()

# ─── Request Schemas ───────────────────────────────────────────────────────────

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

@router.post("/organize", response_model=TasksOrganizeResponse)
async def organize_tasks(
    body: OrganizeTasksRequest,
    planner: AIPlannerService = Depends(get_planner_service),
    current_user_id: str = Depends(get_current_user_id),
):
    try:
        plan = await planner.organize_tasks(body.tasks)
        return plan
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to organize tasks: {str(e)}")

@router.post("/calendar", response_model=CalendarPlannerResponse)
async def calendar_planner(
    body: CalendarPlannerRequest,
    planner: AIPlannerService = Depends(get_planner_service),
    current_user_id: str = Depends(get_current_user_id),
):
    try:
        plan = await planner.ai_calendar_planner(body.tasks, body.free_slots)
        return plan
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to plan calendar events: {str(e)}")

@router.post("/weekly", response_model=WeeklyPlanResponse)
async def weekly_planner(
    body: WeeklyPlannerRequest,
    planner: AIPlannerService = Depends(get_planner_service),
    current_user_id: str = Depends(get_current_user_id),
):
    try:
        availability = body.availability or {"working_hours": "09:00 - 18:00"}
        plan = await planner.weekly_planner(body.tasks, availability)
        return plan
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate weekly plan: {str(e)}")

@router.post("/improve")
async def task_improve(
    body: TaskImproveRequest,
    planner: AIPlannerService = Depends(get_planner_service),
    current_user_id: str = Depends(get_current_user_id),
):
    try:
        result = await planner.task_improve(body.title, body.description, body.mode)
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to suggest task improvements: {str(e)}")
