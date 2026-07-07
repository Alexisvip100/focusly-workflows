import strawberry

from app.graphql import types
from app.graphql.common import get_user_id


@strawberry.type
class TagQuery:
    @strawberry.field
    async def get_tags_by_user(self, info, user_id: str, search_term: str | None = None) -> list[types.Tag]:
        get_user_id(info)
        db = info.context["db"]
        from app.models import Task
        from sqlalchemy import select
        
        result = await db.execute(
            select(Task).where(Task.userId == user_id, Task.deletedAt == None)
        )
        tasks = result.scalars().all()
        
        unique_tags = set()
        for t in tasks:
            if t.tags:
                for tag in t.tags:
                    if isinstance(tag, dict):
                        name = tag.get("name")
                        if name:
                            unique_tags.add(name.strip())
                    elif isinstance(tag, str):
                        unique_tags.add(tag.strip())
                        
        if search_term:
            term = search_term.strip().lower()
            unique_tags = {name for name in unique_tags if term in name.lower()}
                        
        return [types.Tag(name=name) for name in sorted(unique_tags)]