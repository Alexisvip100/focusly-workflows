import uuid
import time
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.models.models import User, Task

class GoogleCalendarService:
    def __init__(self, db: AsyncSession, auth_service=None, tasks_service=None, scheduler_service=None):
        self.db = db
        self.auth_service = auth_service
        self.tasks_service = tasks_service
        self.scheduler_service = scheduler_service

    async def get_events(self, user_id: str, time_min: Optional[str] = None, time_max: Optional[str] = None) -> Dict[str, Any]:
        if not self.auth_service:
            raise ValueError("AuthService is required to get events")
            
        token_info = await self.auth_service.refresh_google_access_token(user_id)
        access_token = token_info.get("access_token")

        params = {
            "maxResults": "2500",
            "singleEvents": "true",
            "orderBy": "startTime"
        }

        if time_min:
            params["timeMin"] = time_min
        else:
            default_min = datetime.utcnow() - timedelta(days=30)
            params["timeMin"] = default_min.isoformat() + "Z"

        if time_max:
            params["timeMax"] = time_max

        url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events?{urlencode(params)}"
        async with httpx.AsyncClient() as client:
            res = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
            if res.status_code != 200:
                raise Exception(f"Failed to fetch from Google Calendar: {res.text}")
            return res.json()

    async def create_event(self, user_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        if not self.auth_service:
            raise ValueError("AuthService is required to create event")
            
        token_info = await self.auth_service.refresh_google_access_token(user_id)
        access_token = token_info.get("access_token")

        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events?conferenceDataVersion=1"
        async with httpx.AsyncClient() as client:
            res = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json=event
            )
            if res.status_code not in (200, 201):
                raise Exception(f"Failed to create Google event: {res.text}")
            return res.json()

    async def patch_event(self, user_id: str, event_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        if not self.auth_service:
            raise ValueError("AuthService is required to patch event")
            
        token_info = await self.auth_service.refresh_google_access_token(user_id)
        access_token = token_info.get("access_token")

        url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}?conferenceDataVersion=1"
        async with httpx.AsyncClient() as client:
            res = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json=event
            )
            if res.status_code != 200:
                raise Exception(f"Failed to patch Google event: {res.text}")
            return res.json()

    async def delete_event(self, user_id: str, event_id: str) -> None:
        if not self.auth_service:
            raise ValueError("AuthService is required to delete event")
            
        print(f"[GOOGLE CAL] Deleting event {event_id} for user {user_id}")
        token_info = await self.auth_service.refresh_google_access_token(user_id)
        access_token = token_info.get("access_token")

        url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}"
        async with httpx.AsyncClient() as client:
            res = await client.delete(url, headers={"Authorization": f"Bearer {access_token}"})
            if res.status_code != 200 and res.status_code != 204 and res.status_code != 404:
                print(f"[GOOGLE CAL] Delete failed ({res.status_code}): {res.text}")
                raise Exception("Failed to delete Google event")

    async def sync_calendar(self, user_id: str) -> None:
        print(f"Starting syncCalendar for user: {user_id}")
        if not self.auth_service or not self.tasks_service or not self.scheduler_service:
            raise ValueError("Required services not injected in GoogleCalendarService")

        token_info = await self.auth_service.refresh_google_access_token(user_id)
        access_token = token_info.get("access_token")

        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            raise ValueError(f"User {user_id} not found")

        sync_token = user.googleCalendarSyncToken
        next_page_token = None
        new_sync_token = None
        items_to_process = []

        base_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        
        async with httpx.AsyncClient() as client:
            try:
                while True:
                    params = {"maxResults": "250"}
                    
                    if sync_token:
                        params["syncToken"] = sync_token
                    else:
                        default_min = datetime.utcnow() - timedelta(days=30)
                        params["timeMin"] = default_min.isoformat() + "Z"
                        params["singleEvents"] = "true"
                        
                    if next_page_token:
                        params["pageToken"] = next_page_token

                    url = f"{base_url}?{urlencode(params)}"
                    res = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})

                    if res.status_code == 410:
                        print(f"Sync token expired for user {user_id}. Retrying with full sync.")
                        user.googleCalendarSyncToken = None
                        await self.db.commit()
                        sync_token = None
                        next_page_token = None
                        continue

                    if res.status_code != 200:
                        print(f"Error response from Google Calendar API: {res.text}")
                        raise Exception("Failed to fetch from Google Calendar")

                    data = res.json()
                    items = data.get("items", [])
                    if items:
                        items_to_process.extend(items)
                        
                    next_page_token = data.get("nextPageToken")
                    new_sync_token = data.get("nextSyncToken")
                    
                    if not next_page_token:
                        break

                print(f"Fetched {len(items_to_process)} events/changes to process for user {user_id}")
                
                has_changes = False
                for item in items_to_process:
                    event_id = item.get("id") or ""
                    
                    if item.get("status") == "cancelled":
                        print(f"Sync Cancelled/Deleted Event: {event_id} for user {user_id}")
                        # Find existing task
                        result_tasks = await self.db.execute(
                            select(Task).where(
                                Task.userId == user_id,
                                Task.google_event_id == event_id,
                                Task.deletedAt == None
                            )
                        )
                        existing_tasks = result_tasks.scalars().all()
                        for t in existing_tasks:
                            # delete task
                            await self.tasks_service.delete(t.id, skip_scheduling=True, skip_google_sync=True)
                            has_changes = True
                    else:
                        summary = item.get("summary") or "Sin título"
                        print(f"Sync Active/Updated Event: {event_id} - \"{summary}\"")
                        
                        processed = self._process_google_event(item, user_email=user.email)

                        # Check if this event already exists in DB and if so, whether
                        # our local version is newer than the Google event's updated timestamp.
                        # If the DB task was updated MORE RECENTLY than Google's event, we skip
                        # overwriting estimated_start/end dates to preserve manual drag-and-drop changes.
                        google_updated_str = item.get("updated")  # e.g. "2026-06-03T22:00:05.000Z"
                        google_updated = None
                        if google_updated_str:
                            try:
                                from datetime import timezone as _tz
                                google_updated = datetime.fromisoformat(
                                    google_updated_str.replace("Z", "+00:00")
                                ).astimezone(_tz.utc).replace(tzinfo=None)
                            except Exception:
                                pass

                        preserve_dates = False
                        if google_updated and event_id:
                            existing_result = await self.db.execute(
                                select(Task).where(
                                    Task.userId == user_id,
                                    Task.google_event_id == event_id,
                                    Task.deletedAt == None
                                )
                            )
                            existing_task = existing_result.scalars().first()
                            if existing_task and existing_task.updatedAt:
                                db_updated = existing_task.updatedAt
                                # If our DB record is at least 2 seconds newer than Google's event,
                                # it means WE triggered this change; skip date overwrite.
                                if db_updated >= google_updated - timedelta(seconds=2):
                                    preserve_dates = True
                                    print(
                                        f"[SYNC] Preserving local dates for event {event_id}: "
                                        f"DB updated={db_updated.isoformat()}, "
                                        f"Google updated={google_updated.isoformat()}"
                                    )
                        
                        task_data = {
                            "userId": user_id,
                            "title": processed["title"],
                            "notesEncrypted": processed["notes_encrypted"] or "",
                            "deadline": processed["deadline"],
                            "status": "Scheduled",
                            "priorityLevel": processed["priority_level"] or 2,
                            "estimateTimer": processed["estimate_timer"] or 30,
                            "category": "Meeting",
                            "google_event_id": processed["google_event_id"],
                            "task_type": "GoogleTask",
                            "source": "google",
                            "tags": processed["tags"] or [],
                            "links": processed["links"] or [],
                            "collaborators": processed["collaborators"] or [],
                            "is_owner": processed.get("is_owner", True),
                        }

                        # Only include dates from Google if we are NOT preserving local values
                        if not preserve_dates:
                            task_data["estimated_start_date"] = processed["estimated_start_date"]
                            task_data["estimated_end_date"] = processed["estimated_end_date"]

                        task = await self.tasks_service.create(
                            task_data,
                            skip_scheduling=True,
                            skip_google_sync=True
                        )
                        if task.get("_changed"):
                            has_changes = True

                if new_sync_token:
                    user.googleCalendarSyncToken = new_sync_token
                    await self.db.commit()
                    print(f"Updated syncToken to: {new_sync_token} for user {user_id}")

                if has_changes:
                    print(f"Sync Calendar detected changes. Running scheduler for user: {user_id}")
                    # In python tasks service, scheduler pipeline uses the socket server we injected or default
                    await self.scheduler_service.run_scheduling_pipeline(user_id, self.db, self.tasks_service.socket_server)
                else:
                    print(f"Sync Calendar detected no actual changes for user: {user_id}. Skipping scheduler.")

                # Register push watch
                await self.watch_calendar(user_id)

            except Exception as error:
                print(f"Error in syncCalendar: {error}")
                raise error

    async def watch_calendar(self, user_id: str) -> None:
        try:
            result = await self.db.execute(select(User).where(User.id == user_id))
            user = result.scalars().first()
            if not user:
                return

            expiration = user.googleChannelExpiration
            now = int(time.time() * 1000)

            # Check if valid for next 24 hours
            if expiration and expiration - now > 24 * 60 * 60 * 1000:
                print(f"Watch channel for user {user_id} is still valid. Skipping setup.")
                return

            if user.googleChannelId and user.googleResourceId:
                try:
                    await self.stop_watching_calendar(user_id)
                except Exception as e:
                    print(f"Failed to stop old watch channel: {e}")

            token_info = await self.auth_service.refresh_google_access_token(user_id)
            access_token = token_info.get("access_token")

            webhook_url = settings.WEBHOOK_URL
            if not webhook_url:
                print(f"WEBHOOK_URL not set in settings. Cannot establish watch channel for user {user_id}.")
                return

            channel_id = str(uuid.uuid4())
            address = f"{webhook_url}/google-calendar/webhook"
            expiration_time = now + 7 * 24 * 60 * 60 * 1000 # 7 days

            url = "https://www.googleapis.com/calendar/v3/calendars/primary/events/watch"
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "id": channel_id,
                        "type": "web_hook",
                        "address": address,
                        "token": user_id,
                        "expiration": str(expiration_time)
                    }
                )
                if res.status_code != 200:
                    print(f"Failed to register watch channel. Status: {res.status_code}. Body: {res.text}")
                    return

                data = res.json()
                
            user.googleChannelId = data.get("id")
            user.googleResourceId = data.get("resourceId")
            user.googleChannelExpiration = int(data.get("expiration") or expiration_time)
            await self.db.commit()

            print(f"Watch channel registered for user {user_id}. Expires: {datetime.fromtimestamp(user.googleChannelExpiration / 1000).isoformat()}")

        except Exception as error:
            print(f"Error setting up watch channel: {error}")

    async def stop_watching_calendar(self, user_id: str) -> None:
        try:
            result = await self.db.execute(select(User).where(User.id == user_id))
            user = result.scalars().first()
            if not user:
                return

            channel_id = user.googleChannelId
            resource_id = user.googleResourceId

            if not channel_id or not resource_id:
                return

            token_info = await self.auth_service.refresh_google_access_token(user_id)
            access_token = token_info.get("access_token")

            url = "https://www.googleapis.com/calendar/v3/channels/stop"
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "id": channel_id,
                        "resourceId": resource_id
                    }
                )
                if res.status_code in (200, 204, 404):
                    user.googleChannelId = None
                    user.googleResourceId = None
                    user.googleChannelExpiration = None
                    await self.db.commit()
                    print(f"Stopped watching calendar for user {user_id}")
                else:
                    print(f"Failed to stop watch channel for user {user_id}. Body: {res.text}")

        except Exception as error:
            print(f"Error stopping watch channel: {error}")

    def _process_google_event(self, event: Dict[str, Any], user_email: Optional[str] = None) -> Dict[str, Any]:
        # Stage 1: Basic Mapping
        start_obj = event.get("start") or {}
        end_obj = event.get("end") or {}
        
        is_all_day = bool(start_obj.get("date"))
        creator_email = event.get("creator", {}).get("email")
        is_creator_self = bool(event.get("creator", {}).get("self", False))
        is_owner = is_creator_self or (user_email is not None and creator_email == user_email)
        start_val = start_obj.get("dateTime") or start_obj.get("date")
        if start_val:
            dt = datetime.fromisoformat(start_val.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                from datetime import timezone
                dt = dt.astimezone(timezone.utc)
            start = dt.replace(tzinfo=None)
        else:
            start = datetime.utcnow()

        end_val = end_obj.get("dateTime") or end_obj.get("date")
        if end_val:
            dt = datetime.fromisoformat(end_val.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                from datetime import timezone
                dt = dt.astimezone(timezone.utc)
            deadline = dt.replace(tzinfo=None)
        else:
            deadline = start + timedelta(minutes=30)

        # Color mapping to priority
        def map_google_color_to_priority(color_id: Optional[str]) -> int:
            if not color_id:
                return 1
            priority_map = {
                "11": 3, "4": 3, "6": 3, "3": 3,
                "5": 2, "9": 2, "7": 2, "2": 2,
                "1": 1, "10": 1, "8": 1
            }
            return priority_map.get(color_id, 1)

        task = {
            "id": event.get("id") or "",
            "google_event_id": event.get("id"),
            "title": event.get("summary") or "Sin título",
            "notes_encrypted": event.get("description") or "",
            "deadline": deadline.isoformat(),
            "estimated_start_date": start.isoformat(),
            "estimated_end_date": deadline.isoformat(),
            "status": "Scheduled",
            "priority_level": map_google_color_to_priority(event.get("colorId")),
            "tags": [],
            "links": [],
            "estimate_timer": int(round((deadline - start).total_seconds() / 60.0)),
            "task_type": "GoogleTask",
            "is_all_day": is_all_day,
            "location": event.get("location"),
            "collaborators": [],
            "organizer_email": event.get("organizer", {}).get("email"),
            "is_owner": is_owner
        }

        # Stage 2: Clean Description
        notes = task["notes_encrypted"]
        if notes:
            # strip html
            notes = notes.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
            notes = re.sub(r'</p>', '\n', notes, flags=re.IGNORECASE)
            notes = re.sub(r'<li>', '• ', notes, flags=re.IGNORECASE)
            notes = re.sub(r'</li>', '\n', notes, flags=re.IGNORECASE)
            notes = re.sub(r'<[^>]*>?', '', notes)
            # decode HTML entities
            notes = notes.replace("&amp;", "&").replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            notes = re.sub(r'\n\s*\n', '\n\n', notes)
            task["notes_encrypted"] = notes.strip()

        # Stage 3: Extract Meeting Links
        conf_data = event.get("conferenceData") or {}
        entry_points = conf_data.get("entryPoints") or []
        conference_link = None
        for ep in entry_points:
            if ep.get("entryPointType") == "video":
                conference_link = ep.get("uri")
                break

        call_link = event.get("hangoutLink") or conference_link
        if call_link:
            is_google_meet = "meet.google.com" in call_link
            title = "Google Meet" if is_google_meet else "Enlace de Reunión"
            task["links"].append({"title": title, "url": call_link})

        # Stage 4: Process Participants
        attendees = event.get("attendees") or []
        has_meet_link = any("meet.google.com" in l["url"] or l["title"] == "Google Meet" for l in task["links"])
        
        if has_meet_link and attendees:
            collaborators = []
            for att in attendees:
                email = att.get("email")
                if email:
                    name = att.get("displayName") or email.split("@")[0]
                    collaborators.append({
                        "name": name,
                        "email": email,
                        "avatar": f"https://ui-avatars.com/api/?name={name}&background=random&color=fff&size=128"
                    })
            task["collaborators"] = collaborators

        return task
