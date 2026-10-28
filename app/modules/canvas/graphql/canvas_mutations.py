from typing import Any

import strawberry

from app.graphql import types
from app.graphql.common import get_user_id
from app.modules.canvas.services.canvas_service import CanvasService


@strawberry.type
class CanvasMutation:
    @strawberry.mutation
    async def create_canvas(
        self, info, input: types.CreateCanvasInput
    ) -> types.Canvas:
        user_id = get_user_id(info)
        db = info.context["db"]
        canvas_serv = CanvasService(db)

        create_data: dict[str, Any] = {
            "name": input.name,
            "workspaceId": input.workspace_id,
        }
        if input.icon is not None:
            create_data["icon"] = input.icon
        if input.data is not None:
            create_data["data"] = input.data

        res = await canvas_serv.create(create_data, user_id)
        return types.map_model_to_strawberry_canvas(res)

    # The autosave. The client already holds the scene it sent, so the
    # response leaves it out rather than echo it back on every save.
    @strawberry.mutation
    async def update_canvas(
        self, info, input: types.UpdateCanvasInput
    ) -> types.Canvas:
        user_id = get_user_id(info)
        db = info.context["db"]
        canvas_serv = CanvasService(db)

        update_data: dict[str, Any] = {}
        if input.name is not None:
            update_data["name"] = input.name
        if input.icon is not None:
            update_data["icon"] = input.icon
        if input.data is not None:
            update_data["data"] = input.data

        res = await canvas_serv.update(str(input.id), update_data, user_id)
        return types.map_model_to_strawberry_canvas(res, include_data=False)

    # Where the browser uploads an image pasted into the canvas
    @strawberry.mutation
    async def create_canvas_file_upload(
        self, info, input: types.CreateCanvasFileUploadInput
    ) -> types.CanvasFileUpload:
        user_id = get_user_id(info)
        db = info.context["db"]
        canvas_serv = CanvasService(db)
        upload_url = await canvas_serv.create_file_upload(
            str(input.canvas_id), user_id, input.file_id, input.mime_type, input.size
        )
        return types.CanvasFileUpload(upload_url=upload_url)

    @strawberry.mutation
    async def remove_canvas(self, info, id: strawberry.ID) -> bool:
        user_id = get_user_id(info)
        db = info.context["db"]
        canvas_serv = CanvasService(db)
        return await canvas_serv.remove(str(id), user_id)
