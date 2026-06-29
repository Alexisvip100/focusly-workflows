from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import Conversation, Message, ProjectGroup, Workspace, Task
from .prompts import SYSTEM_PROMPT
from .memory import search_memories

async def build_context(user_id: str, conversation_id: str, query: str, db: AsyncSession) -> str:
    """
    Builds the full prompt context for the LLM.
    """
    import datetime
    now_utc = datetime.datetime.utcnow()
    context = f"{SYSTEM_PROMPT}\n\n--- ENVIRONMENT INFO ---\n- Current Date/Time: {now_utc.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
    
    # 1. Fetch relevant memories
    memories = await search_memories(user_id, query, db)
    if memories:
        context += f"--- USER MEMORIES ---\n{memories}\n\n"
        
    # 2. Fetch user's project groups
    groups_result = await db.execute(select(ProjectGroup).filter(ProjectGroup.userId == user_id))
    groups = groups_result.scalars().all()
    if groups:
        context += "--- EXISTING PROJECT GROUPS (FOLDERS) ---\n"
        for g in groups:
            context += f"- ID: {g.id}, Name: {g.name}\n"
        context += "\n"
        
    # 3. Fetch user's workspaces
    ws_result = await db.execute(select(Workspace).filter(Workspace.userId == user_id))
    workspaces = ws_result.scalars().all()
    if workspaces:
        context += "--- EXISTING WORKSPACES (DOCUMENTS) ---\n"
        for w in workspaces:
            context += f"- ID: {w.id}, Title: {w.title}, Project Group ID: {w.groupId or 'None (Ungrouped)'}\n"
        context += "\n"

    # 4. Fetch user's active tasks and calendar events
    tasks_result = await db.execute(
        select(Task)
        .filter(Task.userId == user_id)
        .filter(Task.deletedAt == None)
        .order_by(Task.deadline.asc())
    )
    tasks = tasks_result.scalars().all()
    if tasks:
        context += "--- USER TASKS AND CALENDAR EVENTS ---\n"
        for t in tasks:
            start_str = t.estimated_start_date.isoformat() if t.estimated_start_date else "None"
            end_str = t.estimated_end_date.isoformat() if t.estimated_end_date else "None"
            deadline_str = t.deadline.isoformat() if t.deadline else "None"
            source_info = f"Source: {t.source or 'focusly'}"
            if t.google_event_id:
                source_info += " (Synced from Google Calendar)"
            
            clean_title = (t.title or "").replace('\n', ' ').replace('\r', ' ').strip()
            clean_notes = (t.notesEncrypted or "").replace('\n', ' ').replace('\r', ' ').strip()
            
            context += (
                f"- ID: {t.id}\n"
                f"  Title: {clean_title}\n"
                f"  Status: {t.status}\n"
                f"  Priority: {t.priorityLevel}\n"
                f"  Start: {start_str}\n"
                f"  End: {end_str}\n"
                f"  Deadline: {deadline_str}\n"
                f"  {source_info}\n"
                f"  Notes/Description: {clean_notes or 'None'}\n\n"
            )

    # 5. Fetch user's productivity insights (weekly stats)
    try:
        from app.services.insights.insights_service import InsightsService
        insights_service = InsightsService(db)
        insights = await insights_service.getInsights(user_id, "Weekly")
        if insights:
            context += "--- USER PRODUCTIVITY INSIGHTS (WEEKLY SUMMARY) ---\n"
            context += f"- Total Focus Hours: {insights.get('totalFocusHours', {}).get('value', 'N/A')}\n"
            context += f"- Task Completion Rate: {insights.get('taskCompletion', {}).get('value', 'N/A')}\n"
            context += f"- Energy/Efficiency Score: {insights.get('energyScore', {}).get('value', 'N/A')}\n"
            context += f"- Golden Window (Most Productive Hours): {insights.get('goldenWindow', {}).get('value', 'N/A')}\n"
            context += f"- Break Time: {insights.get('breakHours', {}).get('value', 'N/A')}\n"
            
            time_dist = insights.get('timeDistribution', [])
            if time_dist:
                context += "- Time Distribution:\n"
                for item in time_dist:
                    context += f"  * {item.get('name')}: {item.get('value')} minutes\n"
                    
            trends = insights.get('productivityTrends', [])
            if trends:
                context += "- Daily Productivity Trends (Planned vs Actual Hours):\n"
                for t in trends:
                    context += f"  * {t.get('label')}: Planned {t.get('planned')}h, Actual {t.get('actual')}h\n"
            context += "\n"
    except Exception as e:
        print(f"[INSIGHTS CONTEXT ERROR] {e}")

    # 4. Fetch conversation summary
    conv_result = await db.execute(select(Conversation).filter(Conversation.id == conversation_id))
    conversation = conv_result.scalar_one_or_none()
    
    if conversation and conversation.summary:
        context += f"--- PREVIOUS CONVERSATION SUMMARY ---\n{conversation.summary}\n\n"
        
    # 3. Fetch recent messages
    if conversation:
        msg_result = await db.execute(
            select(Message)
            .filter(Message.conversationId == conversation_id)
            .order_by(Message.createdAt.desc())
            .limit(10)
        )
        recent_messages = msg_result.scalars().all()
        # They come out desc, so reverse them for chronological
        recent_messages.reverse()
        
        if recent_messages:
            context += "--- RECENT MESSAGES ---\n"
            for m in recent_messages:
                context += f"{m.role}: {m.content}\n"
    
    context += f"\nUser Query: {query}\n"
    return context
