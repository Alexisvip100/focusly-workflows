import strawberry
from datetime import datetime
from typing import List, Optional, Dict, Any

# Types

@strawberry.type
class Tag:
    name: str

@strawberry.type
class Collaborator:
    name: Optional[str] = None
    email: str
    avatar: Optional[str] = None
    response_status: Optional[str] = strawberry.field(name="responseStatus", default=None)

@strawberry.type
class TaskLink:
    title: str
    url: str

@strawberry.type
class TaskFilters:
    status: Optional[List[str]] = None
    priority_level: Optional[List[int]] = strawberry.field(name="priorityLevel", default=None)
    category: Optional[List[str]] = None

@strawberry.type
class UserSettings:
    focus_duration_pref: Optional[int] = strawberry.field(name="focusDurationPref", default=None)
    break_duration_pref: Optional[int] = strawberry.field(name="breakDurationPref", default=None)
    notifications_enabled: Optional[bool] = strawberry.field(name="notificationsEnabled", default=None)

@strawberry.type
class User:
    id: strawberry.ID
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None
    role: Optional[str] = None
    auth_provider: Optional[str] = strawberry.field(name="authProvider", default=None)
    google_refresh_token: Optional[str] = strawberry.field(name="googleRefreshToken", default=None)
    subscription_status: str = strawberry.field(name="subscriptionStatus")
    settings: Optional[UserSettings] = None
    bio: Optional[str] = None

@strawberry.type
class AuthResponse:
    access_token: str
    user: User
    google_access_token: Optional[str] = None

@strawberry.type
class Workspace:
    id: strawberry.ID
    userId: str
    taskId: Optional[str] = None
    title: str
    emoji: Optional[str] = None
    background_color: Optional[str] = strawberry.field(name="background_color", default=None)
    card_show_background: Optional[bool] = strawberry.field(name="card_show_background", default=None)
    projectId: Optional[str] = None
    groupId: Optional[str] = None
    content: str
    saveStatus: Optional[bool] = None
    createdAt: datetime
    updatedAt: datetime

    # Resolved fields will be in the resolver/queries
    @strawberry.field
    async def task(self, info) -> Optional["Task"]:
        if not self.taskId:
            return None
        db = info.context["db"]
        from app.services.tasks.tasks_service import TasksService
        tasks_serv = TasksService(db)
        try:
            res = await tasks_serv.find_one(self.taskId)
            return map_dict_to_strawberry_task(res)
        except:
            return None

    @strawberry.field
    async def project(self, info) -> Optional["Project"]:
        if not self.projectId:
            return None
        db = info.context["db"]
        from app.services.folders.folders_service import FoldersService
        folders_serv = FoldersService(db)
        try:
            res = await folders_serv.find_one(self.projectId, self.userId)
            if res:
                return Project(
                    id=strawberry.ID(res.id),
                    name=res.name,
                    user_id=res.userId,
                    color=res.color,
                    created_at=res.createdAt,
                    updated_at=res.updatedAt
                )
        except:
            return None

@strawberry.type
class Project:
    id: strawberry.ID
    name: str
    user_id: str = strawberry.field(name="userId")
    color: Optional[str] = None
    group_id: Optional[str] = strawberry.field(name="groupId", default=None)
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: datetime = strawberry.field(name="updatedAt")

    @strawberry.field
    async def workspaces(self, info) -> List[Workspace]:
        db = info.context["db"]
        from app.services.workspaces.workspaces_service import WorkspacesService
        ws_serv = WorkspacesService(db)
        res = await ws_serv.find_all(self.user_id, folder_id=str(self.id))
        return [
            Workspace(
                id=strawberry.ID(w.id),
                userId=w.userId,
                taskId=w.taskId,
                title=w.title,
                emoji=w.emoji,
                background_color=w.background_color,
                card_show_background=w.card_show_background,
                projectId=w.folderId,
                content=w.content,
                saveStatus=w.saveStatus,
                createdAt=w.createdAt,
                updatedAt=w.updatedAt
            ) for w in res
        ]

    @strawberry.field
    async def workspace_count(self, info) -> int:
        workspaces = await self.workspaces(info)
        return len(workspaces)

@strawberry.type
class ProjectGroup:
    id: strawberry.ID
    name: str
    user_id: str = strawberry.field(name="userId")
    color: Optional[str] = None
    emoji: Optional[str] = None
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: datetime = strawberry.field(name="updatedAt")

    @strawberry.field
    async def folders(self, info) -> List[Project]:
        db = info.context["db"]
        from app.services.folders.folders_service import FoldersService
        folders_serv = FoldersService(db)
        res = await folders_serv.find_all(self.user_id, group_id=str(self.id))
        return [
            Project(
                id=strawberry.ID(f.id),
                name=f.name,
                user_id=f.userId,
                color=f.color,
                group_id=f.groupId,
                created_at=f.createdAt,
                updated_at=f.updatedAt
            ) for f in res
        ]

    @strawberry.field
    async def general_workspaces(self, info) -> List[Workspace]:
        """Workspaces that belong to this group but not to any specific folder."""
        db = info.context["db"]
        from app.services.workspaces.workspaces_service import WorkspacesService
        ws_serv = WorkspacesService(db)
        all_ws = await ws_serv.find_all(self.user_id, group_id=str(self.id))
        return [
            Workspace(
                id=strawberry.ID(w.id),
                userId=w.userId,
                taskId=w.taskId,
                title=w.title,
                emoji=w.emoji,
                background_color=w.background_color,
                card_show_background=w.card_show_background,
                projectId=w.folderId,
                groupId=w.groupId,
                content=w.content,
                saveStatus=w.saveStatus,
                createdAt=w.createdAt,
                updatedAt=w.updatedAt
            ) for w in all_ws if not w.folderId
        ]

    @strawberry.field
    async def folder_count(self, info) -> int:
        folders = await self.folders(info)
        return len(folders)

@strawberry.type
class Task:
    id: strawberry.ID
    user_id: str = strawberry.field(name="user_id")
    title: str
    notes_encrypted: str = strawberry.field(name="notes_encrypted")
    estimate_timer: Optional[int] = strawberry.field(name="estimate_timer", default=None)
    real_timer: Optional[float] = strawberry.field(name="real_timer", default=None)
    priority_level: int = strawberry.field(name="priority_level")
    category: Optional[str] = None
    color: Optional[str] = None
    deadline: datetime
    status: str
    completed_at: Optional[datetime] = strawberry.field(name="completed_at", default=None)
    duration: Optional[datetime] = None
    created_at: datetime = strawberry.field(name="created_at")
    updated_at: datetime = strawberry.field(name="updated_at")
    deleted_at: Optional[datetime] = strawberry.field(name="deleted_at", default=None)
    tags: List[Tag]
    filters: Optional[TaskFilters] = None
    links: List[TaskLink]
    task_type: Optional[str] = strawberry.field(name="task_type", default="PlatformTask")
    google_event_id: Optional[str] = strawberry.field(name="google_event_id", default=None)
    estimated_start_date: Optional[datetime] = strawberry.field(name="estimated_start_date", default=None)
    estimated_end_date: Optional[datetime] = strawberry.field(name="estimated_end_date", default=None)
    collaborators: Optional[List[Collaborator]] = strawberry.field(default_factory=list)
    use_ai: Optional[bool] = strawberry.field(name="use_ai", default=False)
    is_owner: Optional[bool] = strawberry.field(name="is_owner", default=True)
    source: Optional[str] = strawberry.field(name="source", default="platform")

    @strawberry.field
    async def workspace(self, info) -> Optional[Workspace]:
        db = info.context["db"]
        from app.services.workspaces.workspaces_service import WorkspacesService
        ws_serv = WorkspacesService(db)
        res = await ws_serv.find_by_task_id(str(self.id))
        if res:
            return Workspace(
                id=strawberry.ID(res.id),
                userId=res.userId,
                taskId=res.taskId,
                title=res.title,
                emoji=res.emoji,
                background_color=res.background_color,
                card_show_background=res.card_show_background,
                projectId=res.folderId,
                content=res.content,
                saveStatus=res.saveStatus,
                createdAt=res.createdAt,
                updatedAt=res.updatedAt
            )
        return None

@strawberry.type
class PaginatedTasks:
    tasks: List[Task]
    totalCount: int

# Insights Types

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
class InsightsResponse:
    total_focus_hours: StatCardValue = strawberry.field(name="totalFocusHours")
    task_completion: StatCardValue = strawberry.field(name="taskCompletion")
    energy_score: StatCardValue = strawberry.field(name="energyScore")
    golden_window: StatCardValue = strawberry.field(name="goldenWindow")
    break_hours: StatCardValue = strawberry.field(name="breakHours")
    productivity_trends: List[ProductivityTrend] = strawberry.field(name="productivityTrends")
    time_distribution: List[TimeDistribution] = strawberry.field(name="timeDistribution")
    heatmap: List[int]
    heatmap_labels: Optional[List[str]] = strawberry.field(name="heatmapLabels", default=None)

# Inputs

@strawberry.input
class CollaboratorInput:
    name: Optional[str] = None
    email: str
    avatar: Optional[str] = None
    responseStatus: Optional[str] = None

@strawberry.input
class LinkInput:
    title: str
    url: str

@strawberry.input
class CreateTaskInput:
    user_id: str = strawberry.field(name="user_id")
    title: str
    notes_encrypted: str = strawberry.field(name="notes_encrypted")
    estimate_timer: Optional[int] = strawberry.field(name="estimate_timer", default=None)
    real_timer: Optional[float] = strawberry.field(name="real_timer", default=None)
    duration: Optional[str] = strawberry.field(name="duration", default=None)
    priority_level: int = strawberry.field(name="priority_level")
    deadline: str
    category: Optional[str] = strawberry.field(name="category", default=None)
    color: Optional[str] = strawberry.field(name="color", default=None)
    status: Optional[str] = strawberry.field(name="status", default=None)
    tags: List[str] = strawberry.field(name="tags")
    links: Optional[List[LinkInput]] = strawberry.field(name="links", default=None)
    task_type: Optional[str] = strawberry.field(name="task_type", default=None)
    google_event_id: Optional[str] = strawberry.field(name="google_event_id", default=None)
    estimated_start_date: Optional[str] = strawberry.field(name="estimated_start_date", default=None)
    estimated_end_date: Optional[str] = strawberry.field(name="estimated_end_date", default=None)
    source: Optional[str] = strawberry.field(name="source", default=None)
    sync_status: Optional[str] = strawberry.field(name="sync_status", default=None)
    collaborators: Optional[List[CollaboratorInput]] = strawberry.field(name="collaborators", default=None)
    use_ai: Optional[bool] = strawberry.field(name="use_ai", default=None)
    is_owner: Optional[bool] = strawberry.field(name="is_owner", default=True)

@strawberry.input
class UpdateTaskInput:
    id: strawberry.ID
    user_id: Optional[str] = strawberry.field(name="user_id", default=None)
    title: Optional[str] = strawberry.field(name="title", default=None)
    notes_encrypted: Optional[str] = strawberry.field(name="notes_encrypted", default=None)
    estimate_timer: Optional[int] = strawberry.field(name="estimate_timer", default=None)
    real_timer: Optional[float] = strawberry.field(name="real_timer", default=None)
    duration: Optional[str] = strawberry.field(name="duration", default=None)
    priority_level: Optional[int] = strawberry.field(name="priority_level", default=None)
    deadline: Optional[str] = strawberry.field(name="deadline", default=None)
    category: Optional[str] = strawberry.field(name="category", default=None)
    color: Optional[str] = strawberry.field(name="color", default=None)
    status: Optional[str] = strawberry.field(name="status", default=None)
    tags: Optional[List[str]] = strawberry.field(name="tags", default=None)
    links: Optional[List[LinkInput]] = strawberry.field(name="links", default=None)
    task_type: Optional[str] = strawberry.field(name="task_type", default=None)
    google_event_id: Optional[str] = strawberry.field(name="google_event_id", default=None)
    estimated_start_date: Optional[str] = strawberry.field(name="estimated_start_date", default=None)
    estimated_end_date: Optional[str] = strawberry.field(name="estimated_end_date", default=None)
    source: Optional[str] = strawberry.field(name="source", default=None)
    sync_status: Optional[str] = strawberry.field(name="sync_status", default=None)
    collaborators: Optional[List[CollaboratorInput]] = strawberry.field(name="collaborators", default=None)
    use_ai: Optional[bool] = strawberry.field(name="use_ai", default=None)
    is_owner: Optional[bool] = strawberry.field(name="is_owner", default=None)

@strawberry.input
class TaskFilterInput:
    status: Optional[List[str]] = None
    priorityLevel: Optional[List[int]] = None
    category: Optional[List[str]] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    searchTerm: Optional[str] = None

@strawberry.input
class TaskSortInput:
    sort: Optional[str] = None
    order: Optional[str] = None

@strawberry.input
class CreateWorkspaceInput:
    title: str
    content: str
    emoji: Optional[str] = None
    background_color: Optional[str] = strawberry.field(name="background_color", default=None)
    card_show_background: Optional[bool] = strawberry.field(name="card_show_background", default=None)
    projectId: Optional[str] = None
    groupId: Optional[str] = None
    taskId: Optional[str] = None
    saveStatus: Optional[bool] = None

@strawberry.input
class UpdateWorkspaceInput:
    id: strawberry.ID
    title: Optional[str] = None
    content: Optional[str] = None
    emoji: Optional[str] = None
    background_color: Optional[str] = strawberry.field(name="background_color", default=None)
    card_show_background: Optional[bool] = strawberry.field(name="card_show_background", default=None)
    projectId: Optional[str] = None
    groupId: Optional[str] = None
    taskId: Optional[str] = None
    saveStatus: Optional[bool] = None

@strawberry.input
class CreateProjectInput:
    name: str
    color: Optional[str] = None
    groupId: Optional[str] = None

@strawberry.input
class UpdateProjectInput:
    id: strawberry.ID
    name: Optional[str] = None
    color: Optional[str] = None
    groupId: Optional[str] = None

@strawberry.input
class CreateProjectGroupInput:
    name: str
    color: Optional[str] = None
    emoji: Optional[str] = None

@strawberry.input
class UpdateProjectGroupInput:
    id: strawberry.ID
    name: Optional[str] = None
    color: Optional[str] = None
    emoji: Optional[str] = None

# Helper functions to convert DB/dict data to strawberry types

def map_dict_to_strawberry_task(t: Dict[str, Any]) -> Task:
    from datetime import timezone as _tz

    def parse_iso(dt_str: Optional[str]) -> Optional[datetime]:
        if not dt_str:
            return None
        # Parse the string; if it has no timezone info (naive), treat it as UTC.
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_tz.utc)
        return dt

    # Tags list
    tags = []
    if isinstance(t.get("tags"), list):
        for tg in t["tags"]:
            if isinstance(tg, dict):
                tags.append(Tag(name=tg.get("name", "")))
            elif isinstance(tg, str):
                tags.append(Tag(name=tg))

    # Links list
    links = []
    if isinstance(t.get("links"), list):
        for l in t["links"]:
            if isinstance(l, dict):
                links.append(TaskLink(title=l.get("title", ""), url=l.get("url", "")))

    # Collaborators list
    collaborators = []
    if isinstance(t.get("collaborators"), list):
        for c in t["collaborators"]:
            if isinstance(c, dict):
                collaborators.append(Collaborator(
                    name=c.get("name"),
                    email=c.get("email", ""),
                    avatar=c.get("avatar"),
                    response_status=c.get("responseStatus")
                ))

    # Filters
    filters = None
    f = t.get("filters")
    if isinstance(f, dict):
        filters = TaskFilters(
            status=f.get("status"),
            priority_level=f.get("priorityLevel"),
            category=f.get("category")
        )

    return Task(
        id=strawberry.ID(t["id"]),
        user_id=t["userId"],
        title=t["title"],
        notes_encrypted=t["notesEncrypted"],
        estimate_timer=t.get("estimateTimer"),
        real_timer=t.get("realTimer"),
        priority_level=t["priorityLevel"],
        category=t.get("category"),
        color=t.get("color"),
        deadline=parse_iso(t["deadline"]),
        status=t["status"],
        completed_at=parse_iso(t.get("completedAt")),
        duration=parse_iso(t.get("duration")),
        created_at=parse_iso(t["createdAt"]),
        updated_at=parse_iso(t["updatedAt"]),
        deleted_at=parse_iso(t.get("deletedAt")),
        tags=tags,
        filters=filters,
        links=links,
        task_type=t.get("task_type"),
        google_event_id=t.get("google_event_id"),
        estimated_start_date=parse_iso(t.get("estimated_start_date")),
        estimated_end_date=parse_iso(t.get("estimated_end_date")),
        collaborators=collaborators,
        use_ai=t.get("use_ai"),
        is_owner=t.get("is_owner", True),
        source=t.get("source", "platform")
    )
