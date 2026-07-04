import uuid
from datetime import datetime, timedelta
from typing import Any
from sqlalchemy import select, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Task, TimeBlock

class SchedulerService:
    async def schedule(
        self,
        user_id: str,
        external_events: list[dict[str, Any]],
        meetings: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        constraints: dict[str, Any],
        existing_work_blocks: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        scheduled_at = datetime.utcnow()
        existing_work_blocks = existing_work_blocks or []

        # 1. Build the timeline of hard constraints
        hard_constraints = self._build_hard_constraints(external_events, meetings)

        # 2. Filter tasks that need scheduling
        tasks_to_schedule = self._filter_tasks_needing_scheduling(tasks)

        # 3. Sort tasks by priority and urgency
        sorted_tasks = self._sort_tasks_by_priority(tasks_to_schedule)

        scheduled_tasks = []
        unscheduled_tasks = []
        conflicts = []

        # 5. Schedule each task
        for task in sorted_tasks:
            result = await self._schedule_single_task(
                task,
                hard_constraints,
                constraints,
                existing_work_blocks
            )

            status = result["status"]
            if status in ["scheduled", "partially_scheduled"]:
                scheduled_tasks.append(result)
                # Add newly scheduled work blocks to existing ones so subsequent tasks don't overlap them
                existing_work_blocks.extend(result["workBlocks"])
            else:
                unscheduled_tasks.append({
                    "taskId": task["id"],
                    "reason": result.get("reason", "no_available_slots"),
                    "suggestedAction": self._get_suggested_action(task, result.get("reason"))
                })

        # Calculate statistics
        total_work_blocks = sum(len(st["workBlocks"]) for st in scheduled_tasks)
        total_scheduled_minutes = sum(
            sum(wb["duration"] for wb in st["workBlocks"])
            for st in scheduled_tasks
        )

        # Calculate scheduling efficiency
        efficiency = self._calculate_scheduling_efficiency(
            hard_constraints,
            scheduled_tasks,
            constraints
        )

        return {
            "userId": user_id,
            "scheduledAt": scheduled_at,
            "scheduledTasks": scheduled_tasks,
            "unscheduledTasks": unscheduled_tasks,
            "conflicts": conflicts,
            "totalTasksScheduled": len(scheduled_tasks),
            "totalWorkBlocksCreated": total_work_blocks,
            "totalScheduledMinutes": total_scheduled_minutes,
            "schedulingEfficiency": efficiency
        }

    def _build_hard_constraints(
        self,
        external_events: list[dict[str, Any]],
        meetings: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        constraints = []
        for event in external_events:
            if not event.get("start") or not event.get("end"):
                continue
            constraints.append({
                "start": event["start"],
                "end": event["end"],
                "type": "external_event",
                "id": event["id"]
            })
        for meeting in meetings:
            if not meeting.get("start") or not meeting.get("end"):
                continue
            constraints.append({
                "start": meeting["start"],
                "end": meeting["end"],
                "type": "meeting",
                "id": meeting["id"]
            })
        
        # Sort by start time
        constraints.sort(key=lambda x: x["start"])
        return constraints

    def _filter_tasks_needing_scheduling(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            t for t in tasks 
            if t.get("status") not in ["completed", "cancelled", "in_progress"]
        ]

    def _sort_tasks_by_priority(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sorted_tasks = list(tasks)
        
        def sort_key(t: dict[str, Any]):
            priority_val = t.get("priorityValue", 2)
            deadline = t.get("deadline")
            deadline_ts = deadline.timestamp() if deadline else float('inf')
            
            urgency_order = {
                "immediate": 4,
                "today": 3,
                "this_week": 2,
                "this_month": 1,
                "flexible": 0
            }
            urgency_val = urgency_order.get(t.get("urgency", "flexible"), 0)
            
            # We want higher priority first (-priority_val), earlier deadline first (deadline_ts), higher urgency first (-urgency_val)
            return (-priority_val, deadline_ts, -urgency_val)

        sorted_tasks.sort(key=sort_key)
        return sorted_tasks

    async def _schedule_single_task(
        self,
        task: dict[str, Any],
        hard_constraints: list[dict[str, Any]],
        constraints: dict[str, Any],
        existing_work_blocks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        work_blocks = []
        remaining_duration = task.get("estimatedDuration") or 30

        # Check if deadline passed
        hard_deadline = task.get("hardDeadline")
        if hard_deadline and hard_deadline < datetime.utcnow():
            return {
                "taskId": task["id"],
                "workBlocks": [],
                "status": "could_not_schedule",
                "reason": "deadline_passed"
            }

        window_start, window_end = self._calculate_scheduling_window(task, constraints)

        available_slots = self._find_available_slots(
            window_start,
            window_end,
            hard_constraints,
            existing_work_blocks,
            constraints
        )

        for slot in available_slots:
            if remaining_duration <= 0:
                break

            slot_duration = (slot["end"] - slot["start"]).total_seconds() / 60.0
            max_duration = min(slot_duration, constraints.get("maxFocusBlockDuration", 120))
            block_duration = min(max_duration, remaining_duration)

            if block_duration >= 5.0:
                block_end = slot["start"] + timedelta(minutes=block_duration)
                work_block = self._create_work_block(
                    task,
                    slot["start"],
                    block_end,
                    constraints
                )
                work_blocks.append(work_block)
                remaining_duration -= block_duration

        if remaining_duration == 0:
            return {
                "taskId": task["id"],
                "workBlocks": work_blocks,
                "status": "scheduled"
            }
        elif len(work_blocks) > 0:
            return {
                "taskId": task["id"],
                "workBlocks": work_blocks,
                "status": "partially_scheduled",
                "reason": "insufficient_time"
            }
        else:
            return {
                "taskId": task["id"],
                "workBlocks": [],
                "status": "could_not_schedule",
                "reason": "no_available_slots"
            }

    def _calculate_scheduling_window(self, task: dict[str, Any], constraints: dict[str, Any]) -> tuple[datetime, datetime]:
        now = datetime.utcnow()
        # Round to next 5 minutes
        minutes_to_add = 5 - (now.minute % 5)
        if minutes_to_add == 5 and now.second == 0:
            minutes_to_add = 0
        start = now + timedelta(minutes=minutes_to_add)
        start = start.replace(second=0, microsecond=0)

        end = task.get("hardDeadline") or task.get("deadline")
        if not end or end > start + timedelta(days=14):
            end = start + timedelta(days=14)
        
        return start, end

    def _find_available_slots(
        self,
        start_time: datetime,
        end_time: datetime,
        hard_constraints: list[dict[str, Any]],
        existing_work_blocks: list[dict[str, Any]],
        constraints: dict[str, Any]
    ) -> list[dict[str, Any]]:
        slots = []
        slot_size = 5 # 5 minutes granularity
        current_ptr = start_time

        while current_ptr < end_time:
            if not self._is_within_working_hours(current_ptr, constraints):
                current_ptr += timedelta(minutes=slot_size)
                continue

            check_end = current_ptr + timedelta(minutes=slot_size)
            if self._is_overlapping(current_ptr, check_end, hard_constraints):
                current_ptr += timedelta(minutes=slot_size)
                continue

            if self._is_overlapping_with_work_blocks(current_ptr, check_end, existing_work_blocks):
                current_ptr += timedelta(minutes=slot_size)
                continue

            # Found free slot, extend it
            slot_start = current_ptr
            slot_end = current_ptr + timedelta(minutes=slot_size)

            while (
                self._is_within_working_hours(slot_end, constraints) and
                not self._is_overlapping(slot_end, slot_end + timedelta(minutes=slot_size), hard_constraints) and
                not self._is_overlapping_with_work_blocks(slot_end, slot_end + timedelta(minutes=slot_size), existing_work_blocks) and
                slot_end < end_time
            ):
                slot_end += timedelta(minutes=slot_size)

            slots.append({"start": slot_start, "end": slot_end})
            current_ptr = slot_end

        return slots

    def _is_within_working_hours(self, date: datetime, constraints: dict[str, Any]) -> bool:
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        # Python weekday: Monday is 0, Sunday is 6
        day_name = day_names[date.weekday()]

        if day_name not in constraints.get("workingDays", []):
            return False

        time_val = date.hour * 60 + date.minute
        
        hours_config = constraints.get("workingHours", {"start": "09:00", "end": "17:00"})
        start_h, start_m = map(int, hours_config.get("start", "09:00").split(":"))
        end_h, end_m = map(int, hours_config.get("end", "17:00").split(":"))

        start_val = start_h * 60 + start_m
        end_val = end_h * 60 + end_m

        return start_val <= time_val < end_val

    def _is_overlapping(self, start: datetime, end: datetime, constraints: list[dict[str, Any]]) -> bool:
        for c in constraints:
            if start < c["end"] and end > c["start"]:
                return True
        return False

    def _is_overlapping_with_work_blocks(self, start: datetime, end: datetime, blocks: list[dict[str, Any]]) -> bool:
        for wb in blocks:
            if start < wb["end"] and end > wb["start"]:
                return True
        return False

    def _create_work_block(
        self,
        task: dict[str, Any],
        start: datetime,
        end: datetime,
        constraints: dict[str, Any]
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
            "schedulingScore": self._calculate_scheduling_score(task, start, end, constraints),
            "schedulingReason": self._get_scheduling_reason(task, start),
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }

    def _calculate_scheduling_score(
        self,
        task: dict[str, Any],
        start: datetime,
        end: datetime,
        constraints: dict[str, Any]
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

    def _get_scheduling_reason(self, task: dict[str, Any], start: datetime) -> str:
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

    def _get_suggested_action(self, task: dict[str, Any], reason: str | None) -> str:
        if reason == "deadline_passed":
            return "Update deadline or mark as completed"
        elif reason == "no_available_slots":
            return "Extend working hours or reduce task duration"
        elif reason == "constraints_conflict":
            return "Reschedule conflicting meetings or events"
        elif reason == "insufficient_time":
            return "Split task into smaller blocks or extend deadline"
        return "Review task constraints and try again"

    def _calculate_scheduling_efficiency(
        self,
        hard_constraints: list[dict[str, Any]],
        scheduled_tasks: list[dict[str, Any]],
        constraints: dict[str, Any]
    ) -> float:
        total_scheduled = sum(
            sum(wb["duration"] for wb in st["workBlocks"])
            for st in scheduled_tasks
        )
        total_available = 8.0 * 60.0 * 14.0  # mock 8 hours/day * 14 days
        return min(total_scheduled / total_available, 1.0)

    async def run_scheduling_pipeline(self, user_id: str, db: AsyncSession, socket_server=None) -> None:
        # 1. Fetch user settings
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            return

        settings_dict = user.settings or {}
        work_hours_config = settings_dict.get("workHoursConfig", {
            "selectedDays": ["Mon", "Tue", "Wed", "Thu", "Fri"],
            "startTime": "09:00",
            "endTime": "17:00"
        })
        
        # Build scheduling constraints from settings
        working_days = [d.lower() for d in work_hours_config.get("selectedDays", [])]
        constraints = {
            "userId": user_id,
            "workingDays": working_days if working_days else ["mon", "tue", "wed", "thu", "fri"],
            "workingHours": {
                "start": work_hours_config.get("startTime", "09:00"),
                "end": work_hours_config.get("endTime", "17:00")
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
            }
        }

        # 2. Fetch all tasks
        result = await db.execute(select(Task).where(Task.userId == user_id, Task.deletedAt == None, or_(Task.source != "google", Task.source == None)))
        tasks = result.scalars().all()
        tasks_list = []
        for t in tasks:
            tasks_list.append({
                "id": t.id,
                "userId": t.userId,
                "title": t.title,
                "notesEncrypted": t.notesEncrypted,
                "estimateTimer": t.estimateTimer,
                "realTimer": t.realTimer,
                "duration": t.duration,
                "priorityValue": t.priorityLevel,
                "category": t.category,
                "color": t.color,
                "estimated_start_date": t.estimated_start_date,
                "estimated_end_date": t.estimated_end_date,
                "deadline": t.deadline,
                "status": t.status,
                "completedAt": t.completedAt,
                "createdAt": t.createdAt,
                "updatedAt": t.updatedAt,
                "tags": t.tags or [],
                "links": t.links or [],
                "collaborators": t.collaborators or [],
                "use_ai": t.use_ai
            })

        # 3. Fetch all time blocks
        result = await db.execute(select(TimeBlock).where(TimeBlock.userId == user_id))
        time_blocks = result.scalars().all()
        
        # 4. Migrate tasks & timeblocks using MigrationService
        from app.modules.task.services.migration_service import MigrationService
        migrator = MigrationService()
        
        external_events = []
        meetings = []
        new_tasks = []
        existing_work_blocks = []
        
        for t_dict in tasks_list:
            migrated = migrator.migrate_task(t_dict)
            if "externalEvent" in migrated:
                external_events.append(migrated["externalEvent"])
            elif "meeting" in migrated:
                meetings.append(migrated["meeting"])
            elif "task" in migrated:
                new_tasks.append(migrated["task"])
            elif "workBlock" in migrated:
                existing_work_blocks.append(migrated["workBlock"])
                
        for tb in time_blocks:
            tb_dict = {
                "id": tb.id,
                "userId": tb.userId,
                "taskId": tb.taskId,
                "startTime": tb.startTime,
                "endTime": tb.endTime,
                "blockType": tb.blockType,
                "source": tb.source,
                "createdAt": tb.createdAt
            }
            existing_work_blocks.append(migrator.migrate_time_block(tb_dict))

        # 5. Run scheduler
        res = await self.schedule(
            user_id=user_id,
            external_events=external_events,
            meetings=meetings,
            tasks=new_tasks,
            constraints=constraints,
            existing_work_blocks=existing_work_blocks
        )

        # 6. Apply scheduling results to database
        # Deleting old Focus Blocks
        await db.execute(
            delete(TimeBlock).where(TimeBlock.userId == user_id, TimeBlock.blockType == "Focus_Block")
        )
        
        # Insert new time blocks
        new_time_blocks = []
        for st in res["scheduledTasks"]:
            for wb in st["workBlocks"]:
                new_time_blocks.append(TimeBlock(
                    id=wb["id"],
                    userId=user_id,
                    taskId=wb["taskId"],
                    startTime=wb["start"],
                    endTime=wb["end"],
                    blockType="Focus_Block",
                    source="App",
                    title="Focus Block"
                ))
        if new_time_blocks:
            db.add_all(new_time_blocks)
            
        # Update tasks with start/end estimates
        for st in res["scheduledTasks"]:
            t_id = st["taskId"]
            wbs = st["workBlocks"]
            if wbs:
                sorted_wbs = sorted(wbs, key=lambda x: x["start"])
                first_wb = sorted_wbs[0]
                last_wb = sorted_wbs[-1]
                
                # Fetch task and update
                task_res = await db.execute(select(Task).where(Task.id == t_id))
                t_obj = task_res.scalars().first()
                if t_obj:
                    new_start = first_wb["start"]
                    if t_obj.estimated_start_date != new_start:
                        t_obj.notified = False
                        t_obj.lastMinuteNotified = False
                    t_obj.estimated_start_date = new_start
                    t_obj.estimated_end_date = last_wb["end"]
                    t_obj.status = "Scheduled"
                    t_obj.updatedAt = datetime.utcnow()
                    
        await db.commit()
        
        # 7. Notify client via WebSockets
        if socket_server:
            try:
                await socket_server.emit(
                    "schedule_updated",
                    {"type": "SCHEDULE_RECALCULATED", "timestamp": datetime.utcnow().isoformat()},
                    room=f"user_{user_id}",
                    namespace="/realtime"
                )
            except Exception:
                pass
