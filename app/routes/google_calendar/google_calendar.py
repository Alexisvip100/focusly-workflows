from fastapi import APIRouter, HTTPException, Depends, Header, Request, Body
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from app.database import get_db
from app.routes.common import get_current_user_id
from app.services.google_calendar.google_calendar_service import GoogleCalendarService

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
    user_id: str = Depends(get_current_user_id),
    gc_service: GoogleCalendarService = Depends(get_google_calendar_service)
):
    try:
        # 1. Ejecutar la sincronización (Incremental o Completa)
        await gc_service.sync_calendar(user_id)

        # 2. Obtener todas las tareas de tipo GoogleTask de la base de datos local
        user_tasks = await gc_service.tasks_service.find_all_by_user(user_id)
        google_tasks = [t for t in user_tasks if t.get("task_type") == "GoogleTask"]

        # 3. Normalizar y retornar en el formato esperado por el frontend
        mapped_events = []
        for t in google_tasks:
            mapped_events.append({
                "id": t["id"],
                "google_event_id": t["google_event_id"],
                "title": t["title"],
                "notes_encrypted": t["notesEncrypted"] or "",
                "deadline": t["deadline"] or "",
                "estimated_start_date": t["estimated_start_date"] or "",
                "estimated_end_date": t["estimated_end_date"],
                "status": t["status"],
                "priority_level": t["priorityLevel"] or 1,
                "tags": t["tags"] or [],
                "links": t["links"] or [],
                "estimate_timer": t["estimateTimer"] or 30,
                "task_type": t["task_type"],
                "is_all_day": False,
                "created_at": t["createdAt"] or "",
                "updated_at": t["updatedAt"] or "",
                "is_owner": t.get("is_owner", True)
            })

        return mapped_events
    except Exception as e:
        print("Error getting Google Calendar events:", e)
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
        return google_event
    except Exception as e:
        print("Error creating Google Calendar event:", e)
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
        return google_event
    except Exception as e:
        print("Error patching Google Calendar event:", e)
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
        return {"success": True}
    except Exception as e:
        print("Error deleting Google Calendar event:", e)
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
    print(f"Google Webhook received for user: {x_goog_channel_token}, state: {x_goog_resource_state}, channelId: {x_goog_channel_id}")

    if x_goog_resource_state == "sync":
        print(f"Channel {x_goog_channel_id} successfully synchronized.")
        return {"status": "synchronized"}

    if x_goog_resource_state == "exists":
        userId = x_goog_channel_token
        print(f"Triggering incremental sync for user: {userId}")
        
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
                    print(f"[WS] Emitted schedule_updated to user {userId} after Google webhook sync")
                except Exception as err:
                    print(f"Failed to execute incremental sync for user {userId} via webhook: {err}")

        # Start background task
        asyncio.create_task(run_sync_bg())
        return {"status": "sync_triggered"}

    return {"status": "processed"}
