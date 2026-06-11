import strawberry
from app.graphql.tasks import TaskQuery, TaskMutation
from app.graphql.projects import ProjectQuery, ProjectMutation
from app.graphql.workspaces import WorkspaceQuery, WorkspaceMutation
from app.graphql.auth import AuthMutation
from app.graphql.tags import TagQuery
from app.graphql.insights import InsightsQuery
from app.graphql.project_groups import ProjectGroupQuery, ProjectGroupMutation


@strawberry.type
class Query(TaskQuery, ProjectQuery, WorkspaceQuery, TagQuery, InsightsQuery, ProjectGroupQuery):
    """Combined Query class with all entity queries"""
    pass


@strawberry.type
class Mutation(TaskMutation, ProjectMutation, WorkspaceMutation, AuthMutation, ProjectGroupMutation):
    """Combined Mutation class with all entity mutations"""
    pass


schema = strawberry.Schema(query=Query, mutation=Mutation)
