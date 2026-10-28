import strawberry

from app.graphql import types
from app.graphql.common import get_user_id
from app.modules.canvas.services.canvas_service import CanvasService


@strawberry.type
class CanvasQuery:
    @strawberry.field
    async def canvas(self, info, id: strawberry.ID) -> types.Canvas:
        user_id = get_user_id(info)
        db = info.context["db"]
        canvas_serv = CanvasService(db)
        res = await canvas_serv.find_one(str(id), user_id)
        return types.map_model_to_strawberry_canvas(res)

    # Links to the images a canvas uses, loaded when it opens
    @strawberry.field
    async def canvas_files(self, info, canvas_id: strawberry.ID) -> list[types.CanvasFile]:
        user_id = get_user_id(info)
        db = info.context["db"]
        canvas_serv = CanvasService(db)
        files = await canvas_serv.file_urls(str(canvas_id), user_id)
        return [
            types.CanvasFile(id=f["id"], mime_type=f["mimeType"], url=f["url"])
            for f in files
        ]

    # Metadata only: scenes are read one at a time, when a canvas is opened.
    @strawberry.field
    async def canvases_by_workspace(
        self, info, workspace_id: strawberry.ID
    ) -> list[types.Canvas]:
        user_id = get_user_id(info)
        db = info.context["db"]
        canvas_serv = CanvasService(db)
        res = await canvas_serv.find_by_workspace(str(workspace_id), user_id)
        return [types.map_model_to_strawberry_canvas(c, include_data=False) for c in res]
