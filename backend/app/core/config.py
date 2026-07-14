from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://portal:portal@localhost:5432/portal"
    session_ttl_hours: int = 24 * 7
    session_cookie_name: str = "portal_session"
    cookie_secure: bool = False  # set True behind HTTPS
    upload_dir: Path = BASE_DIR / "uploads"
    max_upload_mb: int = 25
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    frontend_url: str = "http://localhost:5173"

    # Google SSO (optional). Create OAuth credentials in Google Cloud Console
    # and register google_redirect_uri as an authorized redirect URI.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"


settings = Settings()
