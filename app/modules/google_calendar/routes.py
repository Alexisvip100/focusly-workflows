import logging
from fastapi import APIRouter, HTTPException, Depends, Header, Request, Body
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from app.database import get_db, safe_attr
from app.routes.common import get_current_user_id
from app.modules.google_calendar.services.google_calendar_service import (
    GoogleCalendarService,
)
from app.sockets.realtime import realtime_gateway
from app.modules.user.repository import UsersRepository
from app.redis import cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/google-calendar", tags=["google-calendar"])


def build_google_calendar_service(db: AsyncSession) -> GoogleCalendarService:
    from app.modules.auth.services.auth_service import AuthService
    from app.modules.task.services.tasks_service import TasksService
    from app.modules.task.services.scheduler_service import SchedulerService

    auth_serv = AuthService(db)
    tasks_serv = TasksService(db, socket_server=realtime_gateway)
    sched_serv = SchedulerService()

    gc_service = GoogleCalendarService(
        db=db,
        auth_service=auth_serv,
        tasks_service=tasks_serv,
        scheduler_service=sched_serv,
    )

    tasks_serv.google_calendar_service = gc_service
    return gc_service


def get_google_calendar_service(
    db: AsyncSession = Depends(get_db),
) -> GoogleCalendarService:
    return build_google_calendar_service(db)


# A sync from loading the calendar runs at most this often per user; Google's
# webhook syncs right away whenever something actually changes.
SYNC_THROTTLE_SECONDS = 60
_background_syncs: set[asyncio.Task] = set()


async def _sync_in_background(user_id: str, notify: bool) -> None:
    from app.database import async_session_local

    async with async_session_local() as local_db:
        try:
            await build_google_calendar_service(local_db).sync_calendar(user_id)
            if notify:
                # The frontend re-fetches the Google events in real time.
                await realtime_gateway.emitScheduleUpdate(
                    user_id, {"source": "google_calendar_webhook"}
                )
        except Exception as e:
            logger.warning("Calendar sync failed for user %s: %s", user_id, e)


async def start_background_sync(
    user_id: str, *, notify: bool = False, throttle: bool = True
) -> bool:
    """Sync without making anyone wait for it. With `throttle`, skipped if
    one started for this user in the last SYNC_THROTTLE_SECONDS (several
    tabs or views loading at once used to run several full syncs)."""
    if throttle:
        taken = await cache.acquire_lock(f"gcal:sync:{user_id}", SYNC_THROTTLE_SECONDS)
        if taken is False:
            return False
    task = asyncio.create_task(_sync_in_background(user_id, notify))
    _background_syncs.add(task)
    task.add_done_callback(_background_syncs.discard)
    return True


def event_attendees(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Everyone invited to an event, with their answer."""
    return [
        {
            "email": a["email"],
            "responseStatus": a.get("responseStatus"),
            "self": bool(a.get("self")),
            "organizer": bool(a.get("organizer")),
        }
        for a in item.get("attendees") or []
        if isinstance(a, dict) and a.get("email")
    ]


@router.get("/events", response_model=list[dict[str, Any]])
async def get_events(
    timeMin: str | None = None,
    timeMax: str | None = None,
    user_id: str = Depends(get_current_user_id),
    gc_service: GoogleCalendarService = Depends(get_google_calendar_service),
):
    try:
        user = await UsersRepository(gc_service.db).get_by_id(user_id)
        if not user or not safe_attr(user, "googleRefreshToken"):
            return []

        # 1. Sync behind the response (cleanup, synced tasks, the push watch):
        # it pages through the whole calendar, and waiting for it is what made
        # this request take minutes after connecting Google.
        await start_background_sync(user_id)

        user_email = safe_attr(user, "email")

        # 2. Query Google Calendar directly (read-only, not persisting)
        events_data = await gc_service.get_events(
            user_id, time_min=timeMin, time_max=timeMax
        )
        items = events_data.get("items", [])

        mapped_events = []
        for item in items:
            if item.get("status") == "cancelled":
                continue

            processed = gc_service._process_google_event(item, user_email=user_email)
            mapped_events.append(
                {
                    "id": processed["id"],
                    "google_event_id": processed["google_event_id"],
                    "title": processed["title"],
                    "notes": processed["notes"] or "",
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
                    "is_owner": processed.get("is_owner", True),
                    "organizer_email": processed.get("organizer_email"),
                    "location": processed.get("location"),
                    "attendees": event_attendees(item),
                }
            )

        return mapped_events
    except Exception as e:
        logger.exception("Failed to retrieve Google Calendar events: %s", e)
        return []


@router.get("/events/{id}")
async def get_event(
    id: str,
    user_id: str = Depends(get_current_user_id),
    gc_service: GoogleCalendarService = Depends(get_google_calendar_service),
):
    try:
        return await gc_service.get_event(user_id, id)
    except Exception:
        raise HTTPException(status_code=404, detail="Google Calendar event not found")


@router.post("/events")
async def create_event(
    event: dict[str, Any] = Body(...),
    user_id: str = Depends(get_current_user_id),
    gc_service: GoogleCalendarService = Depends(get_google_calendar_service),
):
    try:
        # Crear en Google Calendar
        google_event = await gc_service.create_event(user_id, event)
        # Forzar sincronización inmediata
        await gc_service.sync_calendar(user_id)
        # Notify client via WebSocket
        await realtime_gateway.emitScheduleUpdate(
            user_id, {"source": "google_calendar_create"}
        )
        return google_event
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to create Google Calendar event"
        )


@router.patch("/events/{id}")
async def patch_event(
    id: str,
    event: dict[str, Any] = Body(...),
    user_id: str = Depends(get_current_user_id),
    gc_service: GoogleCalendarService = Depends(get_google_calendar_service),
):
    try:
        # Actualizar en Google Calendar
        google_event = await gc_service.patch_event(user_id, id, event)
        # Forzar sincronización inmediata
        await gc_service.sync_calendar(user_id)
        # Notify client via WebSocket
        await realtime_gateway.emitScheduleUpdate(
            user_id, {"source": "google_calendar_patch"}
        )
        return google_event
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to patch Google Calendar event"
        )


@router.delete("/events/{id}")
async def remove_event(
    id: str,
    user_id: str = Depends(get_current_user_id),
    gc_service: GoogleCalendarService = Depends(get_google_calendar_service),
):
    try:
        # Eliminar en Google Calendar
        await gc_service.delete_event(user_id, id)
        # Forzar sincronización inmediata
        await gc_service.sync_calendar(user_id)
        # Notify client via WebSocket
        await realtime_gateway.emitScheduleUpdate(
            user_id, {"source": "google_calendar_delete"}
        )
        return {"success": True}
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to delete Google Calendar event"
        )


@router.post("/webhook")
async def handle_google_webhook(
    request: Request,
    x_goog_channel_id: str = Header(None, alias="x-goog-channel-id"),
    x_goog_resource_id: str = Header(None, alias="x-goog-resource-id"),
    x_goog_channel_token: str = Header(None, alias="x-goog-channel-token"),
    x_goog_resource_state: str = Header(None, alias="x-goog-resource-state"),
    db: AsyncSession = Depends(get_db),
):
    if x_goog_resource_state == "sync":
        return {"status": "synchronized"}

    if x_goog_resource_state == "exists":
        userId = x_goog_channel_token

        # In the background, so Google gets its answer right away.
        await start_background_sync(userId, notify=True, throttle=False)
        return {"status": "sync_triggered"}

    return {"status": "processed"}
