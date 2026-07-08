import strawberry
from app.modules.task.graphql.tasks_queries import TaskQuery
from app.modules.task.graphql.tasks_mutations import TaskMutation
from app.modules.workspace.graphql.workspaces_queries import WorkspaceQuery
from app.modules.workspace.graphql.workspaces_mutations import WorkspaceMutation
from app.modules.auth.graphql.mutations import AuthMutation
from app.modules.task.graphql.tags_queries import TagQuery
from app.modules.insights.graphql.queries import InsightsQuery
from app.modules.workspace.graphql.project_groups_queries import ProjectGroupQuery
from app.modules.workspace.graphql.project_groups_mutations import ProjectGroupMutation
from app.modules.notification.graphql.notifications_queries import NotificationQuery
from app.modules.notification.graphql.notifications_mutations import NotificationMutation


@strawberry.type
class Query(TaskQuery, WorkspaceQuery, TagQuery, InsightsQuery, ProjectGroupQuery, NotificationQuery):
    """Combined Query class with all entity queries"""
    pass


@strawberry.type
class Mutation(TaskMutation, WorkspaceMutation, AuthMutation, ProjectGroupMutation, NotificationMutation):
    """Combined Mutation class with all entity mutations"""
    pass


schema = strawberry.Schema(query=Query, mutation=Mutation)
