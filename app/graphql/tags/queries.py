import strawberry

from app.graphql import types
from app.graphql.common import get_user_id
from app.services.tags.tags_service import TagsService


@strawberry.type
class TagQuery:
    @strawberry.field
    async def get_tags_by_user(self, info, user_id: str) -> list[types.Tag]:
        get_user_id(info)
        db = info.context["db"]
        tags_serv = TagsService(db)
        res = await tags_serv.find_all_by_user(user_id)
        return [types.Tag(name=t.name) for t in res]
