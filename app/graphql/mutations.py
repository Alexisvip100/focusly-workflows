import strawberry
from typing import List, Optional, Any, Dict, Annotated
from datetime import datetime

from app.graphql import types
from app.services.tasks.tasks_service import TasksService
from app.services.folders.folders_service import FoldersService
from app.services.workspaces.workspaces_service import WorkspacesService
from app.services.auth.auth_service import AuthService

def get_user_id(info) -> str:
    user_id = info.context.get("user_id")
    if not user_id:
        raise Exception("Unauthorized: user is not authenticated")
    return user_id

@strawberry.type
class Mutation:
    # Auth Mutations
    @strawberry.mutation
    async def google_login(self, info, code: str) -> types.AuthResponse:
        db = info.context["db"]
        request = info.context.get("request")
        origin = request.headers.get("origin") if request else None
        auth_service = AuthService(db)
        try:
            result = await auth_service.validate_google_token(code, redirect_uri=origin)
            
            # Map user
            u = result["user"]
            settings_dict = u.get("settings")
            u_settings = None
            if isinstance(settings_dict, dict):
                work_config = settings_dict.get("workHoursConfig") or {}
                u_settings = types.UserSettings(
                    focus_duration_pref=settings_dict.get("focusDurationPref"),
                    break_duration_pref=settings_dict.get("breakDurationPref"),
                    notifications_enabled=settings_dict.get("notificationsEnabled")
                )

            user_obj = types.User(
                id=strawberry.ID(u["id"]),
                email=u["email"],
                name=u.get("name"),
                picture=u.get("picture"),
                role=u.get("role"),
                auth_provider=u.get("authProvider"),
                google_refresh_token=u.get("googleRefreshToken"),
                subscription_status=u.get("subscriptionStatus", "free"),
                settings=u_settings,
                bio=u.get("bio")
            )
            return types.AuthResponse(
                access_token=result["access_token"],
                user=user_obj,
                google_access_token=result.get("google_access_token")
            )
        except Exception as e:
            print("GraphQL googleLogin error:", e)
            raise Exception(f"Google login failed: {str(e)}")

    # Task Mutations
    @strawberry.mutation
    async def create_task(self, info, create_task_input: types.CreateTaskInput) -> types.Task:
        get_user_id(info)
        db = info.context["db"]
        
        from app.services.google_calendar.google_calendar_service import GoogleCalendarService
        from app.services.scheduler.scheduler_service import SchedulerService
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
        get_user_id(info)
        db = info.context["db"]
        
        from app.services.google_calendar.google_calendar_service import GoogleCalendarService
        from app.services.scheduler.scheduler_service import SchedulerService
        from app.sockets.realtime import realtime_gateway

        auth_serv = AuthService(db)
        tasks_serv = TasksService(db, socket_server=realtime_gateway)
        sched_serv = SchedulerService()
        gc_service = GoogleCalendarService(db, auth_serv, tasks_serv, sched_serv)
        tasks_serv.google_calendar_service = gc_service

        update_data = {}
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
        
        from app.services.google_calendar.google_calendar_service import GoogleCalendarService
        from app.services.scheduler.scheduler_service import SchedulerService
        from app.sockets.realtime import realtime_gateway

        auth_serv = AuthService(db)
        tasks_serv = TasksService(db, socket_server=realtime_gateway)
        sched_serv = SchedulerService()
        gc_service = GoogleCalendarService(db, auth_serv, tasks_serv, sched_serv)
        tasks_serv.google_calendar_service = gc_service

        await tasks_serv.delete(id)
        return True

    @strawberry.mutation
    async def delete_tasks(self, info, ids: List[str]) -> bool:
        get_user_id(info)
        db = info.context["db"]
        
        from app.services.google_calendar.google_calendar_service import GoogleCalendarService
        from app.services.scheduler.scheduler_service import SchedulerService
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
        
        from app.services.google_calendar.google_calendar_service import GoogleCalendarService
        from app.services.scheduler.scheduler_service import SchedulerService
        from app.sockets.realtime import realtime_gateway

        auth_serv = AuthService(db)
        tasks_serv = TasksService(db, socket_server=realtime_gateway)
        sched_serv = SchedulerService()
        gc_service = GoogleCalendarService(db, auth_serv, tasks_serv, sched_serv)
        tasks_serv.google_calendar_service = gc_service

        await tasks_serv.delete_workspace_tasks(workspace_id)
        return True

    # Folder Mutations
    @strawberry.mutation
    async def create_folder(self, info, create_folder_input: types.CreateFolderInput) -> types.Folder:
        user_id = get_user_id(info)
        db = info.context["db"]
        folders_serv = FoldersService(db)
        create_data = {
            "name": create_folder_input.name,
            "color": create_folder_input.color
        }
        res = await folders_serv.create(create_data, user_id)
        return types.Folder(
            id=strawberry.ID(res.id),
            name=res.name,
            user_id=res.userId,
            color=res.color,
            created_at=res.createdAt,
            updated_at=res.updatedAt
        )

    @strawberry.mutation
    async def update_folder(self, info, update_folder_input: types.UpdateFolderInput) -> types.Folder:
        user_id = get_user_id(info)
        db = info.context["db"]
        folders_serv = FoldersService(db)
        
        update_data = {}
        if update_folder_input.name is not None:
            update_data["name"] = update_folder_input.name
        if update_folder_input.color is not None:
            update_data["color"] = update_folder_input.color

        res = await folders_serv.update(str(update_folder_input.id), update_data, user_id)
        return types.Folder(
            id=strawberry.ID(res.id),
            name=res.name,
            user_id=res.userId,
            color=res.color,
            created_at=res.createdAt,
            updated_at=res.updatedAt
        )

    @strawberry.mutation
    async def remove_folder(self, info, id: strawberry.ID) -> bool:
        user_id = get_user_id(info)
        db = info.context["db"]
        folders_serv = FoldersService(db)
        return await folders_serv.remove(str(id), user_id)

    # Workspace Mutations
    @strawberry.mutation
    async def create_workspace(self, info, create_workspace_input: types.CreateWorkspaceInput) -> types.Workspace:
        user_id = get_user_id(info)
        db = info.context["db"]
        ws_serv = WorkspacesService(db)
        
        create_data = {
            "userId": user_id,
            "title": create_workspace_input.title,
            "emoji": create_workspace_input.emoji,
            "background_color": create_workspace_input.background_color,
            "card_show_background": create_workspace_input.card_show_background,
            "content": create_workspace_input.content,
            "taskId": create_workspace_input.taskId,
            "folderId": create_workspace_input.folderId,
            "saveStatus": create_workspace_input.saveStatus if create_workspace_input.saveStatus is not None else False
        }
        res = await ws_serv.create(create_data, user_id)
        return types.Workspace(
            id=strawberry.ID(res.id),
            userId=res.userId,
            taskId=res.taskId,
            title=res.title,
            emoji=res.emoji,
            background_color=res.background_color,
            card_show_background=res.card_show_background,
            folderId=res.folderId,
            content=res.content,
            saveStatus=res.saveStatus,
            createdAt=res.createdAt,
            updatedAt=res.updatedAt
        )

    @strawberry.mutation
    async def update_workspace(self, info, update_workspace_input: types.UpdateWorkspaceInput) -> types.Workspace:
        user_id = get_user_id(info)
        db = info.context["db"]
        ws_serv = WorkspacesService(db)
        
        update_data = {}
        if update_workspace_input.title is not None:
            update_data["title"] = update_workspace_input.title
        if update_workspace_input.emoji is not None:
            update_data["emoji"] = update_workspace_input.emoji
        if update_workspace_input.background_color is not None:
            update_data["background_color"] = update_workspace_input.background_color
        if update_workspace_input.card_show_background is not None:
            update_data["card_show_background"] = update_workspace_input.card_show_background
        if update_workspace_input.folderId is not None:
            update_data["folderId"] = update_workspace_input.folderId
        if update_workspace_input.content is not None:
            update_data["content"] = update_workspace_input.content
        if update_workspace_input.taskId is not None:
            update_data["taskId"] = update_workspace_input.taskId
        if update_workspace_input.saveStatus is not None:
            update_data["saveStatus"] = update_workspace_input.saveStatus

        res = await ws_serv.update(str(update_workspace_input.id), update_data, user_id)
        return types.Workspace(
            id=strawberry.ID(res.id),
            userId=res.userId,
            taskId=res.taskId,
            title=res.title,
            emoji=res.emoji,
            background_color=res.background_color,
            card_show_background=res.card_show_background,
            folderId=res.folderId,
            content=res.content,
            saveStatus=res.saveStatus,
            createdAt=res.createdAt,
            updatedAt=res.updatedAt
        )

    @strawberry.mutation
    async def remove_workspace(self, info, id: strawberry.ID) -> bool:
        user_id = get_user_id(info)
        db = info.context["db"]
        ws_serv = WorkspacesService(db)
        return await ws_serv.remove(str(id), user_id)
