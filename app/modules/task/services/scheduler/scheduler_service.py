from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import transaction_scope
from app.models import TimeBlock
from app.modules.user.repository import UsersRepository
from app.modules.task.repository import TasksRepository, TimeBlocksRepository
from .scheduling_algorithm import SchedulingAlgorithm


class SchedulerService:
    algo = SchedulingAlgorithm()

    def __init__(self):
        self.algo = SchedulingAlgorithm()

    # Delegate helper methods for direct backwards compatibility / unit tests
    def _build_hard_constraints(self, external_events, meetings):
        return self.algo.build_hard_constraints(external_events, meetings)

    def _filter_tasks_needing_scheduling(self, tasks):
        return self.algo.filter_tasks_needing_scheduling(tasks)

    def _sort_tasks_by_priority(self, tasks):
        return self.algo.sort_tasks_by_priority(tasks)

    def _calculate_scheduling_window(self, task, constraints):
        return self.algo.calculate_scheduling_window(task, constraints)

    def _find_available_slots(self, window_start, window_end, hard_constraints, existing_work_blocks, constraints):
        return self.algo.find_available_slots(window_start, window_end, hard_constraints, existing_work_blocks, constraints)

    def _is_within_working_hours(self, date, constraints):
        return self.algo.is_within_working_hours(date, constraints)

    def _is_overlapping(self, start, end, constraints):
        return self.algo.is_overlapping(start, end, constraints)

    def _is_overlapping_with_work_blocks(self, start, end, blocks):
        return self.algo.is_overlapping_with_work_blocks(start, end, blocks)

    def _create_work_block(self, task, start, end, constraints):
        return self.algo.create_work_block(task, start, end, constraints)

    def _calculate_scheduling_score(self, task, start, end, constraints):
        return self.algo.calculate_scheduling_score(task, start, end, constraints)

    def _get_scheduling_reason(self, task, start):
        return self.algo.get_scheduling_reason(task, start)

    def _get_suggested_action(self, task, reason):
        return self.algo.get_suggested_action(task, reason)

    def _calculate_scheduling_efficiency(self, hard_constraints, scheduled_tasks, constraints):
        return self.algo.calculate_scheduling_efficiency(hard_constraints, scheduled_tasks, constraints)

    async def _schedule_single_task(
        self,
        task: dict[str, Any],
        hard_constraints: list[dict[str, Any]],
        constraints: dict[str, Any],
        existing_work_blocks: list[dict[str, Any]],
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
                "reason": "deadline_passed",
            }

        window_start, window_end = self.algo.calculate_scheduling_window(task, constraints)

        available_slots = self.algo.find_available_slots(
            window_start,
            window_end,
            hard_constraints,
            existing_work_blocks,
            constraints,
        )

        for slot in available_slots:
            if remaining_duration <= 0:
                break

            slot_duration = (slot["end"] - slot["start"]).total_seconds() / 60.0
            max_duration = min(
                slot_duration, constraints.get("maxFocusBlockDuration", 120)
            )
            block_duration = min(max_duration, remaining_duration)

            if block_duration >= 5.0:
                block_end = slot["start"] + timedelta(minutes=block_duration)
                work_block = self.algo.create_work_block(
                    task, slot["start"], block_end, constraints
                )
                work_blocks.append(work_block)
                remaining_duration -= block_duration

        if remaining_duration == 0:
            return {
                "taskId": task["id"],
                "workBlocks": work_blocks,
                "status": "scheduled",
            }
        elif len(work_blocks) > 0:
            return {
                "taskId": task["id"],
                "workBlocks": work_blocks,
                "status": "partially_scheduled",
                "reason": "insufficient_time",
            }
        else:
            return {
                "taskId": task["id"],
                "workBlocks": [],
                "status": "could_not_schedule",
                "reason": "no_available_slots",
            }

    async def schedule(
        self,
        user_id: str,
        external_events: list[dict[str, Any]],
        meetings: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        constraints: dict[str, Any],
        existing_work_blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        scheduled_at = datetime.now()
        existing_work_blocks = existing_work_blocks or []

        # 1. Build timeline of hard constraints
        hard_constraints = self.algo.build_hard_constraints(external_events, meetings)

        # 2. Filter tasks that need scheduling
        tasks_to_schedule = self.algo.filter_tasks_needing_scheduling(tasks)

        # 3. Sort tasks by priority and urgency
        sorted_tasks = self.algo.sort_tasks_by_priority(tasks_to_schedule)

        scheduled_tasks: list[dict[str, Any]] = []
        unscheduled_tasks: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []

        # 4. Schedule each task
        for task in sorted_tasks:
            result = await self._schedule_single_task(
                task, hard_constraints, constraints, existing_work_blocks
            )

            status = result["status"]
            if status in ["scheduled", "partially_scheduled"]:
                scheduled_tasks.append(result)
                existing_work_blocks.extend(result["workBlocks"])
            else:
                unscheduled_tasks.append(
                    {
                        "taskId": task["id"],
                        "reason": result.get("reason", "no_available_slots"),
                        "suggestedAction": self.algo.get_suggested_action(
                            task, result.get("reason")
                        ),
                    }
                )

        total_work_blocks = sum(len(st["workBlocks"]) for st in scheduled_tasks)
        total_focus_time = sum(
            sum(wb["duration"] for wb in st["workBlocks"]) for st in scheduled_tasks
        )

        return {
            "userId": user_id,
            "scheduledAt": scheduled_at,
            "scheduledTasks": scheduled_tasks,
            "unscheduledTasks": unscheduled_tasks,
            "conflicts": conflicts,
            "statistics": {
                "totalTasks": len(tasks),
                "scheduledCount": len(scheduled_tasks),
                "unscheduledCount": len(unscheduled_tasks),
                "totalWorkBlocks": total_work_blocks,
                "totalFocusTime": total_focus_time,
                "schedulingEfficiency": self.algo.calculate_scheduling_efficiency(
                    hard_constraints, scheduled_tasks, constraints
                ),
            },
        }

    async def run_scheduling_pipeline(
        self,
        user_id: str,
        db: AsyncSession,
        socket_server=None,
        emit_socket: bool = True,
    ) -> None:
        user_repo = UsersRepository(db)
        tasks_repo = TasksRepository(db)
        time_blocks_repo = TimeBlocksRepository(db)

        user = await user_repo.get_by_id(user_id)
        if not user:
            return

        settings = user.settings or {}
        work_hours_config = settings.get("workHours", {})
        if not work_hours_config.get("enabled", True):
            return

        working_days = [d.lower() for d in work_hours_config.get("selectedDays", [])]
        constraints = {
            "userId": user_id,
            "workingDays": working_days
            if working_days
            else ["mon", "tue", "wed", "thu", "fri"],
            "workingHours": {
                "start": work_hours_config.get("startTime", "09:00"),
                "end": work_hours_config.get("endTime", "17:00"),
            },
            "breakDuration": 15,
            "breakInterval": 90,
            "preferredFocusBlockDuration": 60,
            "minFocusBlockDuration": 30,
            "maxFocusBlockDuration": 120,
            "schedulingStrategy": "balanced",
            "allowSameDaySplitting": True,
            "allowOvertime": False,
            "goldenWindow": {"start": "09:00", "end": "11:00"},
        }

        tasks = await tasks_repo.get_all_active_by_user(user_id)
        tasks_list = []
        for t in tasks:
            tasks_list.append(
                {
                    "id": t.id,
                    "userId": t.userId,
                    "title": t.title,
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
                    "tags": t.tags or [],
                    "links": t.links or [],
                    "collaborators": getattr(t, "collaborators", None) or [],
                    "use_ai": t.use_ai or False,
                }
            )

        time_blocks = await time_blocks_repo.get_all_by_user(user_id)

        from app.modules.task.services.migration_service import MigrationService
        migrator = MigrationService()

        external_events = []
        meetings = []
        new_tasks = []
        existing_work_blocks = []

        for t in tasks_list:
            migrated = migrator.migrate_task(t)
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
                "createdAt": tb.createdAt,
            }
            existing_work_blocks.append(migrator.migrate_time_block(tb_dict))

        res = await self.schedule(
            user_id=user_id,
            external_events=external_events,
            meetings=meetings,
            tasks=new_tasks,
            constraints=constraints,
            existing_work_blocks=existing_work_blocks,
        )

        new_time_blocks = []
        for st in res["scheduledTasks"]:
            for wb in st["workBlocks"]:
                new_time_blocks.append(
                    TimeBlock(
                        id=wb["id"],
                        userId=user_id,
                        taskId=wb["taskId"],
                        startTime=wb["start"],
                        endTime=wb["end"],
                        blockType="Focus_Block",
                        source="App",
                        title="Focus Block",
                    )
                )

        async with transaction_scope(db):
            await time_blocks_repo.replace_focus_blocks(user_id, new_time_blocks)

            for st in res["scheduledTasks"]:
                t_id = st["taskId"]
                wbs = st["workBlocks"]
                if wbs:
                    sorted_wbs = sorted(wbs, key=lambda x: x["start"])
                    first_wb = sorted_wbs[0]
                    last_wb = sorted_wbs[-1]

                    t_obj = await tasks_repo.get_by_id(t_id)
                    if t_obj:
                        new_start = first_wb["start"]
                        if t_obj.estimated_start_date != new_start:
                            t_obj.notified = False
                            t_obj.lastMinuteNotified = False
                        t_obj.estimated_start_date = new_start
                        t_obj.estimated_end_date = last_wb["end"]
                        t_obj.status = "Scheduled"
                        t_obj.updatedAt = datetime.utcnow()
                        await tasks_repo.save(t_obj)

        if socket_server and emit_socket:
            try:
                await socket_server.emit(
                    "schedule_updated",
                    {
                        "type": "SCHEDULE_RECALCULATED",
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                    room=f"user_{user_id}",
                    namespace="/realtime",
                )
            except Exception:
                pass
