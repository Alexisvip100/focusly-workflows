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
from app.modules.auth.routes import router as auth_router
from app.modules.user.routes import router as users_router
from app.modules.google_calendar.routes import router as google_calendar_router
from app.modules.task.routes.time_blocks import router as time_blocks_router
from app.modules.ai.routes.ai import router as ai_router
from app.modules.ai.routes.planner import router as planner_router
from app.modules.notification.services.task_notifier_service import run_task_notifier_loop
from app.modules.notification.services.smart_notifier_service import run_smart_notifier_loop


from app.database import engine, Base

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background tasks on startup, clean up on shutdown."""
    from app.redis import cache
    await cache.connect()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    notifier_task = asyncio.create_task(run_task_notifier_loop())
    smart_notifier_task = asyncio.create_task(run_smart_notifier_loop())
    yield
    notifier_task.cancel()
    smart_notifier_task.cancel()
    try:
        await notifier_task
    except asyncio.CancelledError:
        pass
    try:
        await smart_notifier_task
    except asyncio.CancelledError:
        pass
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

# 4. GraphQL Setup with session management and auth context
@fastapi_app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    if request.url.path.startswith("/graphql"):
        async with async_session_local() as db:
            request.state.db = db
            response = await call_next(request)
            return response
    else:
        return await call_next(request)

async def get_context(request: Request):
    db = getattr(request.state, "db", None)
    
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
            pass # Invalid token, keep user_id = None

    return {
        "db": db,
        "user_id": user_id,
        "request": request
    }

from app.graphql import schema
graphql_router = GraphQLRouter(schema, context_getter=get_context)
fastapi_app.include_router(graphql_router, prefix="/graphql")

# Root / health check endpoint
@fastapi_app.get("/")
async def root():
    return {"status": "ok", "service": "focusly-back-python"}

# 5. Combined ASGI App with Socket.io wrapper
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app, socketio_path='socket.io')
