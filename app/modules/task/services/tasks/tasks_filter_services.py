from __future__ import annotations
 
from datetime import datetime, timezone
from typing import Any
 
 
class TasksFilterService:

    def add_mapped_filters(
        self,
        tasks: list[dict[str, Any]],
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        mapped = list(tasks)
        for task in mapped:
            # Normalizamos IDs para asegurar que siempre sean strings limpios si existen
            if task.get("projectId") is not None:
                task["projectId"] = str(task["projectId"])
            if task.get("project_id") is not None:
                task["project_id"] = str(task["project_id"])
            if task.get("workspaceId") is not None:
                task["workspaceId"] = str(task["workspaceId"])
            if task.get("workspace_id") is not None:
                task["workspace_id"] = str(task["workspace_id"])

        if filters:
            target_ws = filters.get("workspace_id") or filters.get("workspaceId")
            if target_ws is not None:
                target_ws = str(target_ws)
                mapped = [
                    t
                    for t in mapped
                    if t.get("workspaceId") == target_ws
                    or t.get("workspace_id") == target_ws
                ]

            target_proj = filters.get("project_id") or filters.get("projectId")
            if target_proj is not None:
                target_proj = str(target_proj)
                mapped = [
                    t
                    for t in mapped
                    if t.get("projectId") == target_proj
                    or t.get("project_id") == target_proj
                ]

        return mapped


    def apply_filters_and_sorting(
        self,
        tasks: list[dict[str, Any]],
        filters: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
        search: str = ""
    ) -> list[dict[str, Any]]:
        return self._apply_filters_and_sorting(tasks, filters, sort, search)

    def _apply_filters_and_sorting(
        self,
        tasks: list[dict[str, Any]],
        filters: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
        search: str = "",
    ) -> list[dict[str, Any]]:
        mapped = self.add_mapped_filters(tasks, filters)
        
        if search:
            search_lower = search.lower()
            mapped = [t for t in mapped if search_lower in t.get("title", "").lower()]
            
        if filters:
            if filters.get("status") and len(filters["status"]) > 0:
                mapped = [t for t in mapped if t.get("status") in filters["status"]]

            if filters.get("priorityLevel") and len(filters["priorityLevel"]) > 0:
                levels = filters["priorityLevel"]
                if any(p >= 3 for p in levels):
                    mapped = [
                        t for t in mapped
                        if t.get("priorityLevel", 0) >= 3 or t.get("priorityLevel") in levels
                    ]
                else:
                    mapped = [t for t in mapped if t.get("priorityLevel") in levels]

            if filters.get("category") and len(filters["category"]) > 0:
                mapped = [t for t in mapped if t.get("category") in filters["category"]]

            if filters.get("tags") and len(filters["tags"]) > 0:
                target_tags = {t_tag.lower() for t_tag in filters["tags"]}

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
                    dt = datetime.fromisoformat(d_str.replace("Z", "+00:00"))
                    return dt

                start_date = parse_date(filters.get("startDate"))
                end_date = parse_date(filters.get("endDate"))
                if start_date and start_date.tzinfo is None:
                    start_date = start_date.replace(tzinfo=timezone.utc)
                if end_date and end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)

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

                    try:
                        date_to_use = datetime.fromisoformat(date_to_use_str.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        continue

                    if date_to_use.tzinfo is None:
                        date_to_use = date_to_use.replace(tzinfo=timezone.utc)

                    if start_date and date_to_use < start_date:
                        continue
                    if end_date and date_to_use > end_date:
                        continue
                    filtered_by_date.append(t)
                mapped = filtered_by_date

            if filters.get("searchTerm"):
                term = filters["searchTerm"].lower()
                mapped = [
                    t for t in mapped
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
                        return datetime.fromisoformat(val.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        return val
                return val

            mapped.sort(key=sort_key, reverse=(direction == -1))

        return mapped