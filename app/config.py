import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://alexis@localhost:5432/focusly")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "default_secret_key_change_me_in_production")
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "postmessage")
    GOOGLE_GENERATIVE_AI_API_KEY: str = os.getenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "http://localhost:3000")
    FIREBASE_PROJECT_ID: str = os.getenv("FIREBASE_PROJECT_ID", "focusly-a2132")
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    IS_PRODUCTION: bool = os.getenv("ENV", "development") == "production"

settings = Settings()
