from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any


class SchedulingAlgorithm:
    """Core slot finding, constraint checking, and heuristics for smart scheduling."""

    def build_hard_constraints(
        self,
        external_events: list[dict[str, Any]],
        meetings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        constraints = []
        for event in external_events:
            if not event.get("start") or not event.get("end"):
                continue
            constraints.append(
                {
                    "start": event["start"],
                    "end": event["end"],
                    "type": "external_event",
                    "id": event["id"],
                }
            )
        for meeting in meetings:
            if not meeting.get("start") or not meeting.get("end"):
                continue
            constraints.append(
                {
                    "start": meeting["start"],
                    "end": meeting["end"],
                    "type": "meeting",
                    "id": meeting["id"],
                }
            )

        constraints.sort(key=lambda x: x["start"])
        return constraints

    def filter_tasks_needing_scheduling(
        self, tasks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            t
            for t in tasks
            if t.get("status") not in ["completed", "cancelled", "in_progress"]
        ]

    def sort_tasks_by_priority(
        self, tasks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        sorted_tasks = list(tasks)

        def sort_key(t: dict[str, Any]):
            priority_val = t.get("priorityValue", 2)
            deadline = t.get("deadline")
            deadline_ts = deadline.timestamp() if deadline else float("inf")

            urgency_order = {
                "immediate": 4,
                "today": 3,
                "this_week": 2,
                "this_month": 1,
                "flexible": 0,
            }
            urgency_val = urgency_order.get(t.get("urgency", "flexible"), 0)
            return (-priority_val, deadline_ts, -urgency_val)

        sorted_tasks.sort(key=sort_key)
        return sorted_tasks

    def calculate_scheduling_window(
        self, task: dict[str, Any], constraints: dict[str, Any]
    ) -> tuple[datetime, datetime]:
        now = datetime.now()
        minutes_to_add = 5 - (now.minute % 5)
        if minutes_to_add == 5 and now.second == 0:
            minutes_to_add = 0
        earliest = now + timedelta(minutes=minutes_to_add)
        earliest = earliest.replace(second=0, microsecond=0)

        deadline = task.get("hardDeadline") or task.get("deadline")
        if deadline:
            deadline_day_start = deadline.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            start = max(earliest, deadline_day_start)
        else:
            start = earliest

        end = start + timedelta(days=14)
        return start, end

    def find_available_slots(
        self,
        window_start: datetime,
        window_end: datetime,
        hard_constraints: list[dict[str, Any]],
        existing_work_blocks: list[dict[str, Any]],
        constraints: dict[str, Any],
    ) -> list[dict[str, Any]]:
        slots = []
        slot_duration = timedelta(
            minutes=constraints.get("minFocusBlockDuration", 30)
        )
        current_time = window_start

        while current_time + slot_duration <= window_end:
            slot_end = current_time + slot_duration

            if not self.is_within_working_hours(current_time, constraints):
                current_time += timedelta(minutes=15)
                continue

            if not self.is_within_working_hours(
                slot_end - timedelta(minutes=1), constraints
            ):
                current_time += timedelta(minutes=15)
                continue

            if self.is_overlapping(current_time, slot_end, hard_constraints):
                current_time += timedelta(minutes=15)
                continue

            if self.is_overlapping_with_work_blocks(
                current_time, slot_end, existing_work_blocks
            ):
                current_time += timedelta(minutes=15)
                continue

            slots.append(
                {
                    "start": current_time,
                    "end": slot_end,
                    "duration": slot_duration.total_seconds() / 60.0,
                }
            )

            current_time += slot_duration

        return slots

    def is_within_working_hours(
        self, date: datetime, constraints: dict[str, Any]
    ) -> bool:
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        day_name = day_names[date.weekday()]

        if day_name not in constraints.get("workingDays", []):
            return False

        time_val = date.hour * 60 + date.minute
        hours_config = constraints.get(
            "workingHours", {"start": "09:00", "end": "17:00"}
        )
        start_h, start_m = map(int, hours_config.get("start", "09:00").split(":"))
        end_h, end_m = map(int, hours_config.get("end", "17:00").split(":"))

        start_val = start_h * 60 + start_m
        end_val = end_h * 60 + end_m

        return start_val <= time_val < end_val

    def is_overlapping(
        self, start: datetime, end: datetime, constraints: list[dict[str, Any]]
    ) -> bool:
        for c in constraints:
            if start < c["end"] and end > c["start"]:
                return True
        return False

    def is_overlapping_with_work_blocks(
        self, start: datetime, end: datetime, blocks: list[dict[str, Any]]
    ) -> bool:
        for wb in blocks:
            if start < wb["end"] and end > wb["start"]:
                return True
        return False

    def create_work_block(
        self,
        task: dict[str, Any],
        start: datetime,
        end: datetime,
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        duration = (end - start).total_seconds() / 60.0
        return {
            "id": f"wb_{int(start.timestamp())}_{uuid.uuid4().hex[:6]}",
            "userId": task["userId"],
            "taskId": task["id"],
            "start": start,
            "end": end,
            "duration": duration,
            "blockType": "focus",
            "isGenerated": True,
            "schedulingScore": self.calculate_scheduling_score(
                task, start, end, constraints
            ),
            "schedulingReason": self.get_scheduling_reason(task, start),
            "createdAt": datetime.now(),
            "updatedAt": datetime.now(),
        }

    def calculate_scheduling_score(
        self,
        task: dict[str, Any],
        start: datetime,
        end: datetime,
        constraints: dict[str, Any],
    ) -> float:
        score = 0.0
        hour = start.hour
        golden = constraints.get("goldenWindow")
        if golden:
            start_h, start_m = map(int, golden["start"].split(":"))
            end_h, end_m = map(int, golden["end"].split(":"))

            start_val = start_h * 60 + start_m
            end_val = end_h * 60 + end_m
            time_val = hour * 60 + start.minute

            if start_val <= time_val < end_val:
                score += 0.4

        return min(score, 1.0)

    def get_scheduling_reason(self, task: dict[str, Any], start: datetime) -> str:
        reasons = []
        deadline = task.get("deadline")
        if deadline:
            diff = deadline - start
            days = diff.days
            reasons.append(f"{days} days before deadline")

        hour = start.hour
        if 6 <= hour < 12:
            reasons.append("morning slot")
        elif 12 <= hour < 18:
            reasons.append("afternoon slot")
        elif 18 <= hour < 22:
            reasons.append("evening slot")

        return ", ".join(reasons) if reasons else "available slot"

    def get_suggested_action(self, task: dict[str, Any], reason: str | None) -> str:
        if reason == "deadline_passed":
            return "Update deadline or mark as completed"
        elif reason == "no_available_slots":
            return "Extend working hours or reduce task duration"
        elif reason == "constraints_conflict":
            return "Reschedule conflicting meetings or events"
        elif reason == "insufficient_time":
            return "Split task into smaller blocks or extend deadline"
        return "Review task constraints and try again"

    def calculate_scheduling_efficiency(
        self,
        hard_constraints: list[dict[str, Any]],
        scheduled_tasks: list[dict[str, Any]],
        constraints: dict[str, Any],
    ) -> float:
        total_scheduled = sum(
            sum(wb["duration"] for wb in st["workBlocks"]) for st in scheduled_tasks
        )
        total_available = 8.0 * 60.0 * 14.0
        return min(total_scheduled / total_available, 1.0)
