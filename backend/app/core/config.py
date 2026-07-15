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

    # Confirmation phrase for the destructive Rebuild-from-Sheets action — the
    # admin must type this exact string to commit. Change it per deployment.
    org_name: str = "Mind-Tech Robotics"
    # Where pre-rebuild DB snapshots (JSON dumps of every managed table,
    # written before truncation) are kept.
    snapshot_dir: Path = BASE_DIR / "snapshots"

    # Google SSO (optional). Create OAuth credentials in Google Cloud Console
    # and register google_redirect_uri as an authorized redirect URI.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"
    # Domain allowlist for Google sign-in: comma-separated, checked against the
    # Workspace `hd` claim, or the email's own domain for personal accounts
    # (Gmail has no `hd`). Empty = no restriction. Set explicitly to lock down
    # to your org's Workspace domain, and add e.g. "gmail.com" to permit
    # personal accounts deliberately rather than by accident.
    google_allowed_domains: str = ""

    @property
    def google_allowed_domains_list(self) -> list[str]:
        return [d.strip().lower() for d in self.google_allowed_domains.split(",") if d.strip()]

    # Google Sheets inventory mirror (optional). The portal is the source of
    # truth; "Sync to Sheets" pushes a read-only snapshot into this spreadsheet.
    # Point google_sheets_credentials_file at a service-account JSON key and
    # share the target spreadsheet with that service account's email.
    google_sheets_credentials_file: str = ""
    google_sheets_spreadsheet_id: str = ""
    google_sheets_worksheet: str = "Inventory"


settings = Settings()
