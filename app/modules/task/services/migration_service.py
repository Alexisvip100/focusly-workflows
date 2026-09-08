"""Backward-compatible proxy module for MigrationService."""
from app.modules.task.services.migration.migration_service import MigrationService

FocuslyTaskMigrator = MigrationService

__all__ = ["MigrationService", "FocuslyTaskMigrator"]
