import strawberry

from app.graphql import types
from app.graphql.common import get_user_id
from app.services.workspaces.workspaces_service import WorkspacesService


@strawberry.type
class WorkspaceMutation:
    @strawberry.mutation
    async def create_workspace(
        self, info, create_workspace_input: types.CreateWorkspaceInput
    ) -> types.Workspace:
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
            "folderId": create_workspace_input.projectId,
            "groupId": create_workspace_input.groupId,
            "saveStatus": create_workspace_input.saveStatus
            if create_workspace_input.saveStatus is not None
            else False,
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
            projectId=res.folderId,
            groupId=res.groupId,
            content=res.content,
            saveStatus=res.saveStatus,
            createdAt=res.createdAt,
            updatedAt=res.updatedAt,
        )

    @strawberry.mutation
    async def update_workspace(
        self, info, update_workspace_input: types.UpdateWorkspaceInput
    ) -> types.Workspace:
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
            update_data["card_show_background"] = (
                update_workspace_input.card_show_background
            )
        if update_workspace_input.projectId is not None:
            update_data["folderId"] = update_workspace_input.projectId
        if update_workspace_input.groupId is not None:
            update_data["groupId"] = update_workspace_input.groupId
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
            projectId=res.folderId,
            groupId=res.groupId,
            content=res.content,
            saveStatus=res.saveStatus,
            createdAt=res.createdAt,
            updatedAt=res.updatedAt,
        )

    @strawberry.mutation
    async def remove_workspace(self, info, id: strawberry.ID) -> bool:
        user_id = get_user_id(info)
        db = info.context["db"]
        ws_serv = WorkspacesService(db)
        return await ws_serv.remove(str(id), user_id)
