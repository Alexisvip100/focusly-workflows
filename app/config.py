import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Read and normalize FOCUSLY_AI_URL at module level
_raw_ai_url = (
    os.getenv("FOCUSLY_AI_URL", "http://localhost:8001").strip().strip('"').strip("'")
)
if not (_raw_ai_url.startswith("http://") or _raw_ai_url.startswith("https://")):
    if any(
        h in _raw_ai_url for h in ["localhost", "127.0.0.1", "host.docker.internal"]
    ):
        _normalized_ai_url = f"http://{_raw_ai_url}"
    else:
        _normalized_ai_url = f"https://{_raw_ai_url}"
else:
    _normalized_ai_url = _raw_ai_url


# Not a real credential — a known sentinel value checked against below to
# refuse starting in production without a real JWT_SECRET configured.
_DEFAULT_JWT_SECRET = "default_secret_key_change_me_in_production"  # noqa: S105


class Settings:
    _raw_db_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://alexis@localhost:5432/focusly"
    ).strip()
    DATABASE_URL: str = (
        _raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if _raw_db_url.startswith("postgresql://")
        else _raw_db_url
    )
    JWT_SECRET: str = os.getenv("JWT_SECRET", _DEFAULT_JWT_SECRET)
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "postmessage")
    GOOGLE_GENERATIVE_AI_API_KEY: str = os.getenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "http://localhost:3000")
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    IS_PRODUCTION: bool = os.getenv("ENV", "development") == "production"
    FOCUSLY_AI_URL: str = _normalized_ai_url
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0").strip()
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "http://localhost:9000").strip()
    MINIO_PUBLIC_ENDPOINT: str = os.getenv(
        "MINIO_PUBLIC_ENDPOINT", "http://localhost:9000"
    ).strip()
    MINIO_ROOT_USER: str = os.getenv("MINIO_ROOT_USER", "")
    MINIO_ROOT_PASSWORD: str = os.getenv("MINIO_ROOT_PASSWORD", "")
    MINIO_BUCKET_AVATARS: str = os.getenv("MINIO_BUCKET_AVATARS", "avatars")


settings = Settings()

# A known, source-visible JWT secret lets anyone forge valid access/refresh
# tokens for any account — fail startup outright in production rather than
# quietly running with it, instead of only ever mattering the one time it's
# actually exploited.
if settings.IS_PRODUCTION and settings.JWT_SECRET == _DEFAULT_JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET is not set. Refusing to start in production with the "
        "default secret — set a real JWT_SECRET in the environment."
    )
