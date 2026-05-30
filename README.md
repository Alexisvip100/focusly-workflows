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

Tienes dos opciones principales para ejecutar el backend de Focusly:

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

4. **Ejecutar el servidor de desarrollo**:
   ```bash
   uvicorn app.main:app --reload --port 3000
   ```
   *El flag `--reload` permite que el servidor se reinicie automáticamente cada vez que realices cambios en el código.*

---

### Opción 2: Ejecución con Docker (Recomendado para un entorno aislado)

El proyecto incluye un `Dockerfile` y un archivo `docker-compose.yml` que configuran la aplicación.

1. **Compilar y levantar el contenedor**:
   ```bash
   docker-compose up --build
   ```
   *Nota: Por defecto, la configuración de Docker Compose asume que tu base de datos PostgreSQL está corriendo en el host local y accede mediante `host.docker.internal`.*

2. **Detener los contenedores**:
   ```bash
   docker-compose down
   ```

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
