import strawberry

from app.graphql import types
from app.graphql.common import get_user_id
from app.modules.task.services.tasks_service import TasksService


@strawberry.type
class TaskQuery:
    @strawberry.field
    async def get_tasks(self, info) -> list[types.Task]:
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
        filters: types.TaskFilterInput | None = None,
        sort: types.TaskSortInput | None = None
    ) -> list[types.Task]:
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
        filters: types.TaskFilterInput | None = None,
        sort: types.TaskSortInput | None = None,
        offset: int | None = 0,
        limit: int | None = None
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
    ) -> list[types.Task]:
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