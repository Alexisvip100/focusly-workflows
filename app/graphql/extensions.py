from typing import AsyncIterator
from strawberry.extensions import SchemaExtension
from graphql.language.ast import OperationType
from app.database import transaction_scope


class TransactionalMutationExtension(SchemaExtension):
    """Wraps GraphQL mutation operations in a transaction_scope.

    Queries remain read-only without transaction overhead. Mutations are
    automatically committed on success, or rolled back if GraphQL errors or
    exceptions occur.
    """

    async def on_execute(self) -> AsyncIterator[None]:
        operation_type = self.execution_context.operation_type
        is_mutation = (
            operation_type == OperationType.MUTATION
            or str(operation_type).lower().endswith("mutation")
        )
        if is_mutation:
            context = self.execution_context.context
            db = (
                context.get("db")
                if isinstance(context, dict)
                else getattr(context, "db", None)
            )
            if db:
                try:
                    async with transaction_scope(db):
                        yield
                        if self.execution_context.errors:
                            raise RuntimeError(
                                f"GraphQL Mutation failed: {self.execution_context.errors}"
                            )
                except RuntimeError:
                    pass
                return
        yield
