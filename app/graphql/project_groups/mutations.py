import strawberry

from app.graphql import types
from app.graphql.common import get_user_id
from app.services.project_groups.project_groups_service import ProjectGroupsService


@strawberry.type
class ProjectGroupMutation:
    @strawberry.mutation
    async def create_project_group(
        self, info, input: types.CreateProjectGroupInput
    ) -> types.ProjectGroup:
        user_id = get_user_id(info)
        db = info.context["db"]
        pg_serv = ProjectGroupsService(db)
        create_data = {"name": input.name, "color": input.color, "emoji": input.emoji}
        res = await pg_serv.create(create_data, user_id)
        return types.ProjectGroup(
            id=strawberry.ID(res.id),
            name=res.name,
            user_id=res.userId,
            color=res.color,
            emoji=res.emoji,
            created_at=res.createdAt,
            updated_at=res.updatedAt,
        )

    @strawberry.mutation
    async def update_project_group(
        self, info, input: types.UpdateProjectGroupInput
    ) -> types.ProjectGroup:
        user_id = get_user_id(info)
        db = info.context["db"]
        pg_serv = ProjectGroupsService(db)

        update_data = {}
        if input.name is not None:
            update_data["name"] = input.name
        if input.color is not None:
            update_data["color"] = input.color
        if input.emoji is not None:
            update_data["emoji"] = input.emoji

        res = await pg_serv.update(str(input.id), update_data, user_id)
        return types.ProjectGroup(
            id=strawberry.ID(res.id),
            name=res.name,
            user_id=res.userId,
            color=res.color,
            emoji=res.emoji,
            created_at=res.createdAt,
            updated_at=res.updatedAt,
        )

    @strawberry.mutation
    async def remove_project_group(self, info, id: strawberry.ID) -> bool:
        user_id = get_user_id(info)
        db = info.context["db"]
        pg_serv = ProjectGroupsService(db)
        return await pg_serv.remove(str(id), user_id)
