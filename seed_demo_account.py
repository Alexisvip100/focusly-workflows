"""Fill an account with realistic data for recording the product demo.

The persona is a freelance UX designer with two clients: this week's plan
(with free afternoons left for Lumina to fill on camera), a backlog, client
projects with their docs, and four weeks of finished work and focus sessions
so Insights has charts to show.

The account must exist first: sign in with it once (Google, so the demo can
show the Calendar sync). Every row this script makes has an id derived from
the account's email, so running it again updates the same rows instead of
duplicating them, and --reset removes exactly those rows.

Usage (dates are laid out in the recorder's time zone, UTC-6 by default):
    python seed_demo_account.py demo@example.com            # seed (and make Pro)
    python seed_demo_account.py demo@example.com --dry-run  # only print the plan
    python seed_demo_account.py demo@example.com --reset    # remove the demo data
    python seed_demo_account.py demo@example.com --tz -5 --no-pro
"""

import argparse
import asyncio
import os
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import delete, select  # noqa: E402

from app.database import async_session_local  # noqa: E402
from app.models import FocusSession, ProjectGroup, Task, User, Workspace  # noqa: E402

NAMESPACE = uuid.UUID("5d0c7a3e-9f1b-4c55-a2de-0f0c05e1d3a1")

# ─── Content ────────────────────────────────────────────────────────────────

PROJECTS = [
    ("aurora", "Café Aurora · Rebranding", "#f59e0b", "☕"),
    ("fitlab", "FitLab · App móvil", "#10b981", "💪"),
    ("studio", "Mi estudio", "#8b5cf6", "✨"),
]

WORKSPACES = [
    (
        "aurora-brief",
        "aurora",
        "Brief · Café Aurora",
        "☕",
        """# Brief · Café Aurora

> **Objetivo**: renovar la identidad de una cafetería de especialidad con 3 sucursales, sin perder a la clientela de siempre.

## Lo que pidió el cliente
- Logo nuevo que funcione en vasos, bolsas y redes
- Paleta cálida, nada de café "genérico"
- Menú impreso y versión digital para pedidos

## Público
Profesionales de 25–40 años que trabajan desde la cafetería por las mañanas.

## Entregables y fechas
| Entregable | Fecha |
|---|---|
| Moodboard | Semana 1 |
| 3 propuestas de logo | Semana 2 |
| Manual de marca | Semana 4 |

## Notas de la llamada
- Les encanta el tono de *Blue Bottle*, pero quieren algo más local
- El dueño quiere que aparezca el volcán de la ciudad 🌋
""",
    ),
    (
        "fitlab-notes",
        "fitlab",
        "Reuniones · FitLab",
        "💪",
        """# Reuniones · FitLab

## Kickoff
- App para que entrenadores armen rutinas y den seguimiento a sus alumnos
- MVP en 8 semanas; yo hago UX/UI, ellos el desarrollo

## Revisión de wireframes
- ✅ Onboarding aprobado
- 🔁 La pantalla de progreso tiene demasiados datos: simplificar
- ❓ ¿Modo oscuro desde el MVP? Lo deciden el viernes

## Pendientes
- [ ] Prototipo navegable del flujo "crear rutina"
- [ ] Test con 5 entrenadores
- [x] Mapa de pantallas
""",
    ),
    (
        "studio-content",
        "studio",
        "Plan de contenido · Instagram",
        "✨",
        """# Plan de contenido · Instagram

Meta: **2 publicaciones por semana** mostrando procesos reales, no solo resultados.

## Ideas
1. Antes y después del logo de Café Aurora (cuando el cliente lo apruebe)
2. "Cómo organizo mi semana como freelance" (carrusel)
3. Errores comunes en apps de fitness (reel corto)

## Calendario
- Martes: carrusel educativo
- Viernes: proceso o caso de estudio
""",
    ),
]

# Free-form backlog: no dates, waiting to be planned.
BACKLOG = [
    ("Preparar cotización para nuevo cliente", "studio", 3, 60),
    ("Actualizar portafolio con FitLab", "studio", 2, 90),
    ("Investigar referencias de apps de entrenamiento", "fitlab", 2, 45),
    ("Renovar dominio del sitio web", "studio", 1, 15),
]

# This week: (weekday 0=Mon, start hour, minutes, title, project, priority).
# Thursday and Friday afternoons stay free for Lumina to plan on camera.
WEEK = [
    (0, 9.0, 90, "Moodboard final para Café Aurora", "aurora", 3),
    (0, 11.5, 60, "Llamada semanal con FitLab", "fitlab", 2),
    (0, 15.0, 60, "Responder correos y facturación", "studio", 1),
    (1, 9.0, 120, "Bocetos de logo · 3 direcciones", "aurora", 4),
    (1, 14.0, 90, "Wireframes · pantalla de progreso", "fitlab", 3),
    (2, 9.0, 120, "Diseño UI · flujo crear rutina", "fitlab", 4),
    (2, 13.0, 45, "Carrusel: cómo organizo mi semana", "studio", 2),
    (2, 16.0, 60, "Presentación de propuestas a Café Aurora", "aurora", 4),
    (3, 9.0, 120, "Prototipo navegable FitLab", "fitlab", 4),
    (3, 12.0, 30, "Revisar comentarios del cliente", "aurora", 2),
    (4, 9.5, 90, "Ajustes al logo elegido", "aurora", 3),
    (4, 11.5, 45, "Planear la semana siguiente", "studio", 2),
]

SUBTASKS = {
    "Bocetos de logo · 3 direcciones": ["Dirección clásica", "Dirección moderna", "Dirección ilustrada"],
    "Prototipo navegable FitLab": ["Conectar pantallas en Figma", "Animaciones básicas", "Enviar link al equipo"],
    "Moodboard final para Café Aurora": ["Paleta de color", "Tipografías", "Fotografía de referencia"],
}

# History: tasks finished in past weeks, worked mostly in the morning so
# Insights finds a clear "golden hour".
HISTORY_TITLES = [
    ("Investigación de competencia", "aurora"),
    ("Entrevistas con clientes de la cafetería", "aurora"),
    ("Mapa de pantallas FitLab", "fitlab"),
    ("Wireframes de onboarding", "fitlab"),
    ("Sistema de componentes base", "fitlab"),
    ("Propuesta y cotización Café Aurora", "aurora"),
    ("Publicación: caso de estudio", "studio"),
    ("Factura de octubre", "studio"),
    ("Revisión de accesibilidad", "fitlab"),
    ("Guía de iconografía", "aurora"),
]


# ─── Helpers ────────────────────────────────────────────────────────────────


def make_id(email: str, key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{email.lower()}:{key}"))


def to_utc(local_day: date, hour: float, tz_hours: float) -> datetime:
    """A local wall-clock time as the naive UTC datetime the database stores."""
    local = datetime.combine(local_day, time(0)) + timedelta(hours=hour)
    return local - timedelta(hours=tz_hours)


def build(email: str, user_id: str, tz_hours: float, today: date):
    rnd = random.Random(email)  # noqa: S311 (same data on every run; not for security)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    monday = today - timedelta(days=today.weekday())
    project_ids = {key: make_id(email, f"project:{key}") for key, *_ in PROJECTS}

    projects = [
        ProjectGroup(id=project_ids[key], name=name, userId=user_id, color=color, emoji=emoji)
        for key, name, color, emoji in PROJECTS
    ]
    workspaces = [
        Workspace(
            id=make_id(email, f"workspace:{key}"),
            userId=user_id,
            title=title,
            emoji=emoji,
            groupId=project_ids[project],
            content=content,
            saveStatus=True,
        )
        for key, project, title, emoji, content in WORKSPACES
    ]
    color_of = {key: color for key, _, color, _ in PROJECTS}

    def task(key, title, project, priority, estimate, **extra):
        return Task(
            id=make_id(email, f"task:{key}"),
            userId=user_id,
            title=title,
            notes=extra.pop("notes", ""),
            estimateTimer=estimate,
            priorityLevel=priority,
            category="Personal" if project == "studio" else "Work",
            color=color_of[project],
            projectId=project_ids[project],
            task_type="PlatformTask",
            source="platform",
            is_owner=True,
            use_ai=False,
            tags=[],
            links=[],
            subtasks=extra.pop("subtasks", []),
            time_logs=extra.pop("time_logs", []),
            **extra,
        )

    tasks, sessions = [], []

    for i, (title, project, priority, estimate) in enumerate(BACKLOG):
        tasks.append(task(f"backlog:{i}", title, project, priority, estimate, status="Todo",
                          createdAt=now - timedelta(days=3 + i)))

    for i, (weekday, hour, minutes, title, project, priority) in enumerate(WEEK):
        day = monday + timedelta(days=weekday)
        start = to_utc(day, hour, tz_hours)
        end = start + timedelta(minutes=minutes)
        done = end < now
        subtasks = [
            {"id": make_id(email, f"sub:{title}:{n}"), "title": s, "completed": done,
             "completed_at": end.isoformat() if done else None}
            for n, s in enumerate(SUBTASKS.get(title, []))
        ]
        real = round(minutes * rnd.uniform(0.85, 1.2)) if done else None
        tasks.append(task(
            f"week:{i}", title, project, priority, minutes,
            status="Done" if done else "Todo",
            estimated_start_date=start,
            estimated_end_date=end,
            deadline=end,
            completedAt=end if done else None,
            realTimer=real,
            time_logs=[{"date": day.isoformat(), "minutes": real}] if done else [],
            subtasks=subtasks,
            createdAt=start - timedelta(days=4),
        ))
        if done:
            sessions.append((f"week:{i}", start, real))

    # Four weeks back: 2–3 finished tasks per weekday, mostly mornings.
    n = 0
    for week in range(1, 5):
        week_monday = monday - timedelta(weeks=week)
        for weekday in range(5):
            day = week_monday + timedelta(days=weekday)
            for slot in range(rnd.choice([2, 2, 3])):
                title, project = rnd.choice(HISTORY_TITLES)
                hour = rnd.choice([9, 9.5, 10, 10.5, 11]) if slot == 0 else rnd.choice([12, 14, 15.5, 16.5])
                estimate = rnd.choice([45, 60, 90, 120])
                real = round(estimate * rnd.uniform(0.8, 1.3))
                start = to_utc(day, hour, tz_hours)
                end = start + timedelta(minutes=real)
                key = f"history:{n}"
                tasks.append(task(
                    key, title, project, rnd.choice([2, 2, 3, 4]), estimate,
                    status="Done",
                    estimated_start_date=start,
                    estimated_end_date=start + timedelta(minutes=estimate),
                    completedAt=end,
                    realTimer=real,
                    time_logs=[{"date": day.isoformat(), "minutes": real}],
                    createdAt=start - timedelta(days=rnd.randint(1, 6)),
                ))
                sessions.append((key, start, real))
                n += 1

    focus = []
    for key, start, minutes in sessions:
        # Pomodoro-like blocks of up to 50 minutes with short breaks
        offset = 0
        part = 0
        while offset < minutes:
            length = min(50, minutes - offset)
            begin = start + timedelta(minutes=offset + part * 10)
            focus.append(FocusSession(
                id=make_id(email, f"focus:{key}:{part}"),
                userId=user_id,
                taskId=make_id(email, f"task:{key}"),
                startedAt=begin,
                endedAt=begin + timedelta(minutes=length),
                durationMinutes=length,
                distractionCount=rnd.choice([0, 0, 0, 1, 2]) if begin.hour + tz_hours < 12 else rnd.choice([0, 1, 2, 3]),
                wasSuccessful=True,
            ))
            offset += length
            part += 1

    return projects, workspaces, tasks, focus


# ─── Main ───────────────────────────────────────────────────────────────────


async def main(email: str, tz_hours: float, reset: bool, dry_run: bool, pro: bool) -> None:
    async with async_session_local() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            sys.exit(f"No account with email {email}: sign in with it once first.")

        local_today = (datetime.now(timezone.utc) + timedelta(hours=tz_hours)).date()
        projects, workspaces, tasks, focus = build(email, user.id, tz_hours, local_today)
        groups = [(ProjectGroup, projects), (Workspace, workspaces), (Task, tasks), (FocusSession, focus)]

        if reset:
            for model, rows in groups:
                if not dry_run:
                    await db.execute(delete(model).where(model.id.in_([r.id for r in rows])))
                print(f"remove {len(rows):>4} {model.__name__}")
            if not dry_run:
                await db.commit()
            print("Demo data removed." if not dry_run else "(dry run, nothing changed)")
            return

        for model, rows in groups:
            print(f"upsert {len(rows):>4} {model.__name__}")
            if not dry_run:
                for row in rows:
                    await db.merge(row)
        if pro:
            print(f"plan   {user.subscriptionStatus} -> pro")
            if not dry_run:
                user.subscriptionStatus = "pro"
        if not dry_run:
            await db.commit()
        print(f"This week: {len(WEEK)} scheduled tasks; Thursday and Friday afternoons are free for Lumina.")
        print("Done." if not dry_run else "(dry run, nothing changed)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email")
    parser.add_argument("--tz", type=float, default=-6, help="recorder's UTC offset in hours (default -6)")
    parser.add_argument("--reset", action="store_true", help="remove the demo data instead")
    parser.add_argument("--dry-run", action="store_true", help="print what would change, change nothing")
    parser.add_argument("--no-pro", action="store_true", help="leave the account's plan as it is")
    args = parser.parse_args()
    asyncio.run(main(args.email.strip(), args.tz, args.reset, args.dry_run, not args.no_pro))
