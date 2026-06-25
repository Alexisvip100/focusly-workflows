import strawberry

from app.graphql import types
from app.graphql.common import get_user_id
from app.services.workspaces.workspaces_service import WorkspacesService


@strawberry.type
class WorkspaceQuery:
    @strawberry.field
    async def workspaces(
        self,
        info,
        search: str | None = None,
        project_id: str | None = None,
        group_id: str | None = None,
    ) -> list[types.Workspace]:
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
                updatedAt=w.updatedAt,
            )
            for w in res
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
            updatedAt=res.updatedAt,
        )

    @strawberry.field
    async def total_workspaces(self, info) -> int:
        user_id = get_user_id(info)
        db = info.context["db"]
        ws_serv = WorkspacesService(db)
        return await ws_serv.get_total_workspaces(user_id)
