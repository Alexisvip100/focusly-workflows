import strawberry

from app.graphql import types
from app.graphql.common import get_user_id
from app.services.folders.folders_service import FoldersService


@strawberry.type
class ProjectMutation:
    @strawberry.mutation
    async def create_project(
        self, info, create_project_input: types.CreateProjectInput
    ) -> types.Project:
        user_id = get_user_id(info)
        db = info.context["db"]
        folders_serv = FoldersService(db)
        create_data = {
            "name": create_project_input.name,
            "color": create_project_input.color,
            "groupId": create_project_input.groupId,
        }
        res = await folders_serv.create(create_data, user_id)
        return types.Project(
            id=strawberry.ID(res.id),
            name=res.name,
            user_id=res.userId,
            color=res.color,
            group_id=res.groupId,
            created_at=res.createdAt,
            updated_at=res.updatedAt,
        )

    @strawberry.mutation
    async def update_project(
        self, info, update_project_input: types.UpdateProjectInput
    ) -> types.Project:
        user_id = get_user_id(info)
        db = info.context["db"]
        folders_serv = FoldersService(db)

        update_data = {}
        if update_project_input.name is not None:
            update_data["name"] = update_project_input.name
        if update_project_input.color is not None:
            update_data["color"] = update_project_input.color
        if update_project_input.groupId is not None:
            update_data["groupId"] = update_project_input.groupId

        res = await folders_serv.update(
            str(update_project_input.id), update_data, user_id
        )
        return types.Project(
            id=strawberry.ID(res.id),
            name=res.name,
            user_id=res.userId,
            color=res.color,
            group_id=res.groupId,
            created_at=res.createdAt,
            updated_at=res.updatedAt,
        )

    @strawberry.mutation
    async def remove_project(self, info, id: strawberry.ID) -> bool:
        user_id = get_user_id(info)
        db = info.context["db"]
        folders_serv = FoldersService(db)
        return await folders_serv.remove(str(id), user_id)
