from datetime import datetime, timezone
from typing import Any, Optional
import strawberry
from sqlalchemy import func, select

from app.models import Workspace as WorkspaceModel
from app.modules.workspace.services.workspaces_service import WorkspacesService

# ==============================================================================
# Helpers de Mapeo (DB / Dict -> Strawberry Types)
# ==============================================================================

def parse_iso_datetime(dt_val: str | datetime | None) -> datetime | None:
    if not dt_val:
        return None
    if isinstance(dt_val, datetime):
        return dt_val if dt_val.tzinfo else dt_val.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def map_model_to_strawberry_workspace(w: Any) -> "Workspace":
    # Soporta tanto modelos ORM de SQLAlchemy como diccionarios
    get_val = lambda key, default=None: (
        w.get(key, default) if isinstance(w, dict) else getattr(w, key, default)
    )
    raw_created = get_val("createdAt") or get_val("created_at")
    raw_updated = get_val("updatedAt") or get_val("updated_at")
    
    return Workspace(
        id=strawberry.ID(str(get_val("id"))),
        userId=str(get_val("userId") or get_val("user_id")),
        taskId=get_val("taskId") or get_val("task_id"),
        title=str(get_val("title", " ")),
        emoji=get_val("emoji"),
        background_color=get_val("background_color"),
        card_show_background=get_val("card_show_background"),
        projectId=get_val("groupId") or get_val("group_id") or get_val("projectId"),
        content=str(get_val("content", "")),  
        saveStatus=get_val("saveStatus") or get_val("save_status"),
        createdAt=parse_iso_datetime(raw_created) or datetime.now(timezone.utc),
        updatedAt=parse_iso_datetime(raw_updated) or datetime.now(timezone.utc),
    )


def map_model_to_strawberry_project_group(pg: Any) -> "ProjectGroup":
    get_val = lambda key, default=None: (
        pg.get(key, default) if isinstance(pg, dict) else getattr(pg, key, default)
    )
    raw_created = get_val("createdAt") or get_val("created_at")
    raw_updated = get_val("updatedAt") or get_val("updated_at")

    return ProjectGroup(
        id=strawberry.ID(str(get_val("id"))),
        name=str(get_val("name", "")),
        user_id=str(get_val("userId") or get_val("user_id")),
        color=get_val("color"),
        emoji=get_val("emoji"),
        created_at=parse_iso_datetime(raw_created) or datetime.now(timezone.utc),
        updated_at=parse_iso_datetime(raw_updated) or datetime.now(timezone.utc),
    )


# ==============================================================================
# Tipos Base y Auxiliares
# ==============================================================================

@strawberry.type
class Tag:
    name: str


@strawberry.type
class Collaborator:
    name: str | None = None
    email: str
    avatar: str | None = None
    response_status: str | None = strawberry.field(name="responseStatus", default=None)


@strawberry.type
class TaskLink:
    title: str
    url: str


@strawberry.type
class TimeLog:
    date: str
    minutes: int


@strawberry.type
class Subtask:
    id: str
    title: str
    completed: bool = False
    completed_at: str | None = strawberry.field(name="completed_at", default=None)
    estimate_timer: int | None = strawberry.field(name="estimate_timer", default=None)


@strawberry.type
class TaskFilters:
    status: list[str] | None = None
    priority_level: list[int] | None = strawberry.field(
        name="priorityLevel", default=None
    )
    category: list[str] | None = None


@strawberry.type
class UserSettings:
    focus_duration_pref: int | None = strawberry.field(
        name="focusDurationPref", default=None
    )
    break_duration_pref: int | None = strawberry.field(
        name="breakDurationPref", default=None
    )
    notifications_enabled: bool | None = strawberry.field(
        name="notificationsEnabled", default=None
    )


@strawberry.type
class User:
    id: strawberry.ID
    email: str
    name: str | None = None
    picture: str | None = None
    role: str | None = None
    auth_provider: str | None = strawberry.field(name="authProvider", default=None)
    subscription_status: str = strawberry.field(name="subscriptionStatus")
    settings: UserSettings | None = None
    bio: str | None = None


@strawberry.type
class AuthResponse:
    access_token: str
    user: User
    google_access_token: str | None = None


# ==============================================================================
# Tipos Principales con Resolvers
# ==============================================================================

@strawberry.type
class Workspace:
    id: strawberry.ID
    userId: str
    taskId: str | None = None
    title: str
    emoji: str | None = None
    background_color: str | None = strawberry.field(
        name="background_color", default=None
    )
    card_show_background: bool | None = strawberry.field(
        name="card_show_background", default=None
    )
    projectId: str | None = None
    content: str
    saveStatus: bool | None = None
    createdAt: datetime
    updatedAt: datetime

    @strawberry.field
    async def task(self, info: strawberry.types.Info) -> Optional["Task"]:
        if not self.taskId:
            return None
        db = info.context["db"]
        from app.modules.task.services.tasks_service import TasksService

        tasks_serv = TasksService(db)
        try:
            async with info.context["db_lock"]:
                res = await tasks_serv.find_one(self.taskId)
            return map_dict_to_strawberry_task(res) if res else None
        except Exception:
            return None


@strawberry.type
class ProjectGroup:
    id: strawberry.ID
    name: str
    user_id: str = strawberry.field(name="userId")
    color: str | None = None
    emoji: str | None = None
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: datetime = strawberry.field(name="updatedAt")

    @strawberry.field(name="workspaceCount")
    async def workspace_count(self, info: strawberry.types.Info) -> int:
        db = info.context["db"]
        async with info.context["db_lock"]:
            result = await db.execute(
                select(func.count(WorkspaceModel.id))
                .where(WorkspaceModel.userId == self.user_id)
                .where(WorkspaceModel.groupId == self.id)
            )
        return result.scalar() or 0

    @strawberry.field
    async def workspaces(self, info: strawberry.types.Info) -> list[Workspace]:
        db = info.context["db"]
        ws_serv = WorkspacesService(db)
        async with info.context["db_lock"]:
            all_ws_res = await ws_serv.find_all(self.user_id, group_id=self.id)

        all_ws = (
            all_ws_res.get("items", []) if isinstance(all_ws_res, dict) else all_ws_res
        )
        return [map_model_to_strawberry_workspace(w) for w in all_ws]


@strawberry.type
class Task:
    id: strawberry.ID
    user_id: str = strawberry.field(name="user_id")
    title: str
    workspace_id: str | None = strawberry.field(name="workspace_id", default=None)
    project_id: str | None = strawberry.field(name="project_id", default=None)
    notes_encrypted: str = strawberry.field(name="notes_encrypted")
    estimate_timer: int | None = strawberry.field(name="estimate_timer", default=None)
    real_timer: float | None = strawberry.field(name="real_timer", default=None)
    priority_level: int = strawberry.field(name="priority_level")
    category: str | None = None
    color: str | None = None
    deadline: datetime
    status: str
    completed_at: datetime | None = strawberry.field(name="completed_at", default=None)
    duration: datetime | None = None
    created_at: datetime = strawberry.field(name="created_at")
    updated_at: datetime = strawberry.field(name="updated_at")
    deleted_at: datetime | None = strawberry.field(name="deleted_at", default=None)
    tags: list[Tag]
    filters: TaskFilters | None = None
    links: list[TaskLink]
    task_type: str | None = strawberry.field(name="task_type", default="PlatformTask")
    google_event_id: str | None = strawberry.field(name="google_event_id", default=None)
    estimated_start_date: datetime | None = strawberry.field(
        name="estimated_start_date", default=None
    )
    estimated_end_date: datetime | None = strawberry.field(
        name="estimated_end_date", default=None
    )
    collaborators: list[Collaborator] | None = strawberry.field(default_factory=list)
    time_logs: list[TimeLog] = strawberry.field(
        name="time_logs", default_factory=list
    )
    subtasks: list[Subtask] = strawberry.field(
        name="subtasks", default_factory=list
    )
    use_ai: bool | None = strawberry.field(name="use_ai", default=False)
    is_owner: bool | None = strawberry.field(name="is_owner", default=True)
    source: str | None = strawberry.field(name="source", default="platform")

    @strawberry.field
    async def workspace(self, info: strawberry.types.Info) -> Workspace | None:
        ws_loader = info.context.get("task_workspace_loader")
        res = None
        if ws_loader:
            res = await ws_loader.load((self.id, self.workspace_id))
        else:
            db = info.context.get("db")
            db_lock = info.context.get("db_lock")
            if db and db_lock:
                ws_serv = WorkspacesService(db)
                async with db_lock:
                    res = await ws_serv.find_by_task_id(self.id)
                    if not res and self.workspace_id:
                        # Pasa user_id si tu firma lo exige para evitar missing-argument
                        res = await ws_serv.find_one(self.workspace_id, self.user_id)

        return map_model_to_strawberry_workspace(res) if res else None

    @strawberry.field
    async def project(self, info: strawberry.types.Info) -> Optional[ProjectGroup]:
        if not self.project_id:
            return None
        proj_loader = info.context.get("project_by_id_loader")
        res = None
        if proj_loader:
            res = await proj_loader.load(self.project_id)
        else:
            db = info.context.get("db")
            db_lock = info.context.get("db_lock")
            if db and db_lock:
                from app.modules.workspace.services.project_groups_service import (
                    ProjectGroupsService,
                )

                pg_serv = ProjectGroupsService(db)
                async with db_lock:
                    try:
                        res = await pg_serv.find_one(self.project_id, self.user_id)
                    except Exception:
                        res = None

        return map_model_to_strawberry_project_group(res) if res else None


# ==============================================================================
# Paginación
# ==============================================================================

@strawberry.type
class PaginatedTasks:
    tasks: list[Task]
    totalCount: int


@strawberry.type
class PaginatedWorkspaces:
    workspaces: list[Workspace]
    totalCount: int
    hasMore: bool | None = None


@strawberry.type
class PaginatedProjectGroups:
    projectGroups: list[ProjectGroup]
    totalCount: int
    hasMore: bool | None = None


# ==============================================================================
# Insights Types
# ==============================================================================

@strawberry.type
class StatCardValue:
    value: str
    change: str
    trend: str


@strawberry.type
class ProductivityTrend:
    label: str
    actual: float
    planned: float


@strawberry.type
class TimeDistribution:
    name: str
    value: float
    color: str


@strawberry.type
class HeatmapCompletedTask:
    id: str
    title: str
    completed_at: str | None = strawberry.field(name="completedAt", default=None)
    category: str | None = None
    real_timer: int | None = strawberry.field(name="realTimer", default=None)


@strawberry.type
class HeatmapCell:
    key: str
    label: str
    intensity: int
    count: int
    tasks: list[HeatmapCompletedTask]


@strawberry.type
class InsightsResponse:
    total_focus_hours: StatCardValue = strawberry.field(name="totalFocusHours")
    task_completion: StatCardValue = strawberry.field(name="taskCompletion")
    energy_score: StatCardValue = strawberry.field(name="energyScore")
    golden_window: StatCardValue = strawberry.field(name="goldenWindow")
    break_hours: StatCardValue = strawberry.field(name="breakHours")
    productivity_trends: list[ProductivityTrend] = strawberry.field(
        name="productivityTrends"
    )
    time_distribution: list[TimeDistribution] = strawberry.field(
        name="timeDistribution"
    )
    heatmap: list[int]
    heatmap_labels: list[str] | None = strawberry.field(
        name="heatmapLabels", default=None
    )
    heatmap_cells: list[HeatmapCell] = strawberry.field(
        name="heatmapCells", default_factory=list
    )


# ==============================================================================
# Inputs
# ==============================================================================

@strawberry.input
class SubtaskInput:
    id: str
    title: str
    completed: bool = False
    completed_at: str | None = strawberry.field(name="completed_at", default=None)
    estimate_timer: int | None = strawberry.field(name="estimate_timer", default=None)


@strawberry.input
class CollaboratorInput:
    name: str | None = None
    email: str
    avatar: str | None = None
    responseStatus: str | None = None


@strawberry.input
class LinkInput:
    title: str
    url: str


@strawberry.input
class TimeLogInput:
    date: str
    minutes: int


@strawberry.input
class CreateTaskInput:
    user_id: str = strawberry.field(name="user_id")
    title: str
    workspace_id: str | None = strawberry.field(name="workspace_id", default=None)
    project_id: str | None = strawberry.field(name="project_id", default=None)
    notes_encrypted: str = strawberry.field(name="notes_encrypted")
    estimate_timer: int | None = strawberry.field(name="estimate_timer", default=None)
    real_timer: float | None = strawberry.field(name="real_timer", default=None)
    duration: str | None = strawberry.field(name="duration", default=None)
    priority_level: int = strawberry.field(name="priority_level")
    deadline: str
    category: str | None = strawberry.field(name="category", default=None)
    color: str | None = strawberry.field(name="color", default=None)
    status: str | None = strawberry.field(name="status", default=None)
    tags: list[str] = strawberry.field(name="tags")
    links: list[LinkInput] | None = strawberry.field(name="links", default=None)
    task_type: str | None = strawberry.field(name="task_type", default=None)
    google_event_id: str | None = strawberry.field(name="google_event_id", default=None)
    estimated_start_date: str | None = strawberry.field(
        name="estimated_start_date", default=None
    )
    estimated_end_date: str | None = strawberry.field(
        name="estimated_end_date", default=None
    )
    source: str | None = strawberry.field(name="source", default=None)
    sync_status: str | None = strawberry.field(name="sync_status", default=None)
    collaborators: list[CollaboratorInput] | None = strawberry.field(
        name="collaborators", default=None
    )
    time_logs: list[TimeLogInput] | None = strawberry.field(
        name="time_logs", default=None
    )
    subtasks: list[SubtaskInput] | None = strawberry.field(
        name="subtasks", default=None
    )
    use_ai: bool | None = strawberry.field(name="use_ai", default=None)
    is_owner: bool | None = strawberry.field(name="is_owner", default=True)
    skip_scheduling: bool | None = strawberry.field(
        name="skip_scheduling", default=False
    )


@strawberry.input
class UpdateTaskInput:
    id: strawberry.ID
    user_id: str | None = strawberry.field(name="user_id", default=None)
    title: str | None = strawberry.field(name="title", default=None)
    workspace_id: str | None = strawberry.field(name="workspace_id", default=None)
    project_id: str | None = strawberry.field(name="project_id", default=None)
    notes_encrypted: str | None = strawberry.field(name="notes_encrypted", default=None)
    estimate_timer: int | None = strawberry.field(name="estimate_timer", default=None)
    real_timer: float | None = strawberry.field(name="real_timer", default=None)
    duration: str | None = strawberry.field(name="duration", default=None)
    priority_level: int | None = strawberry.field(name="priority_level", default=None)
    deadline: str | None = strawberry.field(name="deadline", default=None)
    category: str | None = strawberry.field(name="category", default=None)
    color: str | None = strawberry.field(name="color", default=None)
    status: str | None = strawberry.field(name="status", default=None)
    tags: list[str] | None = strawberry.field(name="tags", default=None)
    links: list[LinkInput] | None = strawberry.field(name="links", default=None)
    task_type: str | None = strawberry.field(name="task_type", default=None)
    google_event_id: str | None = strawberry.field(name="google_event_id", default=None)
    estimated_start_date: str | None = strawberry.field(
        name="estimated_start_date", default=None
    )
    estimated_end_date: str | None = strawberry.field(
        name="estimated_end_date", default=None
    )
    source: str | None = strawberry.field(name="source", default=None)
    sync_status: str | None = strawberry.field(name="sync_status", default=None)
    collaborators: list[CollaboratorInput] | None = strawberry.field(
        name="collaborators", default=None
    )
    time_logs: list[TimeLogInput] | None = strawberry.field(
        name="time_logs", default=None
    )
    subtasks: list[SubtaskInput] | None = strawberry.field(
        name="subtasks", default=None
    )
    use_ai: bool | None = strawberry.field(name="use_ai", default=None)
    is_owner: bool | None = strawberry.field(name="is_owner", default=None)


@strawberry.input
class TaskFilterInput:
    status: list[str] | None = None
    workspace_id: str | None = strawberry.field(name="workspace_id", default=None)
    workspaceId: str | None = strawberry.field(name="workspaceId", default=None)
    project_id: str | None = strawberry.field(name="project_id", default=None)
    projectId: str | None = strawberry.field(name="projectId", default=None)
    priorityLevel: list[int] | None = None
    category: list[str] | None = None
    startDate: str | None = None
    endDate: str | None = None
    searchTerm: str | None = None
    tags: list[str] | None = None


@strawberry.input
class TaskSortInput:
    sort: str | None = None
    order: str | None = None


@strawberry.input
class CreateWorkspaceInput:
    title: str
    content: str
    emoji: str | None = None
    background_color: str | None = strawberry.field(
        name="background_color", default=None
    )
    card_show_background: bool | None = strawberry.field(
        name="card_show_background", default=None
    )
    groupId: str | None = None
    taskId: str | None = None
    saveStatus: bool | None = None


@strawberry.input
class UpdateWorkspaceInput:
    id: strawberry.ID
    title: str | None = None
    content: str | None = None
    emoji: str | None = None
    background_color: str | None = strawberry.field(
        name="background_color", default=None
    )
    card_show_background: bool | None = strawberry.field(
        name="card_show_background", default=None
    )
    groupId: str | None = None
    taskId: str | None = None
    saveStatus: bool | None = None


@strawberry.input
class CreateProjectGroupInput:
    name: str
    color: str | None = None
    emoji: str | None = None


@strawberry.input
class UpdateProjectGroupInput:
    id: strawberry.ID
    name: str | None = None
    color: str | None = None
    emoji: str | None = None


# ==============================================================================
# Helper de Mapeo Task & Notificaciones
# ==============================================================================

def map_dict_to_strawberry_task(t: dict[str, Any]) -> Task:
    tags = []
    if isinstance(t.get("tags"), list):
        for tg in t["tags"]:
            tags.append(Tag(name=tg.get("name", "") if isinstance(tg, dict) else str(tg)))

    links = []
    if isinstance(t.get("links"), list):
        for l in t["links"]:
            if isinstance(l, dict):
                links.append(TaskLink(title=l.get("title", ""), url=l.get("url", "")))

    collaborators = []
    if isinstance(t.get("collaborators"), list):
        for c in t["collaborators"]:
            if isinstance(c, dict):
                collaborators.append(
                    Collaborator(
                        name=c.get("name"),
                        email=c.get("email", ""),
                        avatar=c.get("avatar"),
                        response_status=c.get("responseStatus"),
                    )
                )

    time_logs = []
    if isinstance(t.get("time_logs"), list):
        for tl in t["time_logs"]:
            if isinstance(tl, dict):
                time_logs.append(
                    TimeLog(date=tl.get("date", ""), minutes=tl.get("minutes", 0))
                )

    filters = None
    f = t.get("filters")
    if isinstance(f, dict):
        filters = TaskFilters(
            status=f.get("status"),
            priority_level=f.get("priorityLevel"),
            category=f.get("category"),
        )

    subtasks = []
    if isinstance(t.get("subtasks"), list):
        for st in t["subtasks"]:
            if isinstance(st, dict):
                subtasks.append(
                    Subtask(
                        id=str(st.get("id", "")),
                        title=st.get("title", ""),
                        completed=bool(st.get("completed", False)),
                        completed_at=st.get("completed_at"),
                        estimate_timer=st.get("estimate_timer"),
                    )
                )

    return Task(
        id=strawberry.ID(str(t["id"])),
        user_id=str(t["userId"]),
        title=t["title"],
        notes_encrypted=t["notesEncrypted"],
        estimate_timer=t.get("estimateTimer"),
        real_timer=t.get("realTimer"),
        priority_level=t["priorityLevel"],
        category=t.get("category"),
        color=t.get("color"),
        deadline=parse_iso_datetime(t.get("deadline")) or datetime.now(timezone.utc),
        status=t["status"],
        completed_at=parse_iso_datetime(t.get("completedAt")),
        duration=parse_iso_datetime(t.get("duration")),
        created_at=parse_iso_datetime(t.get("createdAt")) or datetime.now(timezone.utc),
        updated_at=parse_iso_datetime(t.get("updatedAt")) or datetime.now(timezone.utc),
        deleted_at=parse_iso_datetime(t.get("deletedAt")),
        tags=tags,
        filters=filters,
        links=links,
        workspace_id=t.get("workspaceId") or t.get("workspace_id"),
        project_id=t.get("projectId") or t.get("project_id"),
        task_type=t.get("task_type"),
        google_event_id=t.get("google_event_id"),
        estimated_start_date=parse_iso_datetime(t.get("estimated_start_date")),
        estimated_end_date=parse_iso_datetime(t.get("estimated_end_date")),
        collaborators=collaborators,
        time_logs=time_logs,
        subtasks=subtasks,
        use_ai=t.get("use_ai"),
        is_owner=t.get("is_owner", True),
        source=t.get("source", "platform"),
    )


@strawberry.type
class NotificationType:
    id: strawberry.ID
    userId: str = strawberry.field(name="userId")
    relatedTaskId: str | None = strawberry.field(name="relatedTaskId", default=None)
    type: str
    scheduledAt: datetime = strawberry.field(name="scheduledAt")
    status: str
    title: str
    body: str
    createdAt: datetime = strawberry.field(name="createdAt")
    updatedAt: datetime = strawberry.field(name="updatedAt")


def map_model_to_strawberry_notification(n: Any) -> NotificationType:
    return NotificationType(
        id=strawberry.ID(str(n.id)),
        userId=n.userId,
        relatedTaskId=n.relatedTaskId,
        type=n.type,
        scheduledAt=n.scheduledAt,
        status=n.status,
        title=n.title,
        body=n.body,
        createdAt=n.createdAt,
        updatedAt=n.updatedAt,
    )