from datetime import UTC, datetime
from typing import Any, Optional

import strawberry

# Types


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
    google_refresh_token: str | None = strawberry.field(
        name="googleRefreshToken", default=None
    )
    subscription_status: str = strawberry.field(name="subscriptionStatus")
    settings: UserSettings | None = None
    bio: str | None = None


@strawberry.type
class AuthResponse:
    access_token: str
    user: User
    google_access_token: str | None = None


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
    groupId: str | None = None
    content: str
    saveStatus: bool | None = None
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
                    updated_at=res.updatedAt,
                )
        except:
            return None


@strawberry.type
class Project:
    id: strawberry.ID
    name: str
    user_id: str = strawberry.field(name="userId")
    color: str | None = None
    group_id: str | None = strawberry.field(name="groupId", default=None)
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: datetime = strawberry.field(name="updatedAt")

    @strawberry.field
    async def workspaces(self, info) -> list[Workspace]:
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
                updatedAt=w.updatedAt,
            )
            for w in res
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
    color: str | None = None
    emoji: str | None = None
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: datetime = strawberry.field(name="updatedAt")

    @strawberry.field
    async def folders(self, info) -> list[Project]:
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
                updated_at=f.updatedAt,
            )
            for f in res
        ]

    @strawberry.field
    async def general_workspaces(self, info) -> list[Workspace]:
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
                updatedAt=w.updatedAt,
            )
            for w in all_ws
            if not w.folderId
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
    use_ai: bool | None = strawberry.field(name="use_ai", default=False)
    is_owner: bool | None = strawberry.field(name="is_owner", default=True)
    source: str | None = strawberry.field(name="source", default="platform")

    @strawberry.field
    async def workspace(self, info) -> Workspace | None:
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
                updatedAt=res.updatedAt,
            )
        return None


@strawberry.type
class PaginatedTasks:
    tasks: list[Task]
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


# Inputs


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
class CreateTaskInput:
    user_id: str = strawberry.field(name="user_id")
    title: str
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
    use_ai: bool | None = strawberry.field(name="use_ai", default=None)
    is_owner: bool | None = strawberry.field(name="is_owner", default=True)


@strawberry.input
class UpdateTaskInput:
    id: strawberry.ID
    user_id: str | None = strawberry.field(name="user_id", default=None)
    title: str | None = strawberry.field(name="title", default=None)
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
    use_ai: bool | None = strawberry.field(name="use_ai", default=None)
    is_owner: bool | None = strawberry.field(name="is_owner", default=None)


@strawberry.input
class TaskFilterInput:
    status: list[str] | None = None
    priorityLevel: list[int] | None = None
    category: list[str] | None = None
    startDate: str | None = None
    endDate: str | None = None
    searchTerm: str | None = None


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
    projectId: str | None = None
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
    projectId: str | None = None
    groupId: str | None = None
    taskId: str | None = None
    saveStatus: bool | None = None


@strawberry.input
class CreateProjectInput:
    name: str
    color: str | None = None
    groupId: str | None = None


@strawberry.input
class UpdateProjectInput:
    id: strawberry.ID
    name: str | None = None
    color: str | None = None
    groupId: str | None = None


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


# Helper functions to convert DB/dict data to strawberry types


def map_dict_to_strawberry_task(t: dict[str, Any]) -> Task:
    def parse_iso(dt_str: str | None) -> datetime | None:
        if not dt_str:
            return None
        # Parse the string; if it has no timezone info (naive), treat it as UTC.
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
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
                collaborators.append(
                    Collaborator(
                        name=c.get("name"),
                        email=c.get("email", ""),
                        avatar=c.get("avatar"),
                        response_status=c.get("responseStatus"),
                    )
                )

    # Filters
    filters = None
    f = t.get("filters")
    if isinstance(f, dict):
        filters = TaskFilters(
            status=f.get("status"),
            priority_level=f.get("priorityLevel"),
            category=f.get("category"),
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
        source=t.get("source", "platform"),
    )
