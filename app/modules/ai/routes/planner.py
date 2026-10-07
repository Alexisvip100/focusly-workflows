import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from typing import Any
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.modules.ai.services.focusly_ai import focusly_ai_headers
from app.modules.billing.plans import FREE_AI_MESSAGE_LIMIT, is_pro
from app.modules.billing.services.usage_service import (
    consume_ai_message,
    refund_ai_message,
)
from app.modules.user.domain.entities.user import User
from app.routes.common import get_current_user_id

router = APIRouter(prefix="/ai/planner", tags=["ai-planner"])

# Each planner call is a Gemini request like a chat message: on the free plan
# it counts toward the same FREE_AI_MESSAGE_LIMIT.
PLANNER_TIMEOUT_SECONDS = 60.0

# ─── Request/Response Schemas ───────────────────────────────────────────────────


class OrganizeTasksRequest(BaseModel):
    tasks: list[dict[str, Any]]


class CalendarPlannerRequest(BaseModel):
    tasks: list[dict[str, Any]]
    free_slots: list[dict[str, Any]]


class WeeklyPlannerRequest(BaseModel):
    tasks: list[dict[str, Any]]
    availability: dict[str, Any] | None = None


class TaskImproveRequest(BaseModel):
    title: str
    description: str | None = ""
    mode: str  # subtasks, estimate, priority, all


# ─── Delegation ───────────────────────────────────────────────────────────────


async def _delegate(
    path: str,
    payload: dict[str, Any],
    *,
    what: str,
    user_id: str,
    db: AsyncSession,
    response: Response,
) -> Any:
    """Checks the plan, then asks focusly-ai. A failed call gives the free
    message back."""
    remaining: int | None = None
    if not is_pro(await db.get(User, user_id)):
        used = await consume_ai_message(db, user_id)
        if used is None:
            raise HTTPException(
                status_code=402,
                detail={"code": "free_limit_reached", "limit": FREE_AI_MESSAGE_LIMIT},
            )
        remaining = FREE_AI_MESSAGE_LIMIT - used

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{settings.FOCUSLY_AI_URL}/ai/planner/{path}",
                json=payload,
                headers=focusly_ai_headers(),
                timeout=PLANNER_TIMEOUT_SECONDS,
            )
        if r.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"focusly-ai service returned code {r.status_code}",
            )
        result = r.json()
    except Exception as e:
        if remaining is not None:
            await refund_ai_message(db, user_id)
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delegate {what} to focusly-ai: {str(e)}",
        )

    if remaining is not None:
        response.headers["X-AI-Messages-Remaining"] = str(remaining)
    return result


# ─── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/organize")
async def organize_tasks(
    body: OrganizeTasksRequest,
    response: Response,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await _delegate(
        "organize",
        {"tasks": body.tasks},
        what="tasks organization",
        user_id=current_user_id,
        db=db,
        response=response,
    )


@router.post("/calendar")
async def calendar_planner(
    body: CalendarPlannerRequest,
    response: Response,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await _delegate(
        "calendar",
        {"tasks": body.tasks, "free_slots": body.free_slots},
        what="calendar planning",
        user_id=current_user_id,
        db=db,
        response=response,
    )


@router.post("/weekly")
async def weekly_planner(
    body: WeeklyPlannerRequest,
    response: Response,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await _delegate(
        "weekly",
        {
            "tasks": body.tasks,
            "availability": body.availability or {"working_hours": "09:00 - 18:00"},
        },
        what="weekly planning",
        user_id=current_user_id,
        db=db,
        response=response,
    )


@router.post("/improve")
async def task_improve(
    body: TaskImproveRequest,
    response: Response,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await _delegate(
        "improve",
        {"title": body.title, "description": body.description, "mode": body.mode},
        what="task improvements",
        user_id=current_user_id,
        db=db,
        response=response,
    )
