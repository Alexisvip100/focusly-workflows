from fastapi import APIRouter, HTTPException, Depends, Header, Request, Body
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from app.database import get_db
from app.routes.common import get_current_user_id
from app.services.google_calendar.google_calendar_service import GoogleCalendarService
from sqlalchemy import select
from app.models import User
from app.sockets.realtime import realtime_gateway

router = APIRouter(prefix="/google-calendar", tags=["google-calendar"])

def get_google_calendar_service(db: AsyncSession = Depends(get_db)) -> GoogleCalendarService:
    from app.services.auth.auth_service import AuthService
    from app.services.tasks.tasks_service import TasksService
    from app.services.scheduler.scheduler_service import SchedulerService
    from app.sockets.realtime import realtime_gateway

    auth_serv = AuthService(db)
    tasks_serv = TasksService(db, socket_server=realtime_gateway)
    sched_serv = SchedulerService()
    
    gc_service = GoogleCalendarService(
        db=db,
        auth_service=auth_serv,
        tasks_service=tasks_serv,
        scheduler_service=sched_serv
    )
    
    tasks_serv.google_calendar_service = gc_service
    return gc_service

@router.get("/events", response_model=List[Dict[str, Any]])
async def get_events(
    timeMin: Optional[str] = None,
    timeMax: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
    gc_service: GoogleCalendarService = Depends(get_google_calendar_service)
):
    try:
        # 1. Run calendar sync (performs cleanup and updates watches/synced tasks, but does NOT persist new events)
        await gc_service.sync_calendar(user_id)

        # 2. Fetch user's email to determine is_owner
        user_res = await gc_service.db.execute(select(User).where(User.id == user_id))
        user = user_res.scalars().first()
        user_email = user.email if user else None

        # 3. Query Google Calendar directly (read-only, not persisting)
        events_data = await gc_service.get_events(user_id, time_min=timeMin, time_max=timeMax)
        items = events_data.get("items", [])

        mapped_events = []
        for item in items:
            if item.get("status") == "cancelled":
                continue
            
            processed = gc_service._process_google_event(item, user_email=user_email)
            mapped_events.append({
                "id": processed["id"],
                "google_event_id": processed["google_event_id"],
                "title": processed["title"],
                "notes_encrypted": processed["notes_encrypted"] or "",
                "deadline": processed["deadline"] or "",
                "estimated_start_date": processed["estimated_start_date"] or "",
                "estimated_end_date": processed["estimated_end_date"],
                "status": processed["status"],
                "priority_level": processed["priority_level"] or 1,
                "tags": processed["tags"] or [],
                "links": processed["links"] or [],
                "estimate_timer": processed["estimate_timer"] or 30,
                "task_type": processed["task_type"],
                "is_all_day": processed.get("is_all_day", False),
                "created_at": item.get("created") or "",
                "updated_at": item.get("updated") or "",
                "is_owner": processed.get("is_owner", True)
            })

        return mapped_events
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to retrieve Google Calendar events")

@router.post("/events")
async def create_event(
    event: Dict[str, Any] = Body(...),
    user_id: str = Depends(get_current_user_id),
    gc_service: GoogleCalendarService = Depends(get_google_calendar_service)
):
    try:
        # Crear en Google Calendar
        google_event = await gc_service.create_event(user_id, event)
        # Forzar sincronización inmediata
        await gc_service.sync_calendar(user_id)
        # Notify client via WebSocket
        await realtime_gateway.emitScheduleUpdate(user_id, {"source": "google_calendar_create"})
        return google_event
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to create Google Calendar event")

@router.patch("/events/{id}")
async def patch_event(
    id: str,
    event: Dict[str, Any] = Body(...),
    user_id: str = Depends(get_current_user_id),
    gc_service: GoogleCalendarService = Depends(get_google_calendar_service)
):
    try:
        # Actualizar en Google Calendar
        google_event = await gc_service.patch_event(user_id, id, event)
        # Forzar sincronización inmediata
        await gc_service.sync_calendar(user_id)
        # Notify client via WebSocket
        await realtime_gateway.emitScheduleUpdate(user_id, {"source": "google_calendar_patch"})
        return google_event
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to patch Google Calendar event")

@router.delete("/events/{id}")
async def remove_event(
    id: str,
    user_id: str = Depends(get_current_user_id),
    gc_service: GoogleCalendarService = Depends(get_google_calendar_service)
):
    try:
        # Eliminar en Google Calendar
        await gc_service.delete_event(user_id, id)
        # Forzar sincronización inmediata
        await gc_service.sync_calendar(user_id)
        # Notify client via WebSocket
        await realtime_gateway.emitScheduleUpdate(user_id, {"source": "google_calendar_delete"})
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to delete Google Calendar event")

@router.post("/webhook")
async def handle_google_webhook(
    request: Request,
    x_goog_channel_id: str = Header(None, alias="x-goog-channel-id"),
    x_goog_resource_id: str = Header(None, alias="x-goog-resource-id"),
    x_goog_channel_token: str = Header(None, alias="x-goog-channel-token"),
    x_goog_resource_state: str = Header(None, alias="x-goog-resource-state"),
    db: AsyncSession = Depends(get_db)
):
    if x_goog_resource_state == "sync":
        return {"status": "synchronized"}

    if x_goog_resource_state == "exists":
        userId = x_goog_channel_token
        
        # Async background sync to prevent Google timeout
        async def run_sync_bg():
            # Since get_db gives session in dependency, we create a new session or run with request db session
            # However, running with request db session might get closed if request ends.
            # To be safe, we can instantiate a new session from async_session_local
            from app.database import async_session_local
            async with async_session_local() as local_db:
                from app.services.auth.auth_service import AuthService
                from app.services.tasks.tasks_service import TasksService
                from app.services.scheduler.scheduler_service import SchedulerService
                from app.sockets.realtime import realtime_gateway

                auth_serv = AuthService(local_db)
                tasks_serv = TasksService(local_db, socket_server=realtime_gateway)
                sched_serv = SchedulerService()
                
                gc_service_bg = GoogleCalendarService(
                    db=local_db,
                    auth_service=auth_serv,
                    tasks_service=tasks_serv,
                    scheduler_service=sched_serv
                )
                tasks_serv.google_calendar_service = gc_service_bg
                
                try:
                    await gc_service_bg.sync_calendar(userId)
                    # Notify frontend via WebSocket so it re-fetches Google events in real-time
                    await realtime_gateway.emitScheduleUpdate(userId, {"source": "google_calendar_webhook"})
                except Exception as err:
                    pass

        # Start background task
        asyncio.create_task(run_sync_bg())
        return {"status": "sync_triggered"}

    return {"status": "processed"}
