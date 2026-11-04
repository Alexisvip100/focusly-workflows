import strawberry
from graphql.validation import NoSchemaIntrospectionCustomRule
from strawberry.extensions import AddValidationRules

from app.config import settings
from app.graphql.extensions import TransactionalMutationExtension
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
from app.modules.canvas.presentation.graphql import CanvasQuery, CanvasMutation


@strawberry.type
class Query(
    TaskQuery,
    WorkspaceQuery,
    TagQuery,
    InsightsQuery,
    ProjectGroupQuery,
    NotificationQuery,
    CanvasQuery,
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
    CanvasMutation,
):
    """Combined Mutation class with all entity mutations"""

    pass


# In production the schema isn't handed to whoever asks (introspection is
# a map of the whole API); the app never needs it. __typename still works.
_production_rules = (
    [AddValidationRules([NoSchemaIntrospectionCustomRule])]
    if settings.IS_PRODUCTION
    else []
)

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[TransactionalMutationExtension, *_production_rules],
)
