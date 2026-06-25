import strawberry

from app.graphql import types
from app.graphql.common import get_user_id
from app.services.project_groups.project_groups_service import ProjectGroupsService


@strawberry.type
class ProjectGroupQuery:
    @strawberry.field
    async def project_groups(self, info) -> list[types.ProjectGroup]:
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
                updated_at=g.updatedAt,
            )
            for g in res
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
            updated_at=res.updatedAt,
        )
