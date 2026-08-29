import asyncio
import jwt
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter
import socketio

from app.config import settings
from app.database import async_session_local
from app.sockets.realtime import sio
from app.modules.auth.presentation.rest import router as auth_router
from app.modules.user.presentation.rest import router as users_router
from app.modules.google_calendar.presentation.rest import (
    router as google_calendar_router,
)
from app.modules.task.presentation.rest import time_blocks_router
from app.modules.ai.presentation.rest import ai_router, planner_router
from app.modules.storage.presentation.rest import router as storage_router


from app.database import engine, Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connect shared resources on startup, clean up on shutdown.

    The recurring notification loops (task/smart notifier) no longer run
    here — they run once, in their own process, via app/worker.py — so
    scaling this web service to multiple replicas doesn't duplicate them.
    """
    from app.redis import cache
    from app.modules.storage.services.storage_service import (
        ensure_avatars_bucket_ready,
    )

    await cache.connect()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        ensure_avatars_bucket_ready()
    except Exception as e:
        # Non-fatal: avatar upload/removal will fail until MinIO is
        # reachable, but the rest of the API (tasks, calendar, AI, etc.)
        # shouldn't go down over a storage dependency that isn't core.
        print(f"Warning: could not initialize avatars bucket: {e}", flush=True)

    yield
    await cache.disconnect()


from fastapi.responses import JSONResponse

# 1. Initialize FastAPI
fastapi_app = FastAPI(title="Focusly Backend", version="1.0.0", lifespan=lifespan)


@fastapi_app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    response = JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "error": str(exc)},
    )

    origin = request.headers.get("origin")
    if origin in [
        "https://focusly-front-psi.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000",
    ]:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"

    return response


# 2. CORS Middleware
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://focusly-front-psi.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Mount REST Routers
fastapi_app.include_router(auth_router)
fastapi_app.include_router(users_router)
fastapi_app.include_router(google_calendar_router)
fastapi_app.include_router(time_blocks_router)
fastapi_app.include_router(ai_router)
fastapi_app.include_router(planner_router)
fastapi_app.include_router(storage_router)


# 4. GraphQL Setup with session management and auth context
@fastapi_app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    if request.url.path.startswith("/graphql"):
        async with async_session_local() as db:
            request.state.db = db
            # A single AsyncSession is shared by every resolver in this
            # request (see get_context below). Sibling GraphQL fields —
            # e.g. each item's nested `workspace`/`workspaces` field when a
            # list of Tasks/ProjectGroups is queried — resolve concurrently,
            # and SQLAlchemy's AsyncSession raises InvalidRequestError
            # ("concurrent operations are not permitted") if two coroutines
            # call it at once. This lock serializes those DB calls without
            # requiring a separate session per resolver.
            request.state.db_lock = asyncio.Lock()
            response = await call_next(request)
            return response
    else:
        return await call_next(request)


async def get_context(request: Request):
    db = getattr(request.state, "db", None)
    db_lock = getattr(request.state, "db_lock", None)

    # Extract user ID from cookies or Authorization header
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    user_id = None
    if token:
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
            user_id = payload.get("sub")
        except Exception:
            pass  # Invalid token, keep user_id = None

    return {"db": db, "db_lock": db_lock, "user_id": user_id, "request": request}


from typing import Any

from app.graphql import schema

graphql_router: GraphQLRouter[Any, Any] = GraphQLRouter(
    schema, context_getter=get_context
)
fastapi_app.include_router(graphql_router, prefix="/graphql")


# Root / health check endpoint
@fastapi_app.get("/")
async def root():
    return {"status": "ok", "service": "focusly-back-python"}


# 5. Combined ASGI App with Socket.io wrapper
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app, socketio_path="socket.io")
