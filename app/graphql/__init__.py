import strawberry

from app.graphql.auth import AuthMutation
from app.graphql.insights import InsightsQuery
from app.graphql.project_groups import ProjectGroupMutation, ProjectGroupQuery
from app.graphql.projects import ProjectMutation, ProjectQuery
from app.graphql.tags import TagQuery
from app.graphql.tasks import TaskMutation, TaskQuery
from app.graphql.workspaces import WorkspaceMutation, WorkspaceQuery


@strawberry.type
class Query(
    TaskQuery, ProjectQuery, WorkspaceQuery, TagQuery, InsightsQuery, ProjectGroupQuery
):
    """Combined Query class with all entity queries"""

    pass


@strawberry.type
class Mutation(
    TaskMutation, ProjectMutation, WorkspaceMutation, AuthMutation, ProjectGroupMutation
):
    """Combined Mutation class with all entity mutations"""

    pass


schema = strawberry.Schema(query=Query, mutation=Mutation)
