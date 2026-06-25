import strawberry

from app.graphql import types
from app.graphql.common import get_user_id
from app.services.folders.folders_service import FoldersService


@strawberry.type
class ProjectQuery:
    @strawberry.field
    async def projects(self, info, group_id: str | None = None) -> list[types.Project]:
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
                updated_at=f.updatedAt,
            )
            for f in res
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
            updated_at=res.updatedAt,
        )

    @strawberry.field
    async def total_projects(self, info) -> int:
        user_id = get_user_id(info)
        db = info.context["db"]
        folders_serv = FoldersService(db)
        return await folders_serv.get_total_folders(user_id)
