import strawberry
from typing import Optional

from app.graphql import types
from app.graphql.common import get_user_id
from app.services.tasks.tasks_service import TasksService
from app.services.insights.insights_service import InsightsService


@strawberry.type
class InsightsQuery:
    @strawberry.field
    async def get_insights(
        self,
        info,
        user_id: str,
        filter: Optional[str] = "Weekly",
        timezone_offset: Optional[int] = 0,
    ) -> types.InsightsResponse:
        get_user_id(info)
        db = info.context["db"]
        
        # Instantiate services needed by insights_service
        from app.services.users.users_service import UsersService
        from app.services.focus_sessions.focus_sessions_service import FocusSessionsService
        
        users_serv = UsersService(db)
        tasks_serv = TasksService(db)
        fs_serv = FocusSessionsService(db)
        
        insights_serv = InsightsService(
            db=db,
            tasks_service=tasks_serv,
            focus_sessions_service=fs_serv,
            users_service=users_serv
        )
        
        res = await insights_serv.getInsights(user_id, filter or "Weekly", timezone_offset or 0)
        
        # Map ProductivityTrend
        trends = []
        for t in res["productivityTrends"]:
            trends.append(types.ProductivityTrend(
                label=t["label"],
                actual=float(t["actual"]),
                planned=float(t["planned"])
            ))
            
        # Map TimeDistribution
        dist = []
        for d in res["timeDistribution"]:
            dist.append(types.TimeDistribution(
                name=d["name"],
                value=float(d["value"]),
                color=d["color"]
            ))

        return types.InsightsResponse(
            total_focus_hours=types.StatCardValue(
                value=res["totalFocusHours"]["value"],
                change=res["totalFocusHours"]["change"],
                trend=res["totalFocusHours"]["trend"]
            ),
            task_completion=types.StatCardValue(
                value=res["taskCompletion"]["value"],
                change=res["taskCompletion"]["change"],
                trend=res["taskCompletion"]["trend"]
            ),
            energy_score=types.StatCardValue(
                value=res["energyScore"]["value"],
                change=res["energyScore"]["change"],
                trend=res["energyScore"]["trend"]
            ),
            golden_window=types.StatCardValue(
                value=res["goldenWindow"]["value"],
                change=res["goldenWindow"]["change"],
                trend=res["goldenWindow"]["trend"]
            ),
            break_hours=types.StatCardValue(
                value=res["breakHours"]["value"],
                change=res["breakHours"]["change"],
                trend=res["breakHours"]["trend"]
            ),
            productivity_trends=trends,
            time_distribution=dist,
            heatmap=res["heatmap"],
            heatmap_labels=res["heatmapLabels"],
            heatmap_cells=[
                types.HeatmapCell(
                    key=cell["key"],
                    label=cell["label"],
                    intensity=cell["intensity"],
                    count=cell["count"],
                    tasks=[
                        types.HeatmapCompletedTask(
                            id=t["id"],
                            title=t["title"],
                            completed_at=t.get("completedAt"),
                            category=t.get("category"),
                            real_timer=t.get("realTimer"),
                        )
                        for t in cell["tasks"]
                    ],
                )
                for cell in res.get("heatmapCells", [])
            ],
        )