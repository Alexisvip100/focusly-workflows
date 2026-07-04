"""
behavioral_analyzer.py

Aggregates user behavioral signals from Tasks, FocusSessions, and Workspaces
into hourly statistics. These aggregated (never raw) stats are used as input
for the AI pattern analysis — keeping user data private.
"""
from datetime import datetime, timedelta
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_

from app.models import Task, FocusSession, Workspace


class BehavioralAnalyzer:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def collect_signals(self, user_id: str) -> dict[str, Any]:
        """
        Fetch and aggregate behavioral signals for the given user.

        Returns a privacy-safe dict of aggregated statistics — no raw task
        titles, notes, or workspace content are included.
        """
        tasks = await self._fetch_tasks(user_id)
        sessions = await self._fetch_sessions(user_id)
        workspaces = await self._fetch_workspaces(user_id)

        hour_buckets = self._build_hour_buckets(tasks, sessions, workspaces)
        task_stats = self._compute_task_stats(tasks)
        session_stats = self._compute_session_stats(sessions)
        top_hours = self._top_productive_hours(hour_buckets)
        work_style = self._infer_work_style(hour_buckets, task_stats, session_stats)

        return {
            "hour_buckets": hour_buckets,
            "task_stats": task_stats,
            "session_stats": session_stats,
            "top_productive_hours": top_hours,
            "work_style_hint": work_style,
            "data_points": len(tasks) + len(sessions),
        }

    # ── Private Helpers ──────────────────────────────────────────────────────

    async def _fetch_tasks(self, user_id: str) -> list[Task]:
        result = await self.db.execute(
            select(Task).where(
                Task.userId == user_id,
                Task.deletedAt == None,
                or_(Task.source != "google", Task.source == None),
            )
        )
        return list(result.scalars().all())

    async def _fetch_sessions(self, user_id: str) -> list[FocusSession]:
        result = await self.db.execute(
            select(FocusSession).where(FocusSession.userId == user_id)
        )
        return list(result.scalars().all())

    async def _fetch_workspaces(self, user_id: str) -> list[Workspace]:
        result = await self.db.execute(
            select(Workspace).where(Workspace.userId == user_id)
        )
        return list(result.scalars().all())

    def _to_dt(self, value) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                return None
        return None

    def _build_hour_buckets(
        self,
        tasks: list[Task],
        sessions: list[FocusSession],
        workspaces: list[Workspace],
    ) -> dict[str, dict[str, Any]]:
        """
        For each hour (0-23) aggregate:
          - tasks_completed: tasks marked Done in that hour
          - tasks_started: tasks that entered In Progress in that hour (≈ updatedAt)
          - tasks_abandoned: tasks In Progress untouched > 72h
          - focus_minutes: total focus session minutes starting that hour
          - workspace_edits: workspace saves in that hour
          - efficiency_sum / efficiency_count: ratio real_timer / estimate_timer
        """
        buckets: dict[str, dict[str, Any]] = {
            str(h): {
                "tasks_completed": 0,
                "tasks_started": 0,
                "tasks_abandoned": 0,
                "focus_minutes": 0,
                "workspace_edits": 0,
                "efficiency_sum": 0.0,
                "efficiency_count": 0,
                "high_priority_completed": 0,
            }
            for h in range(24)
        }

        now = datetime.utcnow()
        stale_threshold = now - timedelta(hours=72)

        # --- Tasks ---
        for t in tasks:
            completed_at = self._to_dt(t.completedAt)
            updated_at = self._to_dt(t.updatedAt)

            if t.status == "Done" and completed_at:
                h = str(completed_at.hour)
                buckets[h]["tasks_completed"] += 1
                if t.priorityLevel and t.priorityLevel >= 4:
                    buckets[h]["high_priority_completed"] += 1
                # Efficiency: only meaningful when both timers > 0
                real = t.realTimer or 0
                est = t.estimateTimer or 0
                if est > 0 and real > 0:
                    ratio = min(est / real, 3.0)  # cap at 3x to avoid outliers
                    buckets[h]["efficiency_sum"] += ratio
                    buckets[h]["efficiency_count"] += 1

            elif t.status == "In Progress" and updated_at:
                h = str(updated_at.hour)
                buckets[h]["tasks_started"] += 1
                # Mark as abandoned if not touched for 72h
                if updated_at < stale_threshold:
                    buckets[h]["tasks_abandoned"] += 1

        # --- Focus Sessions ---
        for s in sessions:
            started_at = self._to_dt(s.startedAt)
            if started_at:
                h = str(started_at.hour)
                buckets[h]["focus_minutes"] += s.durationMinutes or 0

        # --- Workspace Edits ---
        for w in workspaces:
            updated_at = self._to_dt(w.updatedAt)
            if updated_at:
                h = str(updated_at.hour)
                buckets[h]["workspace_edits"] += 1

        # Compute final efficiency ratio per bucket
        for h in buckets:
            count = buckets[h]["efficiency_count"]
            if count > 0:
                buckets[h]["avg_efficiency"] = round(
                    buckets[h]["efficiency_sum"] / count, 2
                )
            else:
                buckets[h]["avg_efficiency"] = None
            # Clean up intermediary keys
            del buckets[h]["efficiency_sum"]
            del buckets[h]["efficiency_count"]

        return buckets

    def _compute_task_stats(self, tasks: list[Task]) -> dict[str, Any]:
        total = len(tasks)
        if total == 0:
            return {
                "total": 0,
                "completed": 0,
                "in_progress": 0,
                "abandoned": 0,
                "completion_rate": 0.0,
                "avg_real_minutes": 0,
            }

        now = datetime.utcnow()
        stale_threshold = now - timedelta(hours=72)

        completed = sum(1 for t in tasks if t.status == "Done")
        in_progress = sum(1 for t in tasks if t.status == "In Progress")
        abandoned = 0
        real_timers = []

        for t in tasks:
            updated_at = self._to_dt(t.updatedAt)
            if t.status == "In Progress" and updated_at and updated_at < stale_threshold:
                abandoned += 1
            if t.realTimer and t.realTimer > 0:
                real_timers.append(t.realTimer)

        avg_real = round(sum(real_timers) / len(real_timers)) if real_timers else 0

        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "abandoned": abandoned,
            "completion_rate": round(completed / total, 2) if total > 0 else 0.0,
            "avg_real_minutes": avg_real,
        }

    def _compute_session_stats(self, sessions: list[FocusSession]) -> dict[str, Any]:
        if not sessions:
            return {"total_sessions": 0, "total_focus_minutes": 0, "avg_session_minutes": 0}

        total_minutes = sum(s.durationMinutes or 0 for s in sessions)
        return {
            "total_sessions": len(sessions),
            "total_focus_minutes": total_minutes,
            "avg_session_minutes": round(total_minutes / len(sessions)),
        }

    def _top_productive_hours(
        self, buckets: dict[str, dict[str, Any]]
    ) -> list[int]:
        """
        Score each hour using a weighted formula:
          score = tasks_completed*3 + high_priority_completed*2 + focus_minutes*0.05 + workspace_edits*0.5
        Returns top-3 hours sorted by score descending.
        """
        scored = []
        for h, b in buckets.items():
            score = (
                b["tasks_completed"] * 3
                + b["high_priority_completed"] * 2
                + b["focus_minutes"] * 0.05
                + b["workspace_edits"] * 0.5
            )
            scored.append((int(h), score))
        scored.sort(key=lambda x: x[1], reverse=True)
        # Filter hours with score > 0
        return [item[0] for item in scored[:3] if item[1] > 0]

    def _infer_work_style(
        self,
        buckets: dict[str, dict[str, Any]],
        task_stats: dict[str, Any],
        session_stats: dict[str, Any],
    ) -> str:
        """
        Heuristic classification of work style to give Gemini extra context.
        Possible values: morning_focused, afternoon_focused, night_owl,
                         deep_worker, sprinter, multitasker, inconsistent
        """
        morning = sum(buckets[str(h)]["tasks_completed"] for h in range(6, 12))
        afternoon = sum(buckets[str(h)]["tasks_completed"] for h in range(12, 18))
        evening = sum(buckets[str(h)]["tasks_completed"] for h in range(18, 24))

        avg_session = session_stats.get("avg_session_minutes", 0)
        completion = task_stats.get("completion_rate", 0)

        if avg_session >= 45:
            style = "deep_worker"
        elif avg_session > 0 and avg_session < 20:
            style = "sprinter"
        elif morning >= afternoon and morning >= evening and morning > 0:
            style = "morning_focused"
        elif afternoon > morning and afternoon >= evening:
            style = "afternoon_focused"
        elif evening > morning and evening > afternoon:
            style = "night_owl"
        elif completion < 0.4:
            style = "inconsistent"
        else:
            style = "balanced"

        return style
