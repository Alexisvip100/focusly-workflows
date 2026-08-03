# Focusly Backend

Este es el backend del proyecto **Focusly**, desarrollado en Python utilizando **FastAPI**, **GraphQL (Strawberry)**, **Socket.IO**, **SQLAlchemy** con soporte asíncrono para **PostgreSQL**, y estructurado bajo una arquitectura **Domain-Driven Design (DDD)**.

---

## 🏗️ Arquitectura del Proyecto (DDD)

El código en `app/modules/` se organiza en **Contextos Delimitados (Bounded Contexts)** estructurados en cuatro capas explícitas:

```text
app/modules/<bounded_context>/
├── domain/                      # 🧱 Entidades y Reglas de Negocio puras (Task, User, Workspace...)
│   └── entities/
├── application/                 # ⚙️ Servicios de Aplicación y Casos de Uso
│   └── services/
├── infrastructure/              # 🔌 Implementaciones Técnicas (Repositorios SQLAlchemy, Redis, APIs...)
│   └── persistence/
└── presentation/                # 🌐 Interfaces y Puntos de Entrada
    ├── graphql/                 # Resolvers, Queries y Mutations de Strawberry
    └── rest/                    # Routers HTTP de FastAPI
```

---

## 🛠️ Comandos del Proyecto (`Makefile`)

El proyecto incluye un `Makefile` para simplificar las tareas de desarrollo, formateo, pruebas e infraestructura:

| Comando | Descripción |
| :--- | :--- |
| `make help` | Muestra el menú de ayuda con todos los comandos disponibles. |
| `make start_dependencies` | Inicia contenedores PostgreSQL y Redis en segundo plano (`docker compose up -d db redis`). |
| `make stop_dependencies` | Detiene los contenedores de PostgreSQL y Redis (`docker compose down`). |
| `make dev` | Inicia el servidor de desarrollo FastAPI con recarga en vivo (`uvicorn --reload`). |
| `make compile` | Verifica la compilación estática de tipos con Mypy (`uv run mypy app`). |
| `make format` | Formatea el código y aplica auto-correcciones con Ruff. |
| `make lint` | Revisa el estilo de código e inconsistencias de tipos sin modificar archivos. |
| `make test` | Ejecuta la suite completa de pruebas unitarias con Pytest. |
| `make test_only FILE=<test>` | Ejecuta un archivo de prueba específico (ej. `make test_only FILE=tests/test_scheduler.py`). |
| `make pre-commit` | Ejecuta todas las validaciones de git pre-commit en los archivos. |

---

## 📋 Prerrequisitos

Antes de comenzar, asegúrate de tener instalado lo siguiente en tu sistema:

- **Python 3.11 o superior** (o gestor de paquetes **`uv`**)
- **Docker & Docker Compose** (para ejecutar dependencias en contenedores)
- Administrador de paquetes de Python (`uv` o `pip`)

---

## ⚙️ Configuración del Entorno

1. Copia el archivo de plantilla `.env.example` para crear tu archivo `.env`:
   ```bash
   cp .env.example .env
   ```

2. Abre el archivo `.env` y rellena las variables de entorno con tus credenciales:
   - **`DATABASE_URL`**: URL de conexión a PostgreSQL con `asyncpg` (ej. `postgresql+asyncpg://focusly_user:focusly_password@localhost:5432/focusly`).
   - **`JWT_SECRET`**: Clave secreta para firma y verificación de tokens JWT.
   - **`GOOGLE_CLIENT_ID`** y **`GOOGLE_CLIENT_SECRET`**: Credenciales de Google OAuth para Google Calendar.
   - **`GOOGLE_GENERATIVE_AI_API_KEY`**: API Key para integraciones de IA (Gemini).
   - **`RESEND_API_KEY`**: Token de Resend para envío de emails.

---

## 🚀 Cómo Ejecutar el Proyecto

### Opción 1: Con `Makefile` y `uv` (Recomendado para desarrollo)

1. **Instalar dependencias del proyecto**:
   ```bash
   uv sync --group dev
   ```

2. **Iniciar base de datos y Redis**:
   ```bash
   make start_dependencies
   ```

3. **Instalar hooks de `pre-commit`**:
   ```bash
   uv run pre-commit install
   ```

4. **Iniciar el servidor de desarrollo**:
   ```bash
   make dev
   ```

---

### Opción 2: Con Docker Compose Completo

Si deseas levantar todo el entorno (base de datos, caché y aplicación) dentro de contenedores:

```bash
docker compose up --build
```

Para detener los servicios:
```bash
make stop_dependencies
```

---

## 🧪 Pruebas Automatizadas

Las pruebas automatizadas se encuentran en la carpeta `tests/` y están impulsadas por **`pytest`**:

```bash
# Ejecutar todas las pruebas
make test

# Ejecutar una prueba específica por archivo
make test_only FILE=tests/test_scheduler.py

# Ejecutar una prueba específica por nombre o patrón
make test_only K=test_schedule_single_task_success
```

---

## 🧹 Calidad de Código (Linting, Formatting y Types)

El proyecto utiliza **`ruff`**, **`mypy`** y **`pre-commit`** para mantener un código limpio y seguro:

```bash
# Formatear código automáticamente
make format

# Revisar tipos y linters
make lint

# Correr todas las verificaciones pre-commit
make pre-commit
```

---

## 🔌 Endpoints y Servicios Disponibles

Una vez iniciado el servidor (por defecto en `http://localhost:8000` o `http://localhost:3000`):

* **Check de Salud**: `http://localhost:8000/` (retorna `{"status": "ok", ...}`)
* **GraphQL Playground (Strawberry)**: `http://localhost:8000/graphql`
* **Socket.IO (Tiempo Real)**: `http://localhost:8000` en la ruta `/socket.io`
* **Rutas REST (FastAPI)**:
  - Auth: `/auth`
  - Users: `/users`
  - Google Calendar: `/google_calendar`
  - Time Blocks: `/time_blocks`
