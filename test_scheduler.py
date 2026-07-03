import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import async_session_local
from app.services.scheduler.scheduler_service import SchedulerService
from sqlalchemy.future import select
from app.models import User, Task, TimeBlock

async def main():
    async with async_session_local() as db:
        user_res = await db.execute(select(User))
        user = user_res.scalars().first()
        if not user:
            print("No user found")
            return
        
        print(f"Running scheduler for user: {user.id} ({user.email})")
        scheduler = SchedulerService()
        
        # We want to run the pipeline and print the results of the schedule() call.
        # Let's inspect what constraints, tasks, and time blocks it builds.
        settings_dict = user.settings or {}
        work_hours_config = settings_dict.get("workHoursConfig", {
            "selectedDays": ["Mon", "Tue", "Wed", "Thu", "Fri"],
            "startTime": "09:00",
            "endTime": "17:00"
        })
        
        working_days = [d.lower() for d in work_hours_config.get("selectedDays", [])]
        constraints = {
            "userId": user.id,
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

        # Fetch tasks
        result = await db.execute(select(Task).where(Task.userId == user.id, Task.deletedAt == None))
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

        # Fetch time blocks
        result = await db.execute(select(TimeBlock).where(TimeBlock.userId == user.id))
        time_blocks = result.scalars().all()
        
        from app.services.tasks.migration_service import MigrationService
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

        print(f"Tasks needing scheduling: {len(new_tasks)}")
        for nt in new_tasks:
            print(f"  - {nt['title']} (priority={nt['priorityValue']}, deadline={nt['deadline']})")

        res = await scheduler.schedule(
            user_id=user.id,
            external_events=external_events,
            meetings=meetings,
            tasks=new_tasks,
            constraints=constraints,
            existing_work_blocks=existing_work_blocks
        )

        print("\n--- SCHEDULER RESULTS ---")
        print(f"Scheduled Tasks: {len(res['scheduledTasks'])}")
        for st in res["scheduledTasks"]:
            print(f"  Task {st['taskId']}: status={st['status']}")
            for wb in st["workBlocks"]:
                print(f"    WorkBlock: start={wb['start']}, end={wb['end']}, duration={wb['duration']}")
        
        print(f"Unscheduled Tasks: {len(res['unscheduledTasks'])}")
        for ut in res["unscheduledTasks"]:
            print(f"  Task {ut['taskId']}: reason={ut['reason']}, action={ut['suggestedAction']}")

if __name__ == "__main__":
    asyncio.run(main())
