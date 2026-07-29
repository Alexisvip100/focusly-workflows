import strawberry

from app.graphql import types
from app.graphql.common import get_user_id
from app.modules.workspace.services.workspaces_service import WorkspacesService


@strawberry.type
class WorkspaceQuery:
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
            projectId=res.groupId,
            content=res.content,
            saveStatus=res.saveStatus,
            createdAt=res.createdAt,
            updatedAt=res.updatedAt,
        )

    @strawberry.field
    async def workspaces_paginated(
        self,
        info,
        search: str | None = None,
        projectId: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> types.PaginatedWorkspaces:
        user_id = get_user_id(info)
        db = info.context["db"]
        ws_serv = WorkspacesService(db)
        res = await ws_serv.find_all(
            user_id, search, group_id=projectId, limit=limit, offset=offset
        )
        workspaces_list = res.get("items", []) if isinstance(res, dict) else res
        total = res.get("total", 0) if isinstance(res, dict) else len(workspaces_list)
        has_more = res.get("hasMore", False) if isinstance(res, dict) else False

        mapped = [
            types.Workspace(
                id=strawberry.ID(w.id),
                userId=w.userId,
                taskId=w.taskId,
                title=w.title,
                emoji=w.emoji,
                background_color=w.background_color,
                card_show_background=w.card_show_background,
                projectId=w.groupId,
                content=w.content,
                saveStatus=w.saveStatus,
                createdAt=w.createdAt,
                updatedAt=w.updatedAt,
            )
            for w in workspaces_list
        ]
        return types.PaginatedWorkspaces(
            workspaces=mapped, totalCount=total, hasMore=has_more
        )
