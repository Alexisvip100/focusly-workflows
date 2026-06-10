import strawberry
from typing import List, Optional, Any, Dict
from datetime import datetime

from app.graphql import types
from app.services.tasks.tasks_service import TasksService
from app.services.folders.folders_service import FoldersService
from app.services.workspaces.workspaces_service import WorkspacesService
from app.services.tags.tags_service import TagsService
from app.services.insights.insights_service import InsightsService
from app.services.project_groups.project_groups_service import ProjectGroupsService

# Helper to enforce auth
def get_user_id(info) -> str:
    user_id = info.context.get("user_id")
    if not user_id:
        raise Exception("Unauthorized: user is not authenticated")
    return user_id

@strawberry.type
class Query:
    @strawberry.field
    async def get_tasks(self, info) -> List[types.Task]:
        get_user_id(info)
        db = info.context["db"]
        tasks_serv = TasksService(db)
        res = await tasks_serv.find_all()
        return [types.map_dict_to_strawberry_task(t) for t in res]

    @strawberry.field
    async def get_tasks_by_user(
        self,
        info,
        user_id: str,
        filters: Optional[types.TaskFilterInput] = None,
        sort: Optional[types.TaskSortInput] = None
    ) -> List[types.Task]:
        get_user_id(info)
        db = info.context["db"]
        tasks_serv = TasksService(db)
        
        # Convert filters input to dict
        filters_dict = None
        if filters:
            filters_dict = {}
            if filters.status is not None:
                filters_dict["status"] = filters.status
            if filters.priorityLevel is not None:
                filters_dict["priorityLevel"] = filters.priorityLevel
            if filters.category is not None:
                filters_dict["category"] = filters.category
            if filters.startDate is not None:
                filters_dict["startDate"] = filters.startDate
            if filters.endDate is not None:
                filters_dict["endDate"] = filters.endDate
            if filters.searchTerm is not None:
                filters_dict["searchTerm"] = filters.searchTerm

        sort_dict = None
        if sort:
            sort_dict = {
                "sort": sort.sort,
                "order": sort.order or "asc"
            }

        res = await tasks_serv.find_all_by_user(user_id, filters_dict, sort_dict)
        return [types.map_dict_to_strawberry_task(t) for t in res]

    @strawberry.field
    async def get_tasks_by_user_paginated(
        self,
        info,
        user_id: str,
        filters: Optional[types.TaskFilterInput] = None,
        sort: Optional[types.TaskSortInput] = None,
        offset: Optional[int] = 0,
        limit: Optional[int] = None
    ) -> types.PaginatedTasks:
        get_user_id(info)
        db = info.context["db"]
        tasks_serv = TasksService(db)

        filters_dict = None
        if filters:
            filters_dict = {}
            if filters.status is not None:
                filters_dict["status"] = filters.status
            if filters.priorityLevel is not None:
                filters_dict["priorityLevel"] = filters.priorityLevel
            if filters.category is not None:
                filters_dict["category"] = filters.category
            if filters.startDate is not None:
                filters_dict["startDate"] = filters.startDate
            if filters.endDate is not None:
                filters_dict["endDate"] = filters.endDate
            if filters.searchTerm is not None:
                filters_dict["searchTerm"] = filters.searchTerm

        sort_dict = None
        if sort:
            sort_dict = {
                "sort": sort.sort,
                "order": sort.order or "asc"
            }

        paginated_res, total = await tasks_serv.find_paginated_by_user(
            user_id=user_id,
            filters=filters_dict,
            sort=sort_dict,
            offset=offset or 0,
            limit=limit
        )

        return types.PaginatedTasks(
            tasks=[types.map_dict_to_strawberry_task(t) for t in paginated_res],
            totalCount=total
        )

    @strawberry.field
    async def get_task(self, info, id: str) -> types.Task:
        get_user_id(info)
        db = info.context["db"]
        tasks_serv = TasksService(db)
        res = await tasks_serv.find_one(id)
        return types.map_dict_to_strawberry_task(res)

    @strawberry.field
    async def get_task_by_filters(
        self,
        info,
        filters: types.TaskFilterInput
    ) -> List[types.Task]:
        get_user_id(info)
        db = info.context["db"]
        tasks_serv = TasksService(db)

        filters_dict = {}
        if filters.status is not None:
            filters_dict["status"] = filters.status
        if filters.priorityLevel is not None:
            filters_dict["priorityLevel"] = filters.priorityLevel
        if filters.category is not None:
            filters_dict["category"] = filters.category

        res = await tasks_serv.filter_by_status(filters_dict)
        return [types.map_dict_to_strawberry_task(t) for t in res]

    # Projects Resolvers
    @strawberry.field
    async def projects(self, info, group_id: Optional[str] = None) -> List[types.Project]:
        user_id = get_user_id(info)
        db = info.context["db"]
        folders_serv = FoldersService(db)
        res = await folders_serv.find_all(user_id, group_id=group_id)
        return [
            types.Project(
                id=strawberry.ID(f.id),
                name=f.name,
                user_id=f.userId,
                color=f.color,
                group_id=f.groupId,
                created_at=f.createdAt,
                updated_at=f.updatedAt
            ) for f in res
        ]

    @strawberry.field
    async def project(self, info, id: strawberry.ID) -> types.Project:
        user_id = get_user_id(info)
        db = info.context["db"]
        folders_serv = FoldersService(db)
        res = await folders_serv.find_one(str(id), user_id)
        return types.Project(
            id=strawberry.ID(res.id),
            name=res.name,
            user_id=res.userId,
            color=res.color,
            group_id=res.groupId,
            created_at=res.createdAt,
            updated_at=res.updatedAt
        )

    @strawberry.field
    async def total_projects(self, info) -> int:
        user_id = get_user_id(info)
        db = info.context["db"]
        folders_serv = FoldersService(db)
        return await folders_serv.get_total_folders(user_id)

    # Workspace Resolvers
    @strawberry.field
    async def workspaces(
        self,
        info,
        search: Optional[str] = None,
        project_id: Optional[str] = None,
        group_id: Optional[str] = None
    ) -> List[types.Workspace]:
        user_id = get_user_id(info)
        db = info.context["db"]
        ws_serv = WorkspacesService(db)
        res = await ws_serv.find_all(user_id, search, project_id, group_id=group_id)
        return [
            types.Workspace(
                id=strawberry.ID(w.id),
                userId=w.userId,
                taskId=w.taskId,
                title=w.title,
                emoji=w.emoji,
                background_color=w.background_color,
                card_show_background=w.card_show_background,
                projectId=w.folderId,
                groupId=w.groupId,
                content=w.content,
                saveStatus=w.saveStatus,
                createdAt=w.createdAt,
                updatedAt=w.updatedAt
            ) for w in res
        ]

    @strawberry.field
    async def workspace(self, info, id: strawberry.ID) -> types.Workspace:
        user_id = get_user_id(info)
        db = info.context["db"]
        ws_serv = WorkspacesService(db)
        res = await ws_serv.find_one(str(id), user_id)
        return types.Workspace(
            id=strawberry.ID(res.id),
            userId=res.userId,
            taskId=res.taskId,
            title=res.title,
            emoji=res.emoji,
            background_color=res.background_color,
            card_show_background=res.card_show_background,
            projectId=res.folderId,
            groupId=res.groupId,
            content=res.content,
            saveStatus=res.saveStatus,
            createdAt=res.createdAt,
            updatedAt=res.updatedAt
        )

    @strawberry.field
    async def total_workspaces(self, info) -> int:
        user_id = get_user_id(info)
        db = info.context["db"]
        ws_serv = WorkspacesService(db)
        return await ws_serv.get_total_workspaces(user_id)

    # ProjectGroup Resolvers
    @strawberry.field
    async def project_groups(self, info) -> List[types.ProjectGroup]:
        user_id = get_user_id(info)
        db = info.context["db"]
        pg_serv = ProjectGroupsService(db)
        res = await pg_serv.find_all(user_id)
        return [
            types.ProjectGroup(
                id=strawberry.ID(g.id),
                name=g.name,
                user_id=g.userId,
                color=g.color,
                emoji=g.emoji,
                created_at=g.createdAt,
                updated_at=g.updatedAt
            ) for g in res
        ]

    @strawberry.field
    async def project_group(self, info, id: strawberry.ID) -> types.ProjectGroup:
        user_id = get_user_id(info)
        db = info.context["db"]
        pg_serv = ProjectGroupsService(db)
        res = await pg_serv.find_one(str(id), user_id)
        return types.ProjectGroup(
            id=strawberry.ID(res.id),
            name=res.name,
            user_id=res.userId,
            color=res.color,
            emoji=res.emoji,
            created_at=res.createdAt,
            updated_at=res.updatedAt
        )

    # Tags Resolver
    @strawberry.field
    async def get_tags_by_user(self, info, user_id: str) -> List[types.Tag]:
        get_user_id(info)
        db = info.context["db"]
        tags_serv = TagsService(db)
        res = await tags_serv.find_all_by_user(user_id)
        return [types.Tag(name=t.name) for t in res]

    # Insights Resolver
    @strawberry.field
    async def get_insights(
        self,
        info,
        user_id: str,
        filter: Optional[str] = "Weekly"
    ) -> types.InsightsResponse:
        get_user_id(info)
        db = info.context["db"]
        
        # Instantiate services needed by insights_service
        # Cyclic imports or direct
        from app.services.users.users_service import UsersService
        from app.services.focus_sessions.focus_sessions_service import FocusSessionsService
        
        users_serv = UsersService(db)
        tasks_serv = TasksService(db)
        fs_serv = FocusSessionsService(db)
        
        insights_serv = InsightsService(
            db=db,
            tasks_service=tasks_serv,
            focus_sessions_service=fs_serv,
            users_service=users_serv
        )
        
        res = await insights_serv.getInsights(user_id, filter or "Weekly")
        
        # Map ProductivityTrend
        trends = []
        for t in res["productivityTrends"]:
            trends.append(types.ProductivityTrend(
                label=t["label"],
                actual=float(t["actual"]),
                planned=float(t["planned"])
            ))
            
        # Map TimeDistribution
        dist = []
        for d in res["timeDistribution"]:
            dist.append(types.TimeDistribution(
                name=d["name"],
                value=float(d["value"]),
                color=d["color"]
            ))

        return types.InsightsResponse(
            total_focus_hours=types.StatCardValue(
                value=res["totalFocusHours"]["value"],
                change=res["totalFocusHours"]["change"],
                trend=res["totalFocusHours"]["trend"]
            ),
            task_completion=types.StatCardValue(
                value=res["taskCompletion"]["value"],
                change=res["taskCompletion"]["change"],
                trend=res["taskCompletion"]["trend"]
            ),
            energy_score=types.StatCardValue(
                value=res["energyScore"]["value"],
                change=res["energyScore"]["change"],
                trend=res["energyScore"]["trend"]
            ),
            golden_window=types.StatCardValue(
                value=res["goldenWindow"]["value"],
                change=res["goldenWindow"]["change"],
                trend=res["goldenWindow"]["trend"]
            ),
            break_hours=types.StatCardValue(
                value=res["breakHours"]["value"],
                change=res["breakHours"]["change"],
                trend=res["breakHours"]["trend"]
            ),
            productivity_trends=trends,
            time_distribution=dist,
            heatmap=res["heatmap"],
            heatmap_labels=res["heatmapLabels"]
        )
