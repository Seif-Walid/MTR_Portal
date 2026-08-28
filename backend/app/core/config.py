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
    # The portal frontend (5173) plus the public marketing website, which reads
    # the /api/public/* Hall of Fame endpoint. The website's production origins
    # are included so a browser-side fetch is allowed; server-side fetches from
    # Next.js aren't subject to CORS but cost nothing to permit.
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]
    # The public marketing site reads the /api/public/* Hall of Fame endpoint
    # from the browser. These origins are ALWAYS allowed, unioned in on top of
    # cors_origins — so a deploy-time CORS_ORIGINS override (which sets the
    # portal frontend's own origins and would otherwise drop these) can never
    # break the public site's read. Public, PII-free data only.
    public_site_origins: list[str] = [
        "https://mindtechrobotics.com",
        "https://www.mindtechrobotics.com",
    ]
    frontend_url: str = "http://localhost:5173"

    @property
    def all_cors_origins(self) -> list[str]:
        """cors_origins (possibly overridden per-deploy) unioned with the public
        marketing-site origins, de-duplicated, order preserved."""
        return list(dict.fromkeys([*self.cors_origins, *self.public_site_origins]))

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
    # Container-friendly alternative to the file above: the service-account JSON
    # key, base64-encoded into a single env var (`base64 -w0 key.json`). Used by
    # the Docker/CI deploy so no key file has to be mounted. If both are set the
    # base64 value wins.
    google_sheets_credentials_b64: str = ""
    google_sheets_spreadsheet_id: str = ""
    google_sheets_worksheet: str = "Inventory"
    # Shared secret for the live sheet->DB webhook. The Apps Script bound to the
    # spreadsheet sends it on every edit; empty disables the webhook (404).
    sheets_sync_token: str = ""


settings = Settings()
