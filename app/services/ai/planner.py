import os
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from app.config import settings
from app.services.ai.prompts import (
    PLANNER_ORGANIZE_PROMPT,
    PLANNER_CALENDAR_PROMPT,
    PLANNER_WEEKLY_PROMPT,
    PLANNER_IMPROVE_SUBTASKS_PROMPT,
    PLANNER_IMPROVE_ESTIMATE_PROMPT,
    PLANNER_IMPROVE_PRIORITY_PROMPT,
    PLANNER_IMPROVE_ALL_PROMPT,
)

# ─── Pydantic schemas for Gemini Structured Output ──────────────────────────────

class TaskPlanItem(BaseModel):
    taskId: str
    recommendedPriority: str  # HIGH, MEDIUM, LOW
    suggestedOrder: int
    reason: str
    suggestedDate: Optional[str] = None
    estimatedTime: Optional[str] = None

class TasksOrganizeResponse(BaseModel):
    plan: List[TaskPlanItem]

class TimeBlockItem(BaseModel):
    taskId: Optional[str] = None
    title: str
    startTime: str  # ISO-8601 string
    endTime: str    # ISO-8601 string
    reason: str

class CalendarPlannerResponse(BaseModel):
    events: List[TimeBlockItem]

class WeeklyPlanDayItem(BaseModel):
    day: str  # Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday
    tasks: List[str]

class WeeklyPlanResponse(BaseModel):
    weeklyPlan: List[WeeklyPlanDayItem]
    recommendationSummary: str

class SubtasksResponse(BaseModel):
    subtasks: List[str]

class EstimatedTimeResponse(BaseModel):
    estimatedTime: str

class SuggestedPriorityResponse(BaseModel):
    suggestedPriority: str  # HIGH, MEDIUM, LOW

class ImproveAllResponse(BaseModel):
    subtasks: List[str]
    estimatedTime: str
    suggestedPriority: str


# ─── Service Class ─────────────────────────────────────────────────────────────

class AIPlannerService:
    def __init__(self):
        api_key = (
            settings.GOOGLE_GENERATIVE_AI_API_KEY
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY")
        )
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.5-flash"

    async def organize_tasks(self, tasks: List[Dict[str, Any]]) -> TasksOrganizeResponse:
        """
        Analyzes tasks and prioritizes them based on Urgency, Importance, Deadline, Effort, and Workload.
        Computes custom priorityScore = urgency + importance + deadlineFactor + effortFactor.
        """
        tasks_context = ""
        for i, t in enumerate(tasks):
            tasks_context += (
                f"- Task #{i+1} ID: {t.get('id')}\n"
                f"  Title: {t.get('title')}\n"
                f"  Description: {t.get('description') or 'No description'}\n"
                f"  Current Priority: {t.get('priority') or 'N/A'}\n"
                f"  Deadline: {t.get('deadline') or 'None'}\n"
                f"  Status: {t.get('status') or 'Todo'}\n"
                f"  Estimated Effort/Time: {t.get('estimatedTime') or 'N/A'}\n\n"
            )

        prompt = PLANNER_ORGANIZE_PROMPT.format(tasks_context=tasks_context)
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        # Parse output
        return TasksOrganizeResponse.model_validate_json(response.text)

    async def ai_calendar_planner(
        self, tasks: List[Dict[str, Any]], free_slots: List[Dict[str, Any]]
    ) -> CalendarPlannerResponse:
        """
        Fits tasks into available calendar slots (time blocking) without conflict.
        """
        tasks_context = "\n".join([
            f"- ID: {t.get('id')} | Title: {t.get('title')} | Duration: {t.get('duration') or '30 mins'} | Priority: {t.get('priority')}"
            for t in tasks
        ])
        
        slots_context = "\n".join([
            f"- Available Slot: {s.get('start')} to {s.get('end')}"
            for s in free_slots
        ])

        prompt = PLANNER_CALENDAR_PROMPT.format(tasks_context=tasks_context, slots_context=slots_context)
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        return CalendarPlannerResponse.model_validate_json(response.text)

    async def weekly_planner(
        self, tasks: List[Dict[str, Any]], availability: Dict[str, Any]
    ) -> WeeklyPlanResponse:
        """
        Generates a weekly schedule recommendation based on tasks and availability.
        """
        tasks_context = "\n".join([
            f"- Title: {t.get('title')} | Priority: {t.get('priority')} | Deadline: {t.get('deadline')}"
            for t in tasks
        ])

        prompt = PLANNER_WEEKLY_PROMPT.format(tasks_context=tasks_context, availability=availability)
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        return WeeklyPlanResponse.model_validate_json(response.text)

    async def task_improve(
        self, title: str, description: str, mode: str
    ) -> Any:
        """
        Suggests task improvements: breaking into subtasks, estimating duration, or predicting priority.
        """
        desc_info = f"Description: {description}" if description else "No description provided."
        
        if mode == "subtasks":
            prompt = PLANNER_IMPROVE_SUBTASKS_PROMPT.format(title=title, description=desc_info)
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SubtasksResponse,
                ),
            )
            return SubtasksResponse.model_validate_json(response.text)

        elif mode == "estimate":
            prompt = PLANNER_IMPROVE_ESTIMATE_PROMPT.format(title=title, description=desc_info)
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=EstimatedTimeResponse,
                ),
            )
            return EstimatedTimeResponse.model_validate_json(response.text)

        elif mode == "priority":
            prompt = PLANNER_IMPROVE_PRIORITY_PROMPT.format(title=title, description=desc_info)
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SuggestedPriorityResponse,
                ),
            )
            return SuggestedPriorityResponse.model_validate_json(response.text)

        else:  # mode == "all"
            prompt = PLANNER_IMPROVE_ALL_PROMPT.format(title=title, description=desc_info)
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ImproveAllResponse,
                ),
            )
            return ImproveAllResponse.model_validate_json(response.text)
