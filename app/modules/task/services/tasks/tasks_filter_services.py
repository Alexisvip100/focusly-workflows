from __future__ import annotations
 
from datetime import datetime
from typing import Any
 
from sqlalchemy import func, select
 
from app.models import Task

class TasksFilterService:
    def apply_filters_and_sorting(
        self,
        tasks: list[dict[str, Any]],
        filters: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self._apply_filters_and_sorting(tasks, filters, sort)

    def _apply_filters_and_sorting(
        self,
        tasks: list[dict[str, Any]],
        filters: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        mapped = list(tasks)

        if filters:
            if filters.get("status") and len(filters["status"]) > 0:
                mapped = [t for t in mapped if t.get("status") in filters["status"]]

            if filters.get("priorityLevel") and len(filters["priorityLevel"]) > 0:
                # If priority level query contains >= 3, include higher levels
                levels = filters["priorityLevel"]
                if any(p >= 3 for p in levels):
                    mapped = [
                        t
                        for t in mapped
                        if t.get("priorityLevel", 0) >= 3
                        or t.get("priorityLevel") in levels
                    ]
                else:
                    mapped = [t for t in mapped if t.get("priorityLevel") in levels]

            if filters.get("category") and len(filters["category"]) > 0:
                mapped = [t for t in mapped if t.get("category") in filters["category"]]

            if filters.get("tags") and len(filters["tags"]) > 0:
                target_tags = set(t_tag.lower() for t_tag in filters["tags"])

                def has_matching_tag(task):
                    task_tags = task.get("tags") or []
                    for tag in task_tags:
                        tag_name = tag if isinstance(tag, str) else tag.get("name", "")
                        if tag_name.lower() in target_tags:
                            return True
                    return False

                mapped = [t for t in mapped if has_matching_tag(t)]

            if filters.get("startDate") or filters.get("endDate"):

                def parse_date(d_str):
                    if not d_str:
                        return None
                    return datetime.fromisoformat(d_str.replace("Z", "+00:00"))

                start_date = parse_date(filters.get("startDate"))
                end_date = parse_date(filters.get("endDate"))

                filtered_by_date = []
                for t in mapped:
                    date_to_use_str = (
                        t.get("estimated_start_date")
                        or t.get("deadline")
                        or t.get("completedAt")
                        or t.get("createdAt")
                    )
                    if not date_to_use_str:
                        continue
                    date_to_use = datetime.fromisoformat(date_to_use_str)

                    if date_to_use.tzinfo is None:
                        if start_date and start_date.tzinfo is not None:
                            start_date = start_date.replace(tzinfo=None)
                        if end_date and end_date.tzinfo is not None:
                            end_date = end_date.replace(tzinfo=None)

                    if start_date and date_to_use < start_date:
                        continue
                    if end_date and date_to_use > end_date:
                        continue
                    filtered_by_date.append(t)
                mapped = filtered_by_date

            if filters.get("searchTerm"):
                term = filters["searchTerm"].lower()
                mapped = [
                    t
                    for t in mapped
                    if term in t.get("title", "").lower()
                    or term in (t.get("notesEncrypted") or "").lower()
                ]

        if sort and sort.get("sort"):
            field_map = {
                "deadline": "deadline",
                "priority_level": "priorityLevel",
                "estimate_minutes": "estimateTimer",
                "created_at": "createdAt",
            }
            sort_field = field_map.get(sort["sort"], sort["sort"])
            direction = -1 if sort.get("order", "asc").lower() == "desc" else 1

            def sort_key(t):
                val = t.get(sort_field)
                if val is None:
                    return float("inf") if direction == 1 else float("-inf")
                if isinstance(val, str):
                    try:
                        return datetime.fromisoformat(val).timestamp()
                    except:
                        return val
                return val

            mapped.sort(key=sort_key, reverse=(direction == -1))

        return mapped
