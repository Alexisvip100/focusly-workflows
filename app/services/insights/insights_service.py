import re
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.models import Task, FocusSession, User
from sqlalchemy import or_

class InsightsService:
    def __init__(self, db: AsyncSession, tasks_service=None, focus_sessions_service=None, users_service=None):
        self.db = db
        self.tasks_service = tasks_service
        self.focus_sessions_service = focus_sessions_service
        self.users_service = users_service

    async def getInsights(self, user_id: str, filter_type: str, timezone_offset_minutes: int = 0) -> Dict[str, Any]:
        # 1. Fetch data
        if self.tasks_service:
            all_tasks = await self.tasks_service.find_all_by_user(user_id)
        else:
            result = await self.db.execute(select(Task).where(Task.userId == user_id, Task.deletedAt == None, or_(Task.source != "google", Task.source == None)))
            all_tasks = [self._map_task_to_dict(t) for t in result.scalars().all()]

        if self.focus_sessions_service:
            all_focus_sessions = await self.focus_sessions_service.findAllByUser(user_id)
        else:
            result = await self.db.execute(select(FocusSession).where(FocusSession.userId == user_id))
            all_focus_sessions = list(result.scalars().all())

        if self.users_service:
            user = await self.users_service.findOne(user_id)
        else:
            result = await self.db.execute(select(User).where(User.id == user_id))
            user = result.scalars().first()

        # 2. Determine Date Range based on filter
        # timezone_offset_minutes: JS getTimezoneOffset() value (e.g. 360 for UTC-6)
        # Subtract offset to convert UTC → local time
        now = datetime.utcnow() - timedelta(minutes=timezone_offset_minutes)
        start_date = datetime(now.year, now.month, now.day)

        if filter_type == "Daily":
            pass  # Keep start_date as beginning of today
        elif filter_type == "Weekly":
            day_of_week = start_date.weekday()
            start_date = start_date - timedelta(days=day_of_week)
        elif filter_type == "Monthly":
            start_date = datetime(start_date.year, start_date.month, 1)
        else:
            day_of_week = start_date.weekday()
            start_date = start_date - timedelta(days=day_of_week)

        # 3. Filter Tasks
        filtered_tasks = []
        for t in all_tasks:
            updated_str = t.get("updatedAt") or t.get("createdAt")
            task_date = datetime.fromisoformat(updated_str.replace("Z", "+00:00")).replace(tzinfo=None) if updated_str else now
            if task_date >= start_date or t.get("status") != "Done":
                filtered_tasks.append(t)

        # 4. Calculate Metrics
        
        # Total Focus Hours
        total_minutes = sum(t.get("realTimer") or 0 for t in filtered_tasks)
        hours = total_minutes // 60
        mins = total_minutes % 60
        total_focus_hours = {
            "value": f"{hours}h {mins}m",
            "change": "+12% vs last period",
            "trend": "up"
        }

        # Task Completion
        total_in_period = len(filtered_tasks)
        completed_in_period = sum(1 for t in filtered_tasks if t.get("status") == "Done")
        completion_rate = round((completed_in_period / total_in_period) * 100) if total_in_period > 0 else 0
        task_completion = {
            "value": f"{completion_rate}%",
            "change": "+5% vs last period",
            "trend": "up"
        }

        energy_score = self.calculate_energy_score(filtered_tasks)
        
        user_settings = user.settings if user else None
        work_hours_config = user_settings.get("workHoursConfig") if isinstance(user_settings, dict) else None
        
        golden_window = self.calculate_golden_window(all_focus_sessions, work_hours_config)
        break_stats = self.calculate_break_hours(all_focus_sessions)

        # 5. Productivity Trends
        productivity_trends = self.calculate_productivity_trends(all_tasks, all_focus_sessions, filter_type)

        # 6. Time Distribution
        break_minutes = self.extract_break_minutes(break_stats["value"])
        time_distribution = self.calculate_time_distribution(filtered_tasks, break_minutes)

        # 7. Activity Map (completed tasks)
        heatmap_data, heatmap_labels, heatmap_cells = self.calculate_activity_map(all_tasks, filter_type, timezone_offset_minutes)

        return {
            "totalFocusHours": total_focus_hours,
            "taskCompletion": task_completion,
            "energyScore": energy_score,
            "goldenWindow": golden_window,
            "breakHours": break_stats,
            "productivityTrends": productivity_trends,
            "timeDistribution": time_distribution,
            "heatmap": heatmap_data,
            "heatmapLabels": heatmap_labels,
            "heatmapCells": heatmap_cells,
        }

    def _map_task_to_dict(self, t: Task) -> Dict[str, Any]:
        return {
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "estimateTimer": t.estimateTimer,
            "realTimer": t.realTimer,
            "deadline": t.deadline.isoformat() if t.deadline else None,
            "completedAt": t.completedAt.isoformat() if t.completedAt else None,
            "createdAt": t.createdAt.isoformat() if t.createdAt else None,
            "updatedAt": t.updatedAt.isoformat() if t.updatedAt else None,
            "category": t.category
        }

    def _get_completion_datetime(self, task: Dict[str, Any]) -> Optional[datetime]:
        if task.get("status") != "Done":
            return None
        for field in ("completedAt", "updatedAt", "createdAt"):
            val = task.get(field)
            if val:
                return datetime.fromisoformat(val.replace("Z", "+00:00")).replace(tzinfo=None)
        return None

    def _intensity_from_count(self, count: int, filter_type: str) -> int:
        if count == 0:
            return 0
        if filter_type == "Monthly":
            if count == 1:
                return 1
            if count <= 4:
                return 2
            return 3
        if count == 1:
            return 1
        if count <= 3:
            return 2
        if count <= 5:
            return 3
        if count <= 8:
            return 4
        return 5

    def _format_hour_label(self, hour: int) -> str:
        suffix = "AM" if hour < 12 else "PM"
        display = hour % 12
        display = 12 if display == 0 else display
        return f"{display} {suffix}"

    def calculate_activity_map(
        self,
        tasks: List[Dict[str, Any]],
        filter_type: str,
        timezone_offset_minutes: int = 0,
    ) -> Tuple[List[int], List[str], List[Dict[str, Any]]]:
        # Convert UTC now to user's local time
        now = datetime.utcnow() - timedelta(minutes=timezone_offset_minutes)
        completed_tasks = [t for t in tasks if self._get_completion_datetime(t) is not None]

        if filter_type == "Daily":
            return self._build_daily_activity_map(completed_tasks, now, timezone_offset_minutes)
        if filter_type == "Monthly":
            return self._build_monthly_activity_map(completed_tasks, now, timezone_offset_minutes)
        return self._build_weekly_activity_map(completed_tasks, now, timezone_offset_minutes)

    def _build_task_entry(self, task: Dict[str, Any]) -> Dict[str, Any]:
        completed_at = self._get_completion_datetime(task)
        return {
            "id": task.get("id", ""),
            "title": task.get("title") or "Untitled",
            "completedAt": completed_at.isoformat() if completed_at else None,
            "category": task.get("category"),
            "realTimer": task.get("realTimer"),
        }

    def _build_daily_activity_map(
        self,
        completed_tasks: List[Dict[str, Any]],
        now: datetime,
        timezone_offset_minutes: int = 0,
    ) -> Tuple[List[int], List[str], List[Dict[str, Any]]]:
        today = now.date()
        bucket: Dict[int, List[Dict[str, Any]]] = {h: [] for h in range(24)}

        for task in completed_tasks:
            completed_at = self._get_completion_datetime(task)
            if completed_at:
                # Convert task's UTC completed_at to user local time
                local_completed_at = completed_at - timedelta(minutes=timezone_offset_minutes)
                if local_completed_at.date() == today:
                    bucket[local_completed_at.hour].append(self._build_task_entry(task))

        cells = []
        intensities = []
        for hour in range(24):
            tasks_in_hour = bucket[hour]
            count = len(tasks_in_hour)
            intensity = self._intensity_from_count(count, "Daily")
            intensities.append(intensity)
            cells.append({
                "key": str(hour),
                "label": self._format_hour_label(hour),
                "intensity": intensity,
                "count": count,
                "tasks": tasks_in_hour,
            })

        return intensities, ["12 AM", "6 AM", "12 PM", "6 PM", "11 PM"], cells

    def _build_weekly_activity_map(
        self,
        completed_tasks: List[Dict[str, Any]],
        now: datetime,
        timezone_offset_minutes: int = 0,
    ) -> Tuple[List[int], List[str], List[Dict[str, Any]]]:
        day_of_week = now.weekday()
        monday = (now - timedelta(days=day_of_week)).date()
        day_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        full_day_names = [
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        ]
        days = [monday + timedelta(days=i) for i in range(7)]
        bucket: Dict[str, List[Dict[str, Any]]] = {d.isoformat(): [] for d in days}

        for task in completed_tasks:
            completed_at = self._get_completion_datetime(task)
            if completed_at:
                local_completed_at = completed_at - timedelta(minutes=timezone_offset_minutes)
                date_key = local_completed_at.date().isoformat()
                if date_key in bucket:
                    bucket[date_key].append(self._build_task_entry(task))

        cells = []
        intensities = []
        for i, day in enumerate(days):
            date_key = day.isoformat()
            tasks_on_day = bucket[date_key]
            count = len(tasks_on_day)
            intensity = self._intensity_from_count(count, "Weekly")
            intensities.append(intensity)
            cells.append({
                "key": date_key,
                "label": f"{full_day_names[i]}, {day.strftime('%b %d')}",
                "intensity": intensity,
                "count": count,
                "tasks": tasks_on_day,
            })

        return intensities, day_names, cells

    def _build_monthly_activity_map(
        self,
        completed_tasks: List[Dict[str, Any]],
        now: datetime,
        timezone_offset_minutes: int = 0,
    ) -> Tuple[List[int], List[str], List[Dict[str, Any]]]:
        month_days = [(now - timedelta(days=i)).date() for i in range(29, -1, -1)]
        bucket: Dict[str, List[Dict[str, Any]]] = {d.isoformat(): [] for d in month_days}

        for task in completed_tasks:
            completed_at = self._get_completion_datetime(task)
            if completed_at:
                local_completed_at = completed_at - timedelta(minutes=timezone_offset_minutes)
                date_key = local_completed_at.date().isoformat()
                if date_key in bucket:
                    bucket[date_key].append(self._build_task_entry(task))

        cells = []
        intensities = []
        for day in month_days:
            date_key = day.isoformat()
            tasks_on_day = bucket[date_key]
            count = len(tasks_on_day)
            intensity = self._intensity_from_count(count, "Monthly")
            intensities.append(intensity)
            cells.append({
                "key": date_key,
                "label": day.strftime("%A, %b %d"),
                "intensity": intensity,
                "count": count,
                "tasks": tasks_on_day,
            })

        return intensities, ["Start", "Middle", "End"], cells

    def extract_break_minutes(self, break_value: str) -> int:
        match = re.match(r"(\d+)h\s+(\d+)m", break_value)
        if match:
            return int(match.group(1)) * 60 + int(match.group(2))
        return 0

    def calculate_energy_score(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not tasks:
            return {"value": "N/A", "change": "0 pts", "trend": "neutral"}

        completed = [t for t in tasks if t.get("status") == "Done"]
        completion_rate = len(completed) / len(tasks)

        efficiency_sum = 0.0
        tasks_with_time = 0
        for t in completed:
            est = t.get("estimateTimer") or 0
            real = t.get("realTimer") or 0
            if est > 0 and real > 0:
                eff = min(est / real, 1.5)
                efficiency_sum += eff
                tasks_with_time += 1

        efficiency = efficiency_sum / tasks_with_time if tasks_with_time > 0 else 0.8
        raw_score = completion_rate * 60 + efficiency * 40
        score = min(max(round(raw_score), 0), 100)

        return {
            "value": f"{score}/100",
            "change": "+2 pts",
            "trend": "up"
        }

    def calculate_golden_window(
        self,
        sessions: List[FocusSession],
        work_hours: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not sessions:
            start = work_hours.get("startTime") if work_hours else "09:00"
            end = work_hours.get("endTime") if work_hours else "11:00"
            return {
                "value": f"{start} - {end}",
                "change": "Base on your profile",
                "trend": "neutral"
            }

        hour_stats = [0] * 24
        for s in sessions:
            started_at = s.startedAt
            if isinstance(started_at, str):
                started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            hour = started_at.hour
            hour_stats[hour] += s.durationMinutes or 0

        max_minutes = 0
        best_start_hour = 9

        for i in range(23):
            window_sum = hour_stats[i] + hour_stats[i + 1]
            if window_sum > max_minutes:
                max_minutes = window_sum
                best_start_hour = i

        def format_hour(h: int) -> str:
            hh = h % 24
            suffix = "PM" if hh >= 12 else "AM"
            display_h = hh - 12 if hh > 12 else (12 if hh == 0 else hh)
            return f"{display_h} {suffix}"

        return {
            "value": f"{format_hour(best_start_hour)} - {format_hour(best_start_hour + 2)}",
            "change": "Most productive period",
            "trend": "neutral"
        }

    def calculate_break_hours(self, sessions: List[FocusSession]) -> Dict[str, Any]:
        if len(sessions) < 2:
            return {"value": "0h 0m", "change": "0%", "trend": "neutral"}

        def get_start_time(s: FocusSession) -> float:
            started = s.startedAt
            if isinstance(started, str):
                started = datetime.fromisoformat(started.replace("Z", "+00:00"))
            return started.timestamp()

        sorted_sessions = sorted(sessions, key=get_start_time)
        break_minutes = 0.0

        for i in range(len(sorted_sessions) - 1):
            started_at = sorted_sessions[i].startedAt
            if isinstance(started_at, str):
                started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            
            current_end = started_at.timestamp() + (sorted_sessions[i].durationMinutes or 0) * 60
            
            next_start_dt = sorted_sessions[i + 1].startedAt
            if isinstance(next_start_dt, str):
                next_start_dt = datetime.fromisoformat(next_start_dt.replace("Z", "+00:00"))
            
            next_start = next_start_dt.timestamp()

            gap_mins = (next_start - current_end) / 60.0
            if 15 <= gap_mins <= 120:
                break_minutes += gap_mins

        hours = int(break_minutes // 60)
        mins = int(round(break_minutes % 60))

        return {
            "value": f"{hours}h {mins}m",
            "change": "Calculated from gaps",
            "trend": "neutral"
        }

    def calculate_productivity_trends(
        self,
        tasks: List[Dict[str, Any]],
        sessions: List[FocusSession],
        filter_type: str
    ) -> List[Dict[str, Any]]:
        if filter_type == "Daily":
            return self.build_daily_trends(tasks, sessions)
        elif filter_type == "Monthly":
            return self.build_monthly_trends(tasks, sessions)
        return self.build_weekly_trends(tasks, sessions)

    def build_daily_trends(self, tasks: List[Dict[str, Any]], sessions: List[FocusSession]) -> List[Dict[str, Any]]:
        today = datetime.utcnow().date()
        trends = []
        for hour in range(8, 23):
            label = "12PM" if hour == 12 else (f"{hour - 12}PM" if hour > 12 else f"{hour}AM")

            # Planned
            planned_mins = 0.0
            for t in tasks:
                dl_str = t.get("deadline") or t.get("createdAt")
                if dl_str:
                    dl_date = datetime.fromisoformat(dl_str.replace("Z", "+00:00")).date()
                    if dl_date == today and t.get("estimateTimer"):
                        planned_mins += (t.get("estimateTimer") or 0) / 9.0

            # Actual
            actual_mins = 0.0
            for s in sessions:
                s_dt = s.startedAt
                if isinstance(s_dt, str):
                    s_dt = datetime.fromisoformat(s_dt.replace("Z", "+00:00"))
                if s_dt.date() == today and s_dt.hour == hour:
                    actual_mins += s.durationMinutes or 0

            if actual_mins == 0.0:
                for t in tasks:
                    u_str = t.get("updatedAt") or t.get("createdAt")
                    if u_str:
                        u_dt = datetime.fromisoformat(u_str.replace("Z", "+00:00"))
                        if u_dt.date() == today and u_dt.hour == hour:
                            actual_mins += t.get("realTimer") or 0

            trends.append({
                "label": label,
                "actual": round(actual_mins / 60.0, 1),
                "planned": round(planned_mins / 60.0, 1)
            })
        return trends

    def build_weekly_trends(self, tasks: List[Dict[str, Any]], sessions: List[FocusSession]) -> List[Dict[str, Any]]:
        now = datetime.utcnow()
        day_of_week = now.weekday()
        monday = (now - timedelta(days=day_of_week)).date()

        trends = []
        day_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

        for i in range(7):
            target_date = monday + timedelta(days=i)

            planned_mins = 0.0
            for t in tasks:
                dl_str = t.get("deadline") or t.get("createdAt")
                if dl_str:
                    dl_date = datetime.fromisoformat(dl_str.replace("Z", "+00:00")).date()
                    if dl_date == target_date:
                        planned_mins += t.get("estimateTimer") or 0

            actual_mins = 0.0
            for s in sessions:
                s_dt = s.startedAt
                if isinstance(s_dt, str):
                    s_dt = datetime.fromisoformat(s_dt.replace("Z", "+00:00"))
                if s_dt.date() == target_date:
                    actual_mins += s.durationMinutes or 0

            if actual_mins == 0.0:
                for t in tasks:
                    u_str = t.get("updatedAt") or t.get("createdAt")
                    if u_str:
                        u_date = datetime.fromisoformat(u_str.replace("Z", "+00:00")).date()
                        if u_date == target_date:
                            actual_mins += t.get("realTimer") or 0

            trends.append({
                "label": day_names[i],
                "actual": round(actual_mins / 60.0, 1),
                "planned": round(planned_mins / 60.0, 1)
            })
        return trends

    def build_monthly_trends(self, tasks: List[Dict[str, Any]], sessions: List[FocusSession]) -> List[Dict[str, Any]]:
        now = datetime.utcnow()
        year = now.year
        month = now.month
        
        first_day = datetime(year, month, 1).date()
        if month == 12:
            last_day = (datetime(year + 1, 1, 1) - timedelta(days=1)).date()
        else:
            last_day = (datetime(year, month + 1, 1) - timedelta(days=1)).date()

        trends = []
        week_start = first_day
        week_num = 1

        while week_start <= last_day:
            week_end = min(week_start + timedelta(days=6), last_day)
            label = f"W{week_num} ({week_start.day}-{week_end.day})"

            planned_mins = 0.0
            for t in tasks:
                dl_str = t.get("deadline") or t.get("createdAt")
                if dl_str:
                    dl_date = datetime.fromisoformat(dl_str.replace("Z", "+00:00")).date()
                    if week_start <= dl_date <= week_end:
                        planned_mins += t.get("estimateTimer") or 0

            actual_mins = 0.0
            for s in sessions:
                s_dt = s.startedAt
                if isinstance(s_dt, str):
                    s_dt = datetime.fromisoformat(s_dt.replace("Z", "+00:00"))
                s_date = s_dt.date()
                if week_start <= s_date <= week_end:
                    actual_mins += s.durationMinutes or 0

            if actual_mins == 0.0:
                for t in tasks:
                    u_str = t.get("updatedAt") or t.get("createdAt")
                    if u_str:
                        u_date = datetime.fromisoformat(u_str.replace("Z", "+00:00")).date()
                        if week_start <= u_date <= week_end:
                            actual_mins += t.get("realTimer") or 0

            trends.append({
                "label": label,
                "actual": round(actual_mins / 60.0, 1),
                "planned": round(planned_mins / 60.0, 1)
            })

            week_start = week_end + timedelta(days=1)
            week_num += 1

        return trends

    def calculate_time_distribution(self, tasks: List[Dict[str, Any]], break_minutes: int) -> List[Dict[str, Any]]:
        category_map = {"Deep Work": 0, "Meetings": 0, "Admin/Misc": 0}

        for t in tasks:
            cat = "Deep Work"
            raw_cat = (t.get("category") or "").lower()
            if "meet" in raw_cat:
                cat = "Meetings"
            elif "admin" in raw_cat or "misc" in raw_cat:
                cat = "Admin/Misc"
            category_map[cat] = category_map.get(cat, 0) + (t.get("realTimer") or 0)

        category_map["Rest/Breaks"] = break_minutes

        colors = {
            "Deep Work": "#3b82f6",
            "Meetings": "#6366f1",
            "Admin/Misc": "#8b5cf6",
            "Rest/Breaks": "#1e293b"
        }

        distribution = []
        for name, mins in category_map.items():
            distribution.append({
                "name": name,
                "value": mins,
                "color": colors.get(name, "#64748b")
            })
        return distribution

