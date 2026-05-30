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
    user_id: str = strawberry.field(name="userId")
    task_id: Optional[str] = strawberry.field(name="taskId", default=None)
    title: str
    emoji: Optional[str] = None
    background_color: Optional[str] = strawberry.field(name="background_color", default=None)
    card_show_background: Optional[bool] = strawberry.field(name="card_show_background", default=None)
    folder_id: Optional[str] = strawberry.field(name="folderId", default=None)
    content: str
    save_status: Optional[bool] = strawberry.field(name="saveStatus", default=None)
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: datetime = strawberry.field(name="updatedAt")

    # Resolved fields will be in the resolver/queries
    @strawberry.field
    async def task(self, info) -> Optional["Task"]:
        if not self.task_id:
            return None
        db = info.context["db"]
        from app.services.tasks.tasks_service import TasksService
        tasks_serv = TasksService(db)
        try:
            res = await tasks_serv.find_one(self.task_id)
            return map_dict_to_strawberry_task(res)
        except:
            return None

    @strawberry.field
    async def folder(self, info) -> Optional["Folder"]:
        if not self.folder_id:
            return None
        db = info.context["db"]
        from app.services.folders.folders_service import FoldersService
        folders_serv = FoldersService(db)
        try:
            res = await folders_serv.find_one(self.folder_id, self.user_id)
            if res:
                return Folder(
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
class Folder:
    id: strawberry.ID
    name: str
    user_id: str = strawberry.field(name="userId")
    color: Optional[str] = None
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
                user_id=w.userId,
                task_id=w.taskId,
                title=w.title,
                emoji=w.emoji,
                background_color=w.background_color,
                card_show_background=w.card_show_background,
                folder_id=w.folderId,
                content=w.content,
                save_status=w.saveStatus,
                created_at=w.createdAt,
                updated_at=w.updatedAt
            ) for w in res
        ]

    @strawberry.field
    async def workspace_count(self, info) -> int:
        workspaces = await self.workspaces(info)
        return len(workspaces)

@strawberry.type
class Task:
    id: strawberry.ID
    user_id: str = strawberry.field(name="user_id")
    title: str
    notes_encrypted: str = strawberry.field(name="notes_encrypted")
    estimate_timer: Optional[int] = strawberry.field(name="estimate_timer", default=None)
    real_timer: Optional[int] = strawberry.field(name="real_timer", default=None)
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

    @strawberry.field
    async def workspace(self, info) -> Optional[Workspace]:
        db = info.context["db"]
        from app.services.workspaces.workspaces_service import WorkspacesService
        ws_serv = WorkspacesService(db)
        res = await ws_serv.find_by_task_id(str(self.id))
        if res:
            return Workspace(
                id=strawberry.ID(res.id),
                user_id=res.userId,
                task_id=res.taskId,
                title=res.title,
                emoji=res.emoji,
                background_color=res.background_color,
                card_show_background=res.card_show_background,
                folder_id=res.folderId,
                content=res.content,
                save_status=res.saveStatus,
                created_at=res.createdAt,
                updated_at=res.updatedAt
            )
        return None

@strawberry.type
class PaginatedTasks:
    tasks: List[Task]
    total_count: int = strawberry.field(name="totalCount")

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
    user_id: str
    title: str
    notes_encrypted: str
    estimate_timer: Optional[int] = None
    real_timer: Optional[int] = None
    duration: Optional[str] = None
    priority_level: int
    deadline: str
    category: Optional[str] = None
    color: Optional[str] = None
    status: Optional[str] = None
    tags: List[str]
    links: Optional[List[LinkInput]] = None
    task_type: Optional[str] = None
    google_event_id: Optional[str] = None
    estimated_start_date: Optional[str] = None
    estimated_end_date: Optional[str] = None
    source: Optional[str] = None
    sync_status: Optional[str] = None
    collaborators: Optional[List[CollaboratorInput]] = None
    use_ai: Optional[bool] = None

@strawberry.input
class UpdateTaskInput:
    id: strawberry.ID
    user_id: Optional[str] = None
    title: Optional[str] = None
    notes_encrypted: Optional[str] = None
    estimate_timer: Optional[int] = None
    real_timer: Optional[int] = None
    duration: Optional[str] = None
    priority_level: Optional[int] = None
    deadline: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None
    links: Optional[List[LinkInput]] = None
    task_type: Optional[str] = None
    google_event_id: Optional[str] = None
    estimated_start_date: Optional[str] = None
    estimated_end_date: Optional[str] = None
    source: Optional[str] = None
    sync_status: Optional[str] = None
    collaborators: Optional[List[CollaboratorInput]] = None
    use_ai: Optional[bool] = None

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
    emoji: Optional[str] = None
    background_color: Optional[str] = strawberry.field(name="background_color", default=None)
    card_show_background: Optional[bool] = strawberry.field(name="card_show_background", default=None)
    folderId: Optional[str] = strawberry.field(name="folderId", default=None)
    content: str
    taskId: Optional[str] = strawberry.field(name="taskId", default=None)
    saveStatus: Optional[bool] = strawberry.field(name="saveStatus", default=None)

@strawberry.input
class UpdateWorkspaceInput:
    id: strawberry.ID
    title: Optional[str] = None
    emoji: Optional[str] = None
    background_color: Optional[str] = strawberry.field(name="background_color", default=None)
    card_show_background: Optional[bool] = strawberry.field(name="card_show_background", default=None)
    folderId: Optional[str] = strawberry.field(name="folderId", default=None)
    content: Optional[str] = None
    taskId: Optional[str] = strawberry.field(name="taskId", default=None)
    saveStatus: Optional[bool] = strawberry.field(name="saveStatus", default=None)

@strawberry.input
class CreateFolderInput:
    name: str
    color: Optional[str] = None

@strawberry.input
class UpdateFolderInput:
    id: strawberry.ID
    name: Optional[str] = None
    color: Optional[str] = None

# Helper functions to convert DB/dict data to strawberry types

def map_dict_to_strawberry_task(t: Dict[str, Any]) -> Task:
    def parse_iso(dt_str: Optional[str]) -> Optional[datetime]:
        if not dt_str:
            return None
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))

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
        use_ai=t.get("use_ai")
    )
