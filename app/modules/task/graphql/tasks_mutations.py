import strawberry

from app.graphql import types
from app.graphql.common import get_user_id
from app.modules.task.services.tasks_service import TasksService
from app.modules.auth.services.auth_service import AuthService


@strawberry.type
class TaskMutation:
    @strawberry.mutation
    async def create_task(self, info, create_task_input: types.CreateTaskInput) -> types.Task:
        get_user_id(info)
        db = info.context["db"]
        
        from app.modules.google_calendar.services.google_calendar_service import GoogleCalendarService
        from app.modules.task.services.scheduler_service import SchedulerService
        from app.sockets.realtime import realtime_gateway

        auth_serv = AuthService(db)
        tasks_serv = TasksService(db, socket_server=realtime_gateway)
        sched_serv = SchedulerService()
        gc_service = GoogleCalendarService(db, auth_serv, tasks_serv, sched_serv)
        tasks_serv.google_calendar_service = gc_service

        # Convert input
        task_data = {
            "userId": create_task_input.user_id,
            "title": create_task_input.title,
            "notesEncrypted": create_task_input.notes_encrypted,
            "estimateTimer": create_task_input.estimate_timer,
            "realTimer": create_task_input.real_timer,
            "duration": create_task_input.duration,
            "priorityLevel": create_task_input.priority_level,
            "deadline": create_task_input.deadline,
            "category": create_task_input.category,
            "color": create_task_input.color,
            "status": create_task_input.status,
            "tags": [{"name": t} for t in create_task_input.tags] if create_task_input.tags else [],
            "links": [{"title": l.title, "url": l.url} for l in create_task_input.links] if create_task_input.links else [],
            "task_type": create_task_input.task_type or "PlatformTask",
            "google_event_id": create_task_input.google_event_id,
            "estimated_start_date": create_task_input.estimated_start_date,
            "estimated_end_date": create_task_input.estimated_end_date,
            "source": create_task_input.source,
            "sync_status": create_task_input.sync_status,
            "collaborators": [
                {
                    "name": c.name,
                    "email": c.email,
                    "avatar": c.avatar,
                    "responseStatus": c.responseStatus
                } for c in create_task_input.collaborators
            ] if create_task_input.collaborators else [],
            "use_ai": create_task_input.use_ai
        }

        res = await tasks_serv.create(task_data)
        return types.map_dict_to_strawberry_task(res)

    @strawberry.mutation
    async def update_task(self, info, update_task_input: types.UpdateTaskInput) -> types.Task:
        user_id = get_user_id(info)
        db = info.context["db"]
        
        from app.modules.google_calendar.services.google_calendar_service import GoogleCalendarService
        from app.modules.task.services.scheduler_service import SchedulerService
        from app.sockets.realtime import realtime_gateway

        auth_serv = AuthService(db)
        tasks_serv = TasksService(db, socket_server=realtime_gateway)
        sched_serv = SchedulerService()
        gc_service = GoogleCalendarService(db, auth_serv, tasks_serv, sched_serv)
        tasks_serv.google_calendar_service = gc_service

        update_data = {
            "userId": update_task_input.user_id if update_task_input.user_id is not None else user_id
        }
        if update_task_input.title is not None:
            update_data["title"] = update_task_input.title
        if update_task_input.notes_encrypted is not None:
            update_data["notesEncrypted"] = update_task_input.notes_encrypted
        if update_task_input.estimate_timer is not None:
            update_data["estimateTimer"] = update_task_input.estimate_timer
        if update_task_input.real_timer is not None:
            update_data["realTimer"] = update_task_input.real_timer
        if update_task_input.duration is not None:
            update_data["duration"] = update_task_input.duration
        if update_task_input.priority_level is not None:
            update_data["priorityLevel"] = update_task_input.priority_level
        if update_task_input.deadline is not None:
            update_data["deadline"] = update_task_input.deadline
        if update_task_input.category is not None:
            update_data["category"] = update_task_input.category
        if update_task_input.color is not None:
            update_data["color"] = update_task_input.color
        if update_task_input.status is not None:
            update_data["status"] = update_task_input.status
        if update_task_input.tags is not None:
            update_data["tags"] = [{"name": t} for t in update_task_input.tags]
        if update_task_input.links is not None:
            update_data["links"] = [{"title": l.title, "url": l.url} for l in update_task_input.links]
        if update_task_input.task_type is not None:
            update_data["task_type"] = update_task_input.task_type
        if update_task_input.google_event_id is not None:
            update_data["google_event_id"] = update_task_input.google_event_id
        if update_task_input.estimated_start_date is not None:
            update_data["estimated_start_date"] = update_task_input.estimated_start_date
        if update_task_input.estimated_end_date is not None:
            update_data["estimated_end_date"] = update_task_input.estimated_end_date
        if update_task_input.source is not None:
            update_data["source"] = update_task_input.source
        if update_task_input.sync_status is not None:
            update_data["sync_status"] = update_task_input.sync_status
        if update_task_input.collaborators is not None:
            update_data["collaborators"] = [
                {
                    "name": c.name,
                    "email": c.email,
                    "avatar": c.avatar,
                    "responseStatus": c.responseStatus
                } for c in update_task_input.collaborators
            ]
        if update_task_input.use_ai is not None:
            update_data["use_ai"] = update_task_input.use_ai

        res = await tasks_serv.update(str(update_task_input.id), update_data)
        return types.map_dict_to_strawberry_task(res)

    @strawberry.mutation
    async def delete_task(self, info, id: str) -> bool:
        get_user_id(info)
        db = info.context["db"]
        
        from app.modules.google_calendar.services.google_calendar_service import GoogleCalendarService
        from app.modules.task.services.scheduler_service import SchedulerService
        from app.sockets.realtime import realtime_gateway

        auth_serv = AuthService(db)
        tasks_serv = TasksService(db, socket_server=realtime_gateway)
        sched_serv = SchedulerService()
        gc_service = GoogleCalendarService(db, auth_serv, tasks_serv, sched_serv)
        tasks_serv.google_calendar_service = gc_service

        await tasks_serv.delete(id)
        return True

    @strawberry.mutation
    async def delete_tasks(self, info, ids: list[str]) -> bool:
        get_user_id(info)
        db = info.context["db"]
        
        from app.modules.google_calendar.services.google_calendar_service import GoogleCalendarService
        from app.modules.task.services.scheduler_service import SchedulerService
        from app.sockets.realtime import realtime_gateway

        auth_serv = AuthService(db)
        tasks_serv = TasksService(db, socket_server=realtime_gateway)
        sched_serv = SchedulerService()
        gc_service = GoogleCalendarService(db, auth_serv, tasks_serv, sched_serv)
        tasks_serv.google_calendar_service = gc_service

        await tasks_serv.delete_many(ids)
        return True

    @strawberry.mutation
    async def delete_workspace_tasks(self, info, workspace_id: str) -> bool:
        get_user_id(info)
        db = info.context["db"]
        
        from app.modules.google_calendar.services.google_calendar_service import GoogleCalendarService
        from app.modules.task.services.scheduler_service import SchedulerService
        from app.sockets.realtime import realtime_gateway

        auth_serv = AuthService(db)
        tasks_serv = TasksService(db, socket_server=realtime_gateway)
        sched_serv = SchedulerService()
        gc_service = GoogleCalendarService(db, auth_serv, tasks_serv, sched_serv)
        tasks_serv.google_calendar_service = gc_service

        await tasks_serv.delete_workspace_tasks(workspace_id)
        return True