from http.cookies import SimpleCookie
from typing import Any
import jwt
import socketio
from socketio.exceptions import ConnectionRefusedError

from app.config import settings

# Redis-backed manager: without this, connected clients and rooms only
# exist in this process's memory, so emit() calls from another process
# (e.g. app/worker.py, or any other web replica) never reach them.
_client_manager = socketio.AsyncRedisManager(settings.REDIS_URL)

# Create async socketio server
sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=_client_manager,
    cors_allowed_origins=[
        "https://focusly-front-psi.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
)

# Create socketio app
socket_app = socketio.ASGIApp(sio, socketio_path="socket.io")


def _extract_token_from_handshake(environ: dict, auth: Any = None) -> str | None:
    # 1. Check socket.io auth dict (e.g. auth={"token": "..."})
    if auth:
        if isinstance(auth, dict):
            token = auth.get("token") or auth.get("access_token")
            if token:
                return token
        elif isinstance(auth, str) and auth.strip():
            return auth.strip()

    # 2. Check HTTP_COOKIE (set as httpOnly access_token cookie by /auth)
    cookie_str = environ.get("HTTP_COOKIE")
    if cookie_str:
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_str)
            if "access_token" in cookie:
                return cookie["access_token"].value
        except Exception:
            pass

    # 3. Check HTTP_AUTHORIZATION header (Bearer <token>)
    auth_header = environ.get("HTTP_AUTHORIZATION")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]

    return None


@sio.event(namespace="/realtime")
async def connect(sid, environ, auth=None):
    token = _extract_token_from_handshake(environ, auth)
    if not token:
        raise ConnectionRefusedError("Authentication required: no token provided")

    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            raise ConnectionRefusedError("Invalid token: sub missing")
    except jwt.ExpiredSignatureError:
        raise ConnectionRefusedError("Token expired")
    except jwt.InvalidTokenError:
        raise ConnectionRefusedError("Invalid token")

    await sio.enter_room(sid, f"user_{user_id}", namespace="/realtime")


@sio.event(namespace="/realtime")
async def disconnect(sid):
    pass


class RealTimeGateway:
    def __init__(self):
        self.sio = sio

    async def emitScheduleUpdate(self, user_id: str, data: Any):
        room_name = f"user_{user_id}"
        await self.sio.emit(
            "schedule_updated", data, room=room_name, namespace="/realtime"
        )

    async def emit_automation_result(
        self,
        user_id: str,
        workspace_id: str,
        tasks_created: list[dict],
    ):
        """
        Emite el evento 'automation_triggered' al frontend cuando el
        motor de automatización crea tareas automáticamente.

        El frontend escucha este evento y muestra un toast tipo:
          "⚡ 2 tareas creadas automáticamente desde el workspace"

        Payload enviado al frontend:
          {
            "workspaceId": "...",
            "tasksCreated": [
              {"taskId": "...", "taskTitle": "Revisar UI"},
              ...
            ],
            "count": 2
          }
        """
        room_name = f"user_{user_id}"
        await self.sio.emit(
            "automation_triggered",
            {
                "workspaceId": workspace_id,
                "tasksCreated": tasks_created,
                "count": len(tasks_created),
            },
            room=room_name,
            namespace="/realtime",
        )


# Singleton instance
realtime_gateway = RealTimeGateway()
