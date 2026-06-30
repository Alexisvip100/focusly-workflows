import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Read and normalize FOCUSLY_AI_URL at module level
_raw_ai_url = os.getenv("FOCUSLY_AI_URL", "http://localhost:8001").strip().strip('"').strip("'")
if not (_raw_ai_url.startswith("http://") or _raw_ai_url.startswith("https://")):
    if any(h in _raw_ai_url for h in ["localhost", "127.0.0.1", "host.docker.internal"]):
        _normalized_ai_url = f"http://{_raw_ai_url}"
    else:
        _normalized_ai_url = f"https://{_raw_ai_url}"
else:
    _normalized_ai_url = _raw_ai_url

class Settings:
    _raw_db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://alexis@localhost:5432/focusly").strip()
    DATABASE_URL: str = (
        _raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if _raw_db_url.startswith("postgresql://")
        else _raw_db_url
    )
    JWT_SECRET: str = os.getenv("JWT_SECRET", "default_secret_key_change_me_in_production")
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "postmessage")
    GOOGLE_GENERATIVE_AI_API_KEY: str = os.getenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "http://localhost:3000")
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    IS_PRODUCTION: bool = os.getenv("ENV", "development") == "production"
    FOCUSLY_AI_URL: str = _normalized_ai_url

settings = Settings()
