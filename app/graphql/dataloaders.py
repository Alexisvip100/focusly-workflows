from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from sqlalchemy import or_
from sqlalchemy.future import select
from strawberry.dataloader import DataLoader

from app.models import Workspace, ProjectGroup

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def get_loaders(db: AsyncSession, db_lock: asyncio.Lock) -> dict[str, DataLoader]:
    """Factory creating request-scoped DataLoaders that safely reuse the request's
    existing AsyncSession under db_lock serialization without spawning extra sessions.
    """

    async def batch_load_workspaces_for_tasks(keys: list[tuple[str, str | None]]) -> list[Workspace | None]:
        """Loads workspaces for tasks in a single query, supporting both the canonical
        Task.workspaceId link and the legacy Workspace.taskId link without dual queries.
        """
        if not keys:
            return []
        task_ids = list({k[0] for k in keys if k[0]})
        workspace_ids = list({k[1] for k in keys if k[1]})

        clauses = []
        if workspace_ids:
            clauses.append(Workspace.id.in_(workspace_ids))
        if task_ids:
            clauses.append(Workspace.taskId.in_(task_ids))

        if not clauses:
            return [None] * len(keys)

        async with db_lock:
            result = await db.execute(select(Workspace).where(or_(*clauses)))
            workspaces = result.scalars().all()

        ws_by_id = {w.id: w for w in workspaces}
        ws_by_task = {w.taskId: w for w in workspaces if w.taskId is not None}

        results: list[Workspace | None] = []
        for tid, wid in keys:
            if wid and wid in ws_by_id:
                results.append(ws_by_id[wid])
            elif tid and tid in ws_by_task:
                results.append(ws_by_task[tid])
            else:
                results.append(None)
        return results

    async def batch_load_projects_by_id(project_ids: list[str]) -> list[ProjectGroup | None]:
        if not project_ids:
            return []
        unique_ids = list(set(project_ids))
        async with db_lock:
            result = await db.execute(
                select(ProjectGroup).where(ProjectGroup.id.in_(unique_ids))
            )
            groups = result.scalars().all()
            grp_map = {g.id: g for g in groups}
            return [grp_map.get(pid) for pid in project_ids]

    return {
        "task_workspace_loader": DataLoader(load_fn=batch_load_workspaces_for_tasks),
        "project_by_id_loader": DataLoader(load_fn=batch_load_projects_by_id),
    }

