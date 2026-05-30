from datetime import timezone
import math
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
# pyrefly: ignore [missing-import]
import numpy as np
class MigrationService:
    def migrate_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        result = {}

        # 1. If task has google_event_id and source is 'google', migrate to ExternalCalendarEvent
        if task.get("google_event_id") and task.get("source") == "google":
            result["externalEvent"] = self._migrate_to_external_event(task)
            return result

        # 2. If task is a meeting (has collaborators or meeting link), migrate to Meeting
        if self._is_meeting(task):
            result["meeting"] = self._migrate_to_meeting(task)
            return result

        # 3. If task has estimated dates, migrate to WorkBlock
        if task.get("estimated_start_date") and task.get("estimated_end_date"):
            result["workBlock"] = self._migrate_to_work_block(task)
            return result

        # 4. Otherwise, migrate to new Task structure
        result["task"] = self._migrate_to_new_task(task)
        return result

    def migrate_time_block(self, time_block: Dict[str, Any]) -> Dict[str, Any]:
        start = self._parse_date(time_block.get("startTime"))
        end = self._parse_date(time_block.get("endTime"))
        duration = (np.subtract(end, start)).total_seconds() / 60.0

        return {
            "id": time_block.get("id"),
            "userId": time_block.get("userId"),
            "taskId": time_block.get("taskId"),
            "start": start,
            "end": end,
            "duration": duration,
            "blockType": self._map_block_type(time_block.get("blockType")),
            "isGenerated": time_block.get("source") == "App",
            "createdAt": self._parse_date(time_block.get("createdAt")),
            "updatedAt": datetime.now()
        }

    def _migrate_to_external_event(self, task: Dict[str, Any]) -> Dict[str, Any]:
        collaborators = task.get("collaborators") or []
        links = task.get("links") or []
        conference_data = self._extract_conference_data(links)

        return {
            "id": task.get("id"),
            "provider": "google",
            "providerEventId": task.get("google_event_id") or task.get("id"),
            "title": task.get("title"),
            "description": task.get("notesEncrypted"),
            "start": self._parse_date(task.get("estimated_start_date")),
            "end": self._parse_date(task.get("deadline")),
            "isAllDay": False,
            "location": None,
            "conferenceData": conference_data,
            "attendees": [
                {
                    "email": c.get("email"),
                    "name": c.get("name"),
                    "responseStatus": self._map_response_status(c.get("responseStatus")),
                    "avatar": c.get("avatar")
                } for c in collaborators
            ],
            "organizer": {
                "email": collaborators[0].get("email") if collaborators else "",
                "name": collaborators[0].get("name") if collaborators else "",
                "isSelf": True
            } if collaborators else None,
            "source": "external",
            "createdAt": self._parse_date(task.get("createdAt")),
            "updatedAt": self._parse_date(task.get("updatedAt"))
        }

    def _migrate_to_meeting(self, task: Dict[str, Any]) -> Dict[str, Any]:
        collaborators = task.get("collaborators") or []
        links = task.get("links") or []
        meeting_url = self._extract_meeting_url(links)

        return {
            "id": task.get("id"),
            "userId": task.get("userId"),
            "title": task.get("title"),
            "description": task.get("notesEncrypted"),
            "start": self._parse_date(task.get("estimated_start_date")),
            "end": self._parse_date(task.get("deadline")),
            "isAllDay": False,
            "location": None,
            "meetingType": "virtual" if meeting_url else "in_person",
            "meetingUrl": meeting_url,
            "attendees": [
                {
                    "email": c.get("email"),
                    "name": c.get("name"),
                    "responseStatus": self._map_response_status(c.get("responseStatus")),
                    "avatar": c.get("avatar")
                } for c in collaborators
            ],
            "isRecurring": False,
            "recurrenceRule": None,
            "source": "external" if task.get("source") == "google" else "manual",
            "externalEventId": task.get("google_event_id"),
            "createdAt": self._parse_date(task.get("createdAt")),
            "updatedAt": self._parse_date(task.get("updatedAt"))
        }

    def _migrate_to_new_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        tags = task.get("tags") or []
        deadline = self._parse_date(task.get("deadline"))

        return {
            "id": task.get("id"),
            "userId": task.get("userId"),
            "title": task.get("title"),
            "description": task.get("notesEncrypted"),
            "priority": self._map_priority(task.get("priorityLevel", 2)),
            "priorityValue": task.get("priorityLevel", 2),
            "urgency": self._map_urgency(deadline),
            "deadline": deadline,
            "hardDeadline": None,
            "estimatedDuration": task.get("estimateTimer") or 30,
            "status": self._map_status(task.get("status")),
            "dependsOnTaskIds": [],
            "blocksTaskIds": [],
            "category": task.get("category"),
            "tags": [t if isinstance(t, str) else t.get("name", "") for t in tags],
            "color": task.get("color"),
            "source": "ai_suggested" if task.get("use_ai") else "manual",
            "createdAt": self._parse_date(task.get("createdAt")),
            "updatedAt": self._parse_date(task.get("updatedAt")),
            "completedAt": self._parse_date(task.get("completedAt"))
        }

    def _migrate_to_work_block(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": f"wb_{task.get('id')}",
            "userId": task.get("userId"),
            "taskId": task.get("id"),
            "start": self._parse_date(task.get("estimated_start_date")),
            "end": self._parse_date(task.get("estimated_end_date") or self._parse_date(task.get("deadline"))),
            "duration": task.get("estimateTimer") or 30,
            "blockType": "focus",
            "isGenerated": False,
            "createdAt": self._parse_date(task.get("createdAt")),
            "updatedAt": self._parse_date(task.get("updatedAt"))    
        }

    def _is_meeting(self, task: Dict[str, Any]) -> bool:
        if task.get("collaborators") and len(task.get("collaborators")) > 0:
            return True
        links = task.get("links") or []
        for l in links:
            if self._is_meeting_link(l.get("url", "")):
                return True
        return False

    def _is_meeting_link(self, url: str) -> bool:
        meeting_domains = [
            "meet.google.com",
            "zoom.us",
            "teams.microsoft.com",
            "webex.com",
            "skype.com"
        ]
        return any(domain in url for domain in meeting_domains)

    def _extract_conference_data(self, links: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        for link in links:
            url = link.get("url", "")
            if "meet.google.com" in url:
                return {"type": "google_meet", "uri": url, "hangoutLink": url}
            elif "zoom.us" in url:
                return {"type": "zoom", "uri": url}
            elif "teams.microsoft.com" in url:
                return {"type": "teams", "uri": url}
        return None

    def _extract_meeting_url(self, links: List[Dict[str, str]]) -> Optional[str]:
        for link in links:
            url = link.get("url", "")
            if self._is_meeting_link(url):
                return url
        return None

    def _map_response_status(self, status: Optional[str]) -> str:
        if not status:
            return "needsAction"
        status_lower = status.lower()
        if status_lower in ["accepted", "declined", "tentative"]:
            return status_lower
        return "needsAction"

    def _map_priority(self, level: int) -> str:
        if level >= 4:
            return "critical"
        if level == 3:
            return "high"
        if level == 2:
            return "medium"
        return "low"

    def _map_urgency(self, deadline: Optional[datetime]) -> str:
        if not deadline:
            return "flexible"
        diff = deadline - datetime.now(timezone.utc)
        diff_hours = diff.total_seconds() / 3600.0
        diff_days = diff_hours / 24.0

        if diff_hours < 0:
            return "immediate"
        if diff_hours < 24:
            return "today"
        if diff_days < 7:
            return "this_week"
        if diff_days < 30:
            return "this_month"
        return "flexible"

    def _map_status(self, status: Optional[str]) -> str:
        if not status:
            return "backlog"
        mapping = {
            "Todo": "backlog",
            "Planning": "planned",
            "Pending": "scheduled",
            "Scheduled": "scheduled",
            "On Hold": "backlog",
            "Review": "in_progress",
            "Done": "completed",
            "Backlog": "backlog",
            "Archived": "cancelled"
        }
        return mapping.get(status, "backlog")

    def _map_block_type(self, block_type: Optional[str]) -> str:
        if block_type in ["Focus_Block", "Break"]:
            return "focus" if block_type == "Focus_Block" else "break"
        return "focus"

    def _parse_date(self, val: Any) -> Optional[datetime]:
        if not val:
            return None
        if isinstance(val, datetime):
            return val
        if isinstance(val, str):
            try:
                # Handle standard isoformats (Z or offset)
                val = val.replace("Z", "+00:00")
                return datetime.fromisoformat(val)
            except Exception:
                return None
        return None

    def create_default_scheduling_constraints(self, user_id: str) -> Dict[str, Any]:
        return {
            "userId": user_id,
            "workingDays": ["mon", "tue", "wed", "thu", "fri"],
            "workingHours": {
                "start": "09:00",
                "end": "17:00"
            },
            "breakDuration": 15,
            "breakInterval": 90,
            "preferredFocusBlockDuration": 60,
            "minFocusBlockDuration": 30,
            "maxFocusBlockDuration": 120,
            "schedulingStrategy": "balanced",
            "allowSameDaySplitting": True,
            "allowOvertime": False,
            "goldenWindow": {
                "start": "09:00",
                "end": "11:00"
            },
            "updatedAt": datetime.now()
        }
