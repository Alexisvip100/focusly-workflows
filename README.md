# Focusly Backend

Este es el backend del proyecto **Focusly**, desarrollado en Python utilizando **FastAPI**, **GraphQL (Strawberry)**, **Socket.IO** y **SQLAlchemy** con soporte asíncrono para **PostgreSQL**.

---

## 📋 Prerrequisitos

Antes de comenzar, asegúrate de tener instalado lo siguiente en tu sistema:

- **Python 3.11 o superior**
- **PostgreSQL** (si ejecutas de manera local) o **Docker & Docker Compose** (para ejecutar en contenedores)
- Administrador de paquetes de Python (`pip`)

---

## ⚙️ Configuración del Entorno

1. Copia el archivo de plantilla `.env.example` para crear tu archivo `.env`:
   ```bash
   cp .env.example .env
   ```

2. Abre el archivo `.env` y rellena las variables de entorno con tus credenciales:
   - **`DATABASE_URL`**: URL de conexión a tu base de datos PostgreSQL usando el driver `asyncpg` (ej. `postgresql+asyncpg://usuario:contraseña@localhost:5432/focusly`).
   - **`JWT_SECRET`**: Clave secreta para la firma y verificación de tokens JWT de sesión.
   - **`GOOGLE_CLIENT_ID`** y **`GOOGLE_CLIENT_SECRET`**: Credenciales de Google OAuth para la sincronización con Google Calendar e inicio de sesión.
   - **`GOOGLE_GENERATIVE_AI_API_KEY`**: API Key para las sugerencias e integraciones de IA (Gemini).
   - **`RESEND_API_KEY`**: Token de Resend para el envío de correos electrónicos.

---

## 🚀 Cómo Ejecutar el Proyecto

Tienes dos opciones principales para ejecutar el backend de Focusly y sus servicios (base de datos y caché):

### 🐳 ¿Por qué Docker?

El backend depende de dos servicios externos además de la app en sí: **PostgreSQL** (base de datos principal) y **Redis** (caché para sesiones, resultados de queries y rate limiting). Levantar y coordinar manualmente estas tres piezas (versiones correctas, puertos, variables de entorno cruzadas entre contenedores) es propenso a errores y distinto en cada máquina.

`docker-compose.yml` empaqueta los tres servicios (`focusly-web`, `focusly-postgres`, `focusly-redis`) con sus versiones fijas, red interna y variables ya cableadas entre sí, de forma que **cualquiera pueda levantar un entorno idéntico con un solo comando**, sin instalar Postgres o Redis en su máquina ni preocuparse por conflictos de versiones. Es el modo recomendado para incorporarse rápido al proyecto o para probar en un entorno aislado y reproducible (el mismo que usa CI/despliegue). La ejecución local sigue siendo útil para desarrollo activo, cuando quieres iterar con `--reload` directamente sobre tu Python local sin la capa extra de contenedores.

### Opción 1: Ejecución Local (Recomendado para desarrollo activo)

1. **Crear un entorno virtual de Python**:
   ```bash
   python3 -m venv .venv
   ```

2. **Activar el entorno virtual**:
   - En macOS y Linux:
     ```bash
     source .venv/bin/activate
     ```
   - En Windows:
     ```bash
     .venv\Scripts\activate
     ```

3. **Instalar las dependencias**:
   ```bash
   pip install -r requirements.txt
   ```
   *(Si usas `uv`, puedes hacer `uv sync` en su lugar; agrega `--group dev` para incluir `ruff` y `mypy`).*

4. **Iniciar PostgreSQL y Redis localmente**:
   Ambos servicios deben estar corriendo y accesibles según lo definido en tu `.env` (`DATABASE_URL` y `REDIS_URL`). Si usas Homebrew en macOS:
   ```bash
   brew services start postgresql@17
   brew services start redis
   ```
   *(Asegúrate de que la base de datos `focusly` exista en tu servidor local de Postgres. Redis no requiere configuración adicional).*

5. **Inicializar las tablas de la base de datos**:
   Corre el script de inicialización para crear la estructura de tablas:
   ```bash
   python init_db.py
   ```

6. **Ejecutar el servidor de desarrollo**:
   ```bash
   uvicorn app.main:app --reload --port 3000
   ```
   *El flag `--reload` permite que el servidor se reinicie automáticamente cada vez que realices cambios en el código.*

---

### Opción 2: Ejecución con Docker (Recomendado para un entorno aislado y reproducible)

El proyecto incluye un `Dockerfile` y un archivo `docker-compose.yml` que empaquetan la aplicación FastAPI junto con **PostgreSQL** y **Redis**, ya conectados entre sí por variables de entorno.

1. **Asegúrate de tener Docker Desktop (o el daemon de Docker) abierto y ejecutándose** en tu máquina.

2. **Compilar y levantar los contenedores**:
   ```bash
   docker-compose up --build
   ```
   *(Esto iniciará tres contenedores en paralelo: `focusly-postgres` (base de datos), `focusly-redis` (caché) y `focusly-web` (backend FastAPI, expuesto en el puerto `3000`)).*

3. **Inicializar las tablas dentro de Docker (Solo la primera vez)**:
   Con los contenedores corriendo en segundo plano o en otra terminal, inicializa la estructura de tablas en la base de datos de Docker ejecutando:
   ```bash
   docker exec -it focusly-web python init_db.py
   ```

4. **Ver logs del backend** (opcional, útil si corriste `docker-compose up` en modo detached con `-d`):
   ```bash
   docker-compose logs -f web
   ```

5. **Detener los contenedores**:
   ```bash
   docker-compose down
   ```
   *(Agrega `-v` si además quieres borrar el volumen `pgdata` y reiniciar la base de datos desde cero).*

---

## 🧹 Linting y Type Checking

El proyecto usa **`ruff`** (linter/formatter) y **`mypy`** (type checker) como dependencias de desarrollo, declaradas en el grupo `dev` de `pyproject.toml`.

1. **Instalar las dependencias de desarrollo** (incluye `ruff` y `mypy`):
   ```bash
   uv sync --group dev
   ```

2. **Ejecutar mypy** (revisa tipado estático sobre todo el paquete `app`):
   ```bash
   uv run mypy app
   ```
   La configuración vive en `[tool.mypy]` dentro de `pyproject.toml`:
   - `explicit_package_bases = true` y `mypy_path = "."` le indican a mypy cómo resolver los módulos a partir de la raíz del repo (necesario porque no todos los subpaquetes de `app/modules` tienen `__init__.py`).
   - El bloque `[[tool.mypy.overrides]]` ignora los imports sin stubs de `socketio` y `google` (genai), que no publican tipado.

3. **Ejecutar ruff** (lint):
   ```bash
   uv run ruff check app
   ```
   Y para formatear automáticamente:
   ```bash
   uv run ruff format app
   ```
   Las reglas seleccionadas/ignoradas están en `[tool.ruff.lint]` dentro de `pyproject.toml`.

   > Si ya tienes el entorno virtual activado (`source .venv/bin/activate`) y las dependencias instaladas, también puedes invocar directamente `mypy app` y `ruff check app` sin el prefijo `uv run`.

---

## 🔌 Endpoints y Servicios Disponibles

Una vez que el servidor esté corriendo (generalmente en `http://localhost:3000`), podrás acceder a los siguientes servicios:

* **Página principal / Check de Salud**: `http://localhost:3000/` (retorna `{"status": "ok", ...}`)
* **GraphQL Playground (Strawberry)**: `http://localhost:3000/graphql`
  - Puedes probar queries y mutations de GraphQL de forma interactiva en tu navegador.
* **Socket.IO (Eventos en Tiempo Real)**: `http://localhost:3000` en la ruta `/socket.io`
  - Conexión websocket para actualizaciones de tareas y notificaciones en tiempo real.
* **Rutas REST (FastAPI)**:
  - Auth: `/auth` (manejo de login y registro)
  - Users: `/users`
  - Google Calendar: `/google_calendar`
  - Time Blocks: `/time_blocks`
