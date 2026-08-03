import strawberry
from app.modules.task.presentation.graphql import TaskQuery, TaskMutation, TagQuery
from app.modules.workspace.presentation.graphql import (
    WorkspaceQuery,
    WorkspaceMutation,
    ProjectGroupQuery,
    ProjectGroupMutation,
)
from app.modules.auth.presentation.graphql import AuthMutation
from app.modules.insights.presentation.graphql import InsightsQuery
from app.modules.notification.presentation.graphql import (
    NotificationQuery,
    NotificationMutation,
)


@strawberry.type
class Query(
    TaskQuery,
    WorkspaceQuery,
    TagQuery,
    InsightsQuery,
    ProjectGroupQuery,
    NotificationQuery,
):
    """Combined Query class with all entity queries"""

    pass


@strawberry.type
class Mutation(
    TaskMutation,
    WorkspaceMutation,
    AuthMutation,
    ProjectGroupMutation,
    NotificationMutation,
):
    """Combined Mutation class with all entity mutations"""

    pass


schema = strawberry.Schema(query=Query, mutation=Mutation)
