import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update
from app.database import async_session_local
from app.models import Task, Workspace, ProjectGroup, User

USER_ID_1 = "6a3f9304-a4fc-432c-af3a-127ebbc7d047"  # alexisultreras01@gmail.com
USER_ID_2 = "1096bb4d-7d50-4f0d-b1c1-37b0790aae46"  # aultreras@grupoabraxas.com

# Base date: local today is 2026-09-28
TODAY = datetime(2026, 9, 28, 9, 0, 0)
TODAY_END = datetime(2026, 9, 28, 18, 0, 0)

TOMORROW = datetime(2026, 9, 29, 10, 0, 0)
IN_2_DAYS = datetime(2026, 9, 30, 11, 0, 0)
IN_3_DAYS = datetime(2026, 10, 1, 9, 30, 0)
IN_5_DAYS = datetime(2026, 10, 3, 14, 0, 0)

FAR_FUTURE = datetime(2026, 12, 31, 23, 59, 59)

async def main():
    async with async_session_local() as session:
        print("Checking existing project groups and workspaces...")
        projects_res = await session.execute(
            select(ProjectGroup).where(ProjectGroup.userId == USER_ID_1)
        )
        projects = {p.name: p for p in projects_res.scalars().all()}

        workspaces_res = await session.execute(
            select(Workspace).where(Workspace.userId == USER_ID_1)
        )
        workspaces = {w.title: w for w in workspaces_res.scalars().all()}

        print(f"Found {len(projects)} projects and {len(workspaces)} workspaces for primary user.")

        # ----------------------------------------------------------------------
        # 1. ACTUALIZAR Y CREAR WORKSPACES CON CONTEXTO RICO EN MARKDOWN
        # ----------------------------------------------------------------------
        print("\n=== Actualizando y enriqueciendo Workspaces con contenido Markdown profundo ===")

        # 1.1 SQL Workspace
        sql_ws_id = "edf35a86-b6e6-4e7f-8ce0-e4225d27ff65"
        sql_content = """# 📊 Notas y Queries para el Curso SQL Avanzado

> **Objetivo del Módulo**: Dominar la optimización de consultas, particionamiento de tablas y funciones de ventana en PostgreSQL para arquitecturas de alta concurrencia.

---

## 🚀 1. Window Functions (Funciones de Ventana)

Las funciones de ventana permiten realizar cálculos a través de un conjunto de filas que están relacionadas con la fila actual, sin colapsar el resultado como lo hace `GROUP BY`.

### 1.1 Cálculo de Promedios Móviles de 7 Días

```sql
WITH daily_focus_metrics AS (
    SELECT 
        DATE(created_at) AS metric_date,
        user_id,
        SUM(real_timer) AS total_focus_minutes
    FROM "Task"
    WHERE status = 'Done' AND deleted_at IS NULL
    GROUP BY DATE(created_at), user_id
)
SELECT 
    metric_date,
    user_id,
    total_focus_minutes,
    ROUND(
        AVG(total_focus_minutes) OVER (
            PARTITION BY user_id 
            ORDER BY metric_date 
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ), 2
    ) AS moving_avg_7d
FROM daily_focus_metrics
ORDER BY user_id, metric_date DESC;
```

### 1.2 Ranking y Detección de Tareas Críticas por Proyecto

```sql
SELECT 
    id,
    title,
    project_id,
    estimate_timer,
    priority_level,
    DENSE_RANK() OVER (
        PARTITION BY project_id 
        ORDER BY priority_level ASC, estimate_timer DESC
    ) AS priority_rank
FROM "Task"
WHERE status != 'Done';
```

---

## ⚡ 2. Optimización con Índices y EXPLAIN ANALYZE

### 2.1 Índice Compuesto para Filtros de la Bandeja y Hoy
```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_task_user_status_dates 
ON "Task" (user_id, status, estimated_start_date, deadline)
WHERE deleted_at IS NULL;
```

### 2.2 Estrategia de Indexación GIN para Búsqueda Full-Text
```sql
CREATE INDEX idx_task_search_gin 
ON "Task" USING gin(to_tsvector('spanish', coalesce(title, '') || ' ' || coalesce(notes_encrypted, '')));
```

---

## 📋 Checklist de Aprendizaje y Práctica
- [x] Sintaxis básica de `ROW_NUMBER()`, `RANK()` y `DENSE_RANK()`
- [x] Particionamiento temporal con `ROWS BETWEEN`
- [ ] Optimización de CTEs con `MATERIALIZED` vs `NOT MATERIALIZED`
- [ ] Implementación de triggers para auditoría de cambios
"""
        await session.execute(
            update(Workspace)
            .where(Workspace.id == sql_ws_id)
            .values(
                title="Notas y Queries para el Curso SQL",
                content=sql_content,
                emoji="📊",
                updatedAt=datetime.now()
            )
        )

        # 1.2 Playwright Workspace (Crear o Actualizar)
        playwright_pg = projects.get("Automatización de Tests End-to-End con Playwright")
        playwright_pg_id = playwright_pg.id if playwright_pg else None

        playwright_ws_id = "ws-playwright-e2e-spec"
        playwright_content = """# 🎭 Especificación Técnica: Suite de Pruebas E2E con Playwright

> **Documento de Arquitectura y Guía de Implementación**  
> **Proyecto**: Automatización de Tests End-to-End  
> **Stack**: Playwright Test, TypeScript, Docker, GitHub Actions

---

## 🎯 1. Objetivos del Sistema de Pruebas
1. Garantizar **cero regresiones visuales y funcionales** en flujos críticos de Focusly.
2. Reducir el tiempo de ejecución en CI a **menos de 4 minutos** mediante sharding paralelo.
3. Asegurar la consistencia de datos entre cliente React y backend GraphQL/FastAPI.

---

## 🏗️ 2. Arquitectura de Page Object Model (POM)

```mermaid
graph TD
    A[BasePage] --> B[LoginPage]
    A --> C[TasksPage]
    A --> D[ProjectsPage]
    A --> E[WorkspaceEditorPage]
    B --> F[AuthFixtures]
    C --> G[TaskModalComponent]
    D --> H[ProjectFolderComponent]
```

### 2.1 Estructura del Directorio de Tests
```text
e2e/
├── fixtures/
│   ├── auth.fixture.ts        # Inyección de storageState persistente
│   └── database.fixture.ts    # Seed y rollback transaccional
├── pages/
│   ├── LoginPage.ts
│   ├── TasksPage.ts
│   └── ProjectsPage.ts
└── specs/
    ├── auth.spec.ts
    ├── tasks-crud.spec.ts
    ├── calendar-sync.spec.ts
    └── projects-workflow.spec.ts
```

---

## ⚙️ 3. Configuración de Playwright (`playwright.config.ts`)
```typescript
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30 * 1000,
  expect: { timeout: 5000 },
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 4 : undefined,
  reporter: [['html'], ['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'setup', testMatch: /.*\.setup\.ts/ },
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], storageState: 'e2e/.auth/user.json' },
      dependencies: ['setup'],
    },
  ],
});
```

---

## ✅ Criterios de Aceptación y Definition of Done
- [x] Fixture de autenticación headless con guardado de token JWT
- [ ] Cobertura del 100% en flujos de creación, filtrado (Bandeja/Hoy/Próximos) y edición de tareas
- [ ] Verificación de sincronización con Webhooks y Socket.IO en tiempo real
- [ ] Pipeline en GitHub Actions configurado con artefactos de video y traces
"""
        existing_playwright_ws = await session.execute(
            select(Workspace).where(Workspace.id == playwright_ws_id)
        )
        if not existing_playwright_ws.scalars().first():
            new_pw_ws = Workspace(
                id=playwright_ws_id,
                userId=USER_ID_1,
                groupId=playwright_pg_id,
                title="Especificación Técnica: Suite de Tests Playwright E2E",
                emoji="🎭",
                content=playwright_content,
                saveStatus=True,
                createdAt=datetime.now(),
                updatedAt=datetime.now()
            )
            session.add(new_pw_ws)
        else:
            await session.execute(
                update(Workspace)
                .where(Workspace.id == playwright_ws_id)
                .values(content=playwright_content, updatedAt=datetime.now())
            )

        # 1.3 Redis Workspace (Crear o Actualizar)
        redis_pg = projects.get("Sistema de Cache Distribuido con Redis Cluster")
        redis_pg_id = redis_pg.id if redis_pg else None

        redis_ws_id = "ws-redis-cluster-architecture"
        redis_content = """# ⚡ Arquitectura del Sistema de Cache Distribuido con Redis Cluster

> **Especificación de Resiliencia y Rendimiento**  
> **Objetivo**: Reducir la latencia en lecturas repetitivas de tareas y workspaces a < 5ms bajo cargas de hasta 10,000 req/sec.

---

## 🏛️ 1. Patrón Cache-Aside con Invalidación Reactiva

```mermaid
sequenceDiagram
    participant Client as Frontend (Apollo)
    participant API as GraphQL Gateway
    participant Redis as Redis Cluster (Memory)
    participant DB as PostgreSQL (Primary)

    Client->>API: Query: GetTasksPaginated(userId, dateRange)
    API->>Redis: GET tasks:cache:{userId}:{filterHash}
    alt Cache Hit
        Redis-->>API: Retorna JSON serializado (2ms)
        API-->>Client: Respuesta HTTP 200 (Cache)
    else Cache Miss
        Redis-->>API: Key no encontrada (nil)
        API->>DB: SELECT * FROM "Task" WHERE ...
        DB-->>API: Filas de datos
        API->>Redis: SETEX tasks:cache:{userId}:{hash} TTL=300s
        API-->>Client: Respuesta HTTP 200 (DB)
    end
```

---

## 🔑 2. Estrategia de Claves y TTLs

| Entidad | Patrón de Key | TTL | Invalidación |
| :--- | :--- | :--- | :--- |
| **Lista de Tareas** | `tasks:user:{userId}:filter:{hash}` | 5 minutos | Al ejecutar `createTask`, `updateTask`, `deleteTask` |
| **Detalle de Tarea** | `task:item:{taskId}` | 15 minutos | Al actualizar la tarea o marcar subtarea |
| **Workspace Content** | `ws:content:{workspaceId}` | 30 minutos | Al persistir cambios en el editor markdown |
| **Métricas Golden Hours**| `insights:user:{userId}:summary` | 1 hora | Tarea nocturna o re-análisis manual |

---

## 🛡️ 3. Resiliencia y Failover
- **Fallback Automático**: Si la conexión a Redis falla o supera un timeout de 80ms, la aplicación hace bypass silencioso directo a PostgreSQL sin interrumpir la experiencia del usuario.
- **Circuit Breaker**: Implementación de patrón circuit-breaker para prevenir cascading failures hacia la base de datos si Redis se desconecta temporalmente.
"""
        existing_redis_ws = await session.execute(
            select(Workspace).where(Workspace.id == redis_ws_id)
        )
        if not existing_redis_ws.scalars().first():
            new_redis_ws = Workspace(
                id=redis_ws_id,
                userId=USER_ID_1,
                groupId=redis_pg_id,
                title="Diseño del Sistema de Cache Distribuido y Resiliencia",
                emoji="⚡",
                content=redis_content,
                saveStatus=True,
                createdAt=datetime.now(),
                updatedAt=datetime.now()
            )
            session.add(new_redis_ws)
        else:
            await session.execute(
                update(Workspace)
                .where(Workspace.id == redis_ws_id)
                .values(content=redis_content, updatedAt=datetime.now())
            )

        # 1.4 Onboarding Workspace (Crear o Actualizar)
        onboarding_pg = projects.get("Rediseño de la Experiencia de Onboarding")
        onboarding_pg_id = onboarding_pg.id if onboarding_pg else None

        onboarding_ws_id = "ws-onboarding-experience-spec"
        onboarding_content = """# 🚀 User Journey y Especificación del Nuevo Onboarding Focusly

> **Iniciativa de Crecimiento y Activación (PLG)**  
> **Meta Principal**: Incrementar el ratio de activación de nuevos usuarios del 28% al 55% en los primeros 7 días.

---

## 🗺️ 1. Flujo Paso a Paso de Activación

1. **Paso 1: Diagnóstico de Hábitos y Enfoque (30 segundos)**
   - Pregunta clave: *"¿Cuál es tu mayor obstáculo de productividad actual?"* (Procrastinación, multitarea caótica, sobrecarga de reuniones).
   - Selección de bloques ideales de concentración (ej. técnica Pomodoro de 25 min vs Deep Work de 90 min).

2. **Paso 2: Generación Asistida del Primer Proyecto con Lumina AI**
   - El usuario escribe en lenguaje natural su meta principal del mes (ej. *"Lanzar mi tienda online"* o *"Estudiar para mi examen de certificación"*).
   - Lumina desglosa automáticamente la meta en 4 tareas accionables con subtareas y estimaciones de tiempo.

3. **Paso 3: Programación en el Calendario Inteligente**
   - El algoritmo sugiere los mejores huecos del día según el cronotipo declarado del usuario.
   - Un click para confirmar y empezar la primera sesión de foco asistida.

---

## 📊 2. Métricas y KPIs de Éxito
- **Time-to-First-Task (TTFT)**: < 90 segundos desde el registro.
- **Ratio de completitud del Onboarding**: > 75%.
- **D7 Retention**: Retención a día 7 superior al 40%.
"""
        existing_onboarding_ws = await session.execute(
            select(Workspace).where(Workspace.id == onboarding_ws_id)
        )
        if not existing_onboarding_ws.scalars().first():
            new_onboarding_ws = Workspace(
                id=onboarding_ws_id,
                userId=USER_ID_1,
                groupId=onboarding_pg_id,
                title="User Journey & Especificación UX del Nuevo Onboarding",
                emoji="🚀",
                content=onboarding_content,
                saveStatus=True,
                createdAt=datetime.now(),
                updatedAt=datetime.now()
            )
            session.add(new_onboarding_ws)
        else:
            await session.execute(
                update(Workspace)
                .where(Workspace.id == onboarding_ws_id)
                .values(content=onboarding_content, updatedAt=datetime.now())
            )

        # 1.5 Enriquecer Workspace de Nutrición
        nutricion_ws_id = "36e69f77-7588-4844-941b-9c6db7f83edd"
        nutricion_content = """# 🥗 Fundamentos de Bioquímica Nutricional y Cálculo Metabólico

> **Manual de Consulta Rápida y Fórmulas de Prescripción Dietoterapéutica**

---

## 🔬 1. Ecuaciones de Estimación del Gasto Energético en Reposo (GER)

### 1.1 Fórmula de Mifflin-St Jeor (Estándar de Oro Clínico)
- **Hombres**: $GER = (10 \times \text{peso en kg}) + (6.25 \times \text{altura en cm}) - (5 \times \text{edad}) + 5$
- **Mujeres**: $GER = (10 \times \text{peso en kg}) + (6.25 \times \text{altura en cm}) - (5 \times \text{edad}) - 161$

### 1.2 Factores de Actividad Física (PAL)
| Nivel de Actividad | Factor Multiplicador | Descripción |
| :--- | :--- | :--- |
| **Sedentario** | 1.20 | Trabajo de escritorio, actividad física programada nula |
| **Ligero** | 1.375 | Ejercicio suave 1 a 3 días por semana |
| **Moderado** | 1.55 | Entrenamiento moderado 3 a 5 días por semana |
| **Intenso** | 1.725 | Ejercicio demandante 6 a 7 días por semana |
| **Atleta Elite** | 1.90 | Doble sesión diaria de alto rendimiento |

---

## 🥑 2. Distribución de Macronutrientes por Objetivo

1. **Hipertrofia y Rendimiento de Fuerza**:
   - Proteínas: $1.8 - 2.2 \text{ g/kg de peso corporal}$
   - Grasas saludables: $0.8 - 1.0 \text{ g/kg}$ (priorizando monoinsaturadas y omega-3)
   - Carbohidratos: Resto calórico ($4.0 - 6.0 \text{ g/kg}$) para soporte glucogénico

2. **Déficit Calórico y Definición Muscular**:
   - Proteínas: $2.2 - 2.6 \text{ g/kg}$ (efecto saciante y preservación de masa magra)
   - Grasas: $0.6 - 0.8 \text{ g/kg}$
   - Déficit moderado: $15\% - 20\%$ del Gasto Energético Total (GET)
"""
        await session.execute(
            update(Workspace)
            .where(Workspace.id == nutricion_ws_id)
            .values(
                title="Bioquímica de los Alimentos y Gasto Energético",
                content=nutricion_content,
                emoji="🥗",
                updatedAt=datetime.now()
            )
        )

        # ----------------------------------------------------------------------
        # 2. DEFINICIÓN DE LAS 13 TAREAS GENERALES (BANDEJA, HOY, PRÓXIMOS)
        # ----------------------------------------------------------------------
        print("\n=== Creando las 13 Tareas Generales (Bandeja: 4, Hoy: 5, Próximos: 4) ===")

        # 4 Tareas de Bandeja (Inbox)
        inbox_tasks = [
            {
                "id": str(uuid.uuid4()),
                "title": "Investigación de patrones Event-Driven: Kafka vs RabbitMQ para Microservicios",
                "notes": "Evaluar la latencia, costo operativo y garantías de entrega (Exactly-Once vs At-Least-Once) para el pipeline de eventos asíncronos en los servicios de Focusly.",
                "category": "Engineering",
                "priorityLevel": 3,
                "estimateTimer": 90,
                "status": "Backlog",
                "estimated_start_date": None,
                "deadline": FAR_FUTURE,
                "tags": [{"name": "Architecture", "color": "#008767"}, {"name": "Backend", "color": "#059669"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Revisar benchmarks oficiales de throughput y retención en disco", "completed": False, "estimate_timer": 30},
                    {"id": str(uuid.uuid4()), "title": "Analizar complejidad de administración en Kubernetes (Strimzi vs CloudAMQP)", "completed": False, "estimate_timer": 30},
                    {"id": str(uuid.uuid4()), "title": "Elaborar documento comparativo de costos y recomendación técnica", "completed": False, "estimate_timer": 30},
                ],
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Auditoría de dependencias y análisis de vulnerabilidades CVE en repositorios",
                "notes": "Escaneo preventivo de librerías en frontend (npm) y microservicios backend (pip) para mitigar vectores de ataque y cumplir estándares SOC2.",
                "category": "Security",
                "priorityLevel": 2,
                "estimateTimer": 60,
                "status": "Backlog",
                "estimated_start_date": None,
                "deadline": FAR_FUTURE,
                "tags": [{"name": "Security", "color": "#10b981"}, {"name": "DevOps", "color": "#047857"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Ejecutar npm audit y pip-audit en monorepo", "completed": False, "estimate_timer": 15},
                    {"id": str(uuid.uuid4()), "title": "Clasificar hallazgos de severidad crítica y alta", "completed": False, "estimate_timer": 20},
                    {"id": str(uuid.uuid4()), "title": "Generar PRs de actualización con pruebas de regresión", "completed": False, "estimate_timer": 25},
                ],
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Benchmarking de observabilidad APM: Datadog vs Sentry vs Grafana Tempo",
                "notes": "Comparativa de soluciones de telemetría distribuida para monitorizar trazas de endpoints GraphQL y tiempos de render en clientes web.",
                "category": "DevOps",
                "priorityLevel": 3,
                "estimateTimer": 75,
                "status": "Backlog",
                "estimated_start_date": None,
                "deadline": FAR_FUTURE,
                "tags": [{"name": "Observability", "color": "#008767"}, {"name": "Cloud", "color": "#059669"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Evaluar SDK de OpenTelemetry en FastAPI y Apollo Client", "completed": False, "estimate_timer": 25},
                    {"id": str(uuid.uuid4()), "title": "Comparar estructura de costos por millón de spans procesados", "completed": False, "estimate_timer": 25},
                    {"id": str(uuid.uuid4()), "title": "Prototipar dashboard básico de p95/p99 en Grafana local", "completed": False, "estimate_timer": 25},
                ],
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Borrador de guía de onboarding y mejores prácticas de arquitectura para nuevos devs",
                "notes": "Redactar documentación concisa para acelerar el ramp-up de nuevos desarrolladores de semanas a menos de 2 días hábiles.",
                "category": "Documentation",
                "priorityLevel": 4,
                "estimateTimer": 45,
                "status": "Backlog",
                "estimated_start_date": None,
                "deadline": FAR_FUTURE,
                "tags": [{"name": "Docs", "color": "#10b981"}, {"name": "Team", "color": "#047857"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Documentar script de setup docker-compose de 1 comando", "completed": False, "estimate_timer": 20},
                    {"id": str(uuid.uuid4()), "title": "Especificar guía de Conventional Commits y ciclo de vida de PRs", "completed": False, "estimate_timer": 15},
                    {"id": str(uuid.uuid4()), "title": "Revisar claridad de diagramas de arquitectura del sistema", "completed": False, "estimate_timer": 10},
                ],
            },
        ]

        # 5 Tareas de Hoy (Today)
        today_tasks = [
            {
                "id": str(uuid.uuid4()),
                "title": "Optimización de consultas lentas e índices compuestos en PostgreSQL",
                "notes": "Analizar pg_stat_statements para identificar las 3 queries más pesadas en la tabla Task y añadir índices optimizados para filtros de rango temporal.",
                "category": "Database",
                "priorityLevel": 1,
                "estimateTimer": 90,
                "status": "InProgress",
                "estimated_start_date": TODAY,
                "deadline": TODAY_END,
                "tags": [{"name": "Performance", "color": "#008767"}, {"name": "SQL", "color": "#059669"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Extraer reporte de consultas con tiempo de ejecución > 200ms", "completed": True, "completed_at": "2026-09-28T09:30:00Z", "estimate_timer": 20},
                    {"id": str(uuid.uuid4()), "title": "Ejecutar EXPLAIN ANALYZE en la consulta de GetTasksPaginated", "completed": True, "completed_at": "2026-09-28T10:00:00Z", "estimate_timer": 25},
                    {"id": str(uuid.uuid4()), "title": "Crear índice compuesto index_task_user_deadline_status", "completed": False, "estimate_timer": 25},
                    {"id": str(uuid.uuid4()), "title": "Validar reducción de tiempo de respuesta a < 50ms en Staging", "completed": False, "estimate_timer": 20},
                ],
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Implementar validación estricta con esquemas Zod en endpoints de Auth",
                "notes": "Reforzar validaciones de contraseña, sanitización de caracteres y límites de tasa en las mutaciones de Login y Registro de usuario.",
                "category": "Security",
                "priorityLevel": 1,
                "estimateTimer": 60,
                "status": "InProgress",
                "estimated_start_date": TODAY + timedelta(hours=2),
                "deadline": TODAY_END,
                "tags": [{"name": "Security", "color": "#10b981"}, {"name": "Backend", "color": "#047857"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Definir schema Zod con regex de complejidad de contraseñas", "completed": True, "completed_at": "2026-09-28T11:30:00Z", "estimate_timer": 15},
                    {"id": str(uuid.uuid4()), "title": "Conectar middleware de parseo seguro y mapeo de errores 422", "completed": False, "estimate_timer": 25},
                    {"id": str(uuid.uuid4()), "title": "Escribir tests unitarios para verificar rechazo de inyecciones", "completed": False, "estimate_timer": 20},
                ],
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Sincronización bidireccional de eventos con Webhooks de Google Calendar",
                "notes": "Asegurar que cuando un usuario modifique un evento en Google Calendar, el cambio se propague de inmediato sin desincronizaciones.",
                "category": "Integrations",
                "priorityLevel": 2,
                "estimateTimer": 80,
                "status": "Todo",
                "estimated_start_date": TODAY + timedelta(hours=4),
                "deadline": TODAY_END + timedelta(hours=1),
                "tags": [{"name": "Google", "color": "#008767"}, {"name": "Sync", "color": "#059669"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Configurar endpoint de webhook para cabeceras X-Goog-Channel-ID", "completed": False, "estimate_timer": 25},
                    {"id": str(uuid.uuid4()), "title": "Manejar tokens de sincronización incremental (syncToken)", "completed": False, "estimate_timer": 30},
                    {"id": str(uuid.uuid4()), "title": "Emitir actualización por Socket.IO al cliente activo", "completed": False, "estimate_timer": 25},
                ],
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Refactorizar diseño y tokens de paleta esmeralda en componentes UI",
                "notes": "Verificar consistencia visual con la marca Focusly SaaS (#008767) en modales, badges y controles de la aplicación.",
                "category": "Frontend",
                "priorityLevel": 2,
                "estimateTimer": 50,
                "status": "Todo",
                "estimated_start_date": TODAY + timedelta(hours=6),
                "deadline": TODAY_END + timedelta(hours=2),
                "tags": [{"name": "UI/UX", "color": "#10b981"}, {"name": "Design", "color": "#047857"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Auditar estilos en componentes compartidos y modales", "completed": True, "completed_at": "2026-09-28T14:00:00Z", "estimate_timer": 15},
                    {"id": str(uuid.uuid4()), "title": "Revisar contraste accesible WCAG en modo claro y oscuro", "completed": False, "estimate_timer": 20},
                    {"id": str(uuid.uuid4()), "title": "Ejecutar build de producción y validar ausencia de errores", "completed": False, "estimate_timer": 15},
                ],
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Daily de sprint y revisión de burn-down chart con equipo de producto",
                "notes": "Reunión de alineación diaria de 45 minutos para resolver dependencias críticas y ajustar entregables de la versión 2.4.",
                "category": "Meeting",
                "priorityLevel": 3,
                "estimateTimer": 45,
                "status": "Todo",
                "estimated_start_date": TODAY + timedelta(hours=7),
                "deadline": TODAY + timedelta(hours=7, minutes=45),
                "tags": [{"name": "Agile", "color": "#008767"}, {"name": "Planning", "color": "#059669"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Revisar velocity del equipo en las últimas dos iteraciones", "completed": False, "estimate_timer": 15},
                    {"id": str(uuid.uuid4()), "title": "Identificar bloqueos técnicos en integraciones externas", "completed": False, "estimate_timer": 20},
                    {"id": str(uuid.uuid4()), "title": "Priorizar backlog de soporte para el cierre de mes", "completed": False, "estimate_timer": 10},
                ],
            },
        ]

        # 4 Tareas de Próximos (Upcoming)
        upcoming_tasks = [
            {
                "id": str(uuid.uuid4()),
                "title": "Diseñar suite de pruebas de carga y estrés con k6 para GraphQL",
                "notes": "Simular concurrencia masiva de 500 usuarios en operaciones complejas de lectura y escritura para determinar umbrales de saturación.",
                "category": "QA",
                "priorityLevel": 2,
                "estimateTimer": 120,
                "status": "Scheduled",
                "estimated_start_date": TOMORROW,
                "deadline": TOMORROW + timedelta(hours=8),
                "tags": [{"name": "Testing", "color": "#008767"}, {"name": "Performance", "color": "#059669"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Escribir script k6 con escenarios de ramp-up progresivo", "completed": False, "estimate_timer": 40},
                    {"id": str(uuid.uuid4()), "title": "Configurar alertas automáticas si p95 supera 250ms", "completed": False, "estimate_timer": 30},
                    {"id": str(uuid.uuid4()), "title": "Analizar uso de CPU y pool de conexiones en PostgreSQL", "completed": False, "estimate_timer": 50},
                ],
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Configurar políticas de ciclo de vida y transición a AWS S3 Glacier",
                "notes": "Automatizar la migración de archivos adjuntos antiguos y reportes generados hacia almacenamiento frío para recortar 65% de costes cloud.",
                "category": "DevOps",
                "priorityLevel": 2,
                "estimateTimer": 60,
                "status": "Scheduled",
                "estimated_start_date": IN_2_DAYS,
                "deadline": IN_2_DAYS + timedelta(hours=6),
                "tags": [{"name": "AWS", "color": "#10b981"}, {"name": "FinOps", "color": "#047857"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Definir regla de transición a Glacier Instant Retrieval a 30 días", "completed": False, "estimate_timer": 20},
                    {"id": str(uuid.uuid4()), "title": "Configurar expiración permanente de temporales tras 90 días", "completed": False, "estimate_timer": 20},
                    {"id": str(uuid.uuid4()), "title": "Verificar permisos IAM del bucket de avatars y backups", "completed": False, "estimate_timer": 20},
                ],
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Implementación de compresión Brotli y headers de cache HTTP/2 en CDN",
                "notes": "Configurar compresión de alto ratio en Cloudflare y directivas Cache-Control para assets estáticos con hashing único.",
                "category": "Performance",
                "priorityLevel": 3,
                "estimateTimer": 45,
                "status": "Todo",
                "estimated_start_date": IN_3_DAYS,
                "deadline": IN_3_DAYS + timedelta(hours=5),
                "tags": [{"name": "CDN", "color": "#008767"}, {"name": "Frontend", "color": "#059669"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Activar compresión Brotli nivel 6 en la zona DNS de Cloudflare", "completed": False, "estimate_timer": 15},
                    {"id": str(uuid.uuid4()), "title": "Asegurar cabecera Cache-Control: max-age=31536000, immutable", "completed": False, "estimate_timer": 15},
                    {"id": str(uuid.uuid4()), "title": "Medir mejora en First Contentful Paint (FCP) con Lighthouse", "completed": False, "estimate_timer": 15},
                ],
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Renovación de certificados TLS y verificación de cabeceras HSTS con SSL Labs",
                "notes": "Auditoría anual de seguridad de transporte de red para asegurar calificación A+ y cumplimiento estricto de cifrado TLS 1.3.",
                "category": "Security",
                "priorityLevel": 1,
                "estimateTimer": 40,
                "status": "Todo",
                "estimated_start_date": IN_5_DAYS,
                "deadline": IN_5_DAYS + timedelta(hours=4),
                "tags": [{"name": "Security", "color": "#10b981"}, {"name": "Infra", "color": "#047857"}],
                "subtasks": [
                    {"id": str(uuid.uuid4()), "title": "Validar rotación automática mediante cert-manager de Kubernetes", "completed": False, "estimate_timer": 15},
                    {"id": str(uuid.uuid4()), "title": "Configurar Strict-Transport-Security con includeSubDomains y preload", "completed": False, "estimate_timer": 15},
                    {"id": str(uuid.uuid4()), "title": "Ejecutar análisis en SSL Labs y documentar reporte de conformidad", "completed": False, "estimate_timer": 10},
                ],
            },
        ]

        all_general_task_definitions = inbox_tasks + today_tasks + upcoming_tasks
        print(f"Total general tasks to insert: {len(all_general_task_definitions)} (Inbox: {len(inbox_tasks)}, Today: {len(today_tasks)}, Upcoming: {len(upcoming_tasks)})")

        for user_id in [USER_ID_1, USER_ID_2]:
            for t_def in all_general_task_definitions:
                task_id = str(uuid.uuid4()) if user_id == USER_ID_2 else t_def["id"]
                subtasks_with_ids = [
                    {
                        "id": str(uuid.uuid4()),
                        "title": s["title"],
                        "completed": s.get("completed", False),
                        "completed_at": s.get("completed_at"),
                        "estimate_timer": s.get("estimate_timer", 20)
                    }
                    for s in t_def["subtasks"]
                ]
                new_task = Task(
                    id=task_id,
                    userId=user_id,
                    title=t_def["title"],
                    notesEncrypted=t_def["notes"],
                    estimateTimer=t_def["estimateTimer"],
                    priorityLevel=t_def["priorityLevel"],
                    category=t_def["category"],
                    status=t_def["status"],
                    estimated_start_date=t_def["estimated_start_date"],
                    estimated_end_date=t_def["deadline"],
                    deadline=t_def["deadline"],
                    subtasks=subtasks_with_ids,
                    tags=t_def["tags"],
                    task_type="PlatformTask",
                    source="platform",
                    is_owner=True,
                    createdAt=datetime.now(),
                    updatedAt=datetime.now()
                )
                session.add(new_task)

        # ----------------------------------------------------------------------
        # 3. TAREAS DE PROYECTO (PROJECT TASKS) CON SUBTAREAS Y WORKSPACES
        # ----------------------------------------------------------------------
        print("\n=== Creando Tareas de Proyecto con subtareas y vinculación a Workspaces ===")

        project_tasks_defs = [
            # Proyecto Playwright
            {
                "projectName": "Automatización de Tests End-to-End con Playwright",
                "workspaceId": playwright_ws_id,
                "title": "Configuración base de Playwright con Page Object Model y Fixtures",
                "notes": "Crear la estructura modular de tests E2E y configurar el pipeline local para ejecución paralela en Chromium, Firefox y WebKit.",
                "status": "InProgress",
                "priorityLevel": 1,
                "estimateTimer": 90,
                "deadline": TODAY_END,
                "tags": [{"name": "E2E", "color": "#008767"}, {"name": "Playwright", "color": "#059669"}],
                "subtasks": [
                    {"title": "Configurar playwright.config.ts con retries y artifacts de video", "completed": True, "completed_at": "2026-09-28T10:00:00Z", "estimate_timer": 30},
                    {"title": "Implementar fixture de autenticación headless con storageState", "completed": True, "completed_at": "2026-09-28T10:45:00Z", "estimate_timer": 30},
                    {"title": "Escribir primer test de navegación y verificación de login exitoso", "completed": False, "estimate_timer": 30},
                ],
            },
            {
                "projectName": "Automatización de Tests End-to-End con Playwright",
                "workspaceId": playwright_ws_id,
                "title": "Pruebas E2E del flujo crítico de Creación y Edición de Proyectos",
                "notes": "Automatizar la validación de formularios de creación de proyectos, selección de colores, carpetas y persistencia de tableros.",
                "status": "Todo",
                "priorityLevel": 2,
                "estimateTimer": 75,
                "deadline": TOMORROW,
                "tags": [{"name": "QA", "color": "#10b981"}, {"name": "Automated", "color": "#047857"}],
                "subtasks": [
                    {"title": "Test de modal de nuevo proyecto y selector de color", "completed": False, "estimate_timer": 25},
                    {"title": "Test de drag-and-drop de tarjetas en el tablero kanban", "completed": False, "estimate_timer": 25},
                    {"title": "Test de recarga de página confirmando consistencia del estado", "completed": False, "estimate_timer": 25},
                ],
            },
            # Proyecto Redis
            {
                "projectName": "Sistema de Cache Distribuido con Redis Cluster",
                "workspaceId": redis_ws_id,
                "title": "Implementación del patrón Cache-Aside con invalidación reactiva",
                "notes": "Integrar decorador de caching en el resolver de GetTasksPaginated para servir respuestas en menos de 5ms.",
                "status": "InProgress",
                "priorityLevel": 1,
                "estimateTimer": 120,
                "deadline": TODAY_END,
                "tags": [{"name": "Redis", "color": "#008767"}, {"name": "Backend", "color": "#059669"}],
                "subtasks": [
                    {"title": "Diseñar esquema de claves con hash seguro de variables GraphQL", "completed": True, "completed_at": "2026-09-28T12:00:00Z", "estimate_timer": 30},
                    {"title": "Conectar hooks de invalidación en mutaciones createTask y updateTask", "completed": False, "estimate_timer": 45},
                    {"title": "Manejo resiliente de fallback a base de datos si Redis no responde", "completed": False, "estimate_timer": 45},
                ],
            },
            {
                "projectName": "Sistema de Cache Distribuido con Redis Cluster",
                "workspaceId": redis_ws_id,
                "title": "Pruebas de tolerancia a fallos y failover automático en Redis Sentinel",
                "notes": "Simular caída de nodos primarios y verificar que la elección del nuevo máster se complete en menos de 2 segundos sin pérdida de datos.",
                "status": "Backlog",
                "priorityLevel": 3,
                "estimateTimer": 60,
                "deadline": FAR_FUTURE,
                "tags": [{"name": "Cluster", "color": "#10b981"}, {"name": "Reliability", "color": "#047857"}],
                "subtasks": [
                    {"title": "Levantar ambiente de 3 réplicas con Redis Sentinel en Docker", "completed": False, "estimate_timer": 20},
                    {"title": "Simular corte abrupto mediante docker kill en el nodo master", "completed": False, "estimate_timer": 20},
                    {"title": "Medir tiempo exacto de reconexión del backend FastAPI", "completed": False, "estimate_timer": 20},
                ],
            },
            # Proyecto Onboarding
            {
                "projectName": "Rediseño de la Experiencia de Onboarding",
                "workspaceId": onboarding_ws_id,
                "title": "Componente interactivo del Wizard de bienvenida con Lumina AI",
                "notes": "Construir las vistas del wizard de onboarding con micro-interacciones fluidas y asistencia guiada en tiempo real.",
                "status": "Review",
                "priorityLevel": 2,
                "estimateTimer": 60,
                "deadline": TODAY_END,
                "tags": [{"name": "Onboarding", "color": "#008767"}, {"name": "Lumina", "color": "#059669"}],
                "subtasks": [
                    {"title": "Diseñar los 3 pasos interactivos con Framer Motion", "completed": True, "completed_at": "2026-09-28T13:00:00Z", "estimate_timer": 20},
                    {"title": "Integrar saludo y sugerencias contextuales con Lumina AI", "completed": True, "completed_at": "2026-09-28T14:15:00Z", "estimate_timer": 25},
                    {"title": "Añadir eventos de telemetría en PostHog para medir abandono", "completed": False, "estimate_timer": 15},
                ],
            },
            # Proyecto SQL
            {
                "projectName": "Curso y Prácticas de SQL",
                "workspaceId": sql_ws_id,
                "title": "Taller práctico: Window Functions avanzadas (LAG, LEAD, NTILE)",
                "notes": "Ejercicios prácticos con datasets reales de ventas y productividad para dominar particiones temporales.",
                "status": "InProgress",
                "priorityLevel": 2,
                "estimateTimer": 90,
                "deadline": TODAY_END,
                "tags": [{"name": "SQL", "color": "#008767"}, {"name": "Learning", "color": "#059669"}],
                "subtasks": [
                    {"title": "Resolver ejercicio de cálculo de diferencia interdiaria con LAG()", "completed": True, "completed_at": "2026-09-28T11:00:00Z", "estimate_timer": 30},
                    {"title": "Agrupar usuarios en cuartiles de productividad con NTILE(4)", "completed": False, "estimate_timer": 30},
                    {"title": "Guardar queries modelo y notas en el workspace de SQL", "completed": False, "estimate_timer": 30},
                ],
            },
            # Proyecto Nutrición
            {
                "projectName": "Notas de Nutrición",
                "workspaceId": nutricion_ws_id,
                "title": "Calculadora de balance de macronutrientes y gasto energético basal",
                "notes": "Plantilla interactiva para aplicar fórmulas de Harris-Benedict y Mifflin-St Jeor en planes de entrenamiento.",
                "status": "Todo",
                "priorityLevel": 2,
                "estimateTimer": 70,
                "deadline": TOMORROW,
                "tags": [{"name": "Nutrición", "color": "#10b981"}, {"name": "Salud", "color": "#047857"}],
                "subtasks": [
                    {"title": "Programar hoja de cálculo con factores de actividad física", "completed": True, "completed_at": "2026-09-28T09:00:00Z", "estimate_timer": 20},
                    {"title": "Establecer rangos de déficit calórico sostenible (15-20%)", "completed": False, "estimate_timer": 25},
                    {"title": "Elaborar menú ejemplo de 2,200 kcal con 150g de proteína", "completed": False, "estimate_timer": 25},
                ],
            },
            # Proyecto Gym
            {
                "projectName": "Gym Project",
                "workspaceId": "f879d1bc-9432-455c-87a3-77aa5bae8cf9",
                "title": "Planificación de mesociclo de hipertrofia y progresión de cargas RPE",
                "notes": "Estructurar la rutina semanal de 4 días (Torso/Pierna) con progresión doble y control de volumen por grupo muscular.",
                "status": "InProgress",
                "priorityLevel": 2,
                "estimateTimer": 60,
                "deadline": TODAY_END,
                "tags": [{"name": "Fitness", "color": "#008767"}, {"name": "Training", "color": "#059669"}],
                "subtasks": [
                    {"title": "Definir ejercicios principales y rangos de repeticiones (6-8 y 10-12)", "completed": True, "completed_at": "2026-09-28T08:00:00Z", "estimate_timer": 20},
                    {"title": "Establecer escala de esfuerzo percibido (RPE 7-9) por serie efectiva", "completed": False, "estimate_timer": 20},
                    {"title": "Configurar semana de descarga (deload) planificada en la semana 6", "completed": False, "estimate_timer": 20},
                ],
            }
        ]

        print(f"Total project tasks to insert: {len(project_tasks_defs)}")

        for p_def in project_tasks_defs:
            proj = projects.get(p_def["projectName"])
            proj_id = proj.id if proj else None

            subtasks_with_ids = [
                {
                    "id": str(uuid.uuid4()),
                    "title": s["title"],
                    "completed": s.get("completed", False),
                    "completed_at": s.get("completed_at"),
                    "estimate_timer": s.get("estimate_timer", 20)
                }
                for s in p_def["subtasks"]
            ]

            proj_task = Task(
                id=str(uuid.uuid4()),
                userId=USER_ID_1,
                title=p_def["title"],
                notesEncrypted=p_def["notes"],
                estimateTimer=p_def["estimateTimer"],
                priorityLevel=p_def["priorityLevel"],
                category="Project",
                status=p_def["status"],
                estimated_start_date=TODAY if p_def["status"] in ["InProgress", "Todo"] else None,
                estimated_end_date=p_def["deadline"],
                deadline=p_def["deadline"],
                subtasks=subtasks_with_ids,
                tags=p_def["tags"],
                projectId=proj_id,
                workspaceId=p_def.get("workspaceId"),
                task_type="PlatformTask",
                source="platform",
                is_owner=True,
                createdAt=datetime.now(),
                updatedAt=datetime.now()
            )
            session.add(proj_task)

        # Confirmar todos los cambios
        await session.commit()
        print("\n🎉 ¡ÉXITO! Todas las tareas generales, tareas de proyecto y contextos de workspaces han sido creados y sincronizados en la base de datos.")

if __name__ == "__main__":
    asyncio.run(main())
