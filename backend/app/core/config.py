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
    # Salt for hashing a website applicant's IP (used only to rate-limit the
    # public join form). Set a random value per deploy.
    application_ip_salt: str = "mtr-applications"

    @property
    def all_cors_origins(self) -> list[str]:
        """cors_origins (possibly overridden per-deploy) unioned with the public
        marketing-site origins, de-duplicated, order preserved."""
        return list(dict.fromkeys([*self.cors_origins, *self.public_site_origins]))

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

    # Outbound mail (see app/core/mail.py). `disabled` | `cloudflare` | `smtp`.
    mail_backend: str = "disabled"
    mail_from_address: str = "portal@mindtechrobotics.com"
    mail_from_name: str = "MindTech Robotics"
    mail_reply_to: str = "support@mindtechrobotics.com"
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""  # needs Email Sending permission
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_ssl: bool = False  # True = implicit TLS (port 465); False = STARTTLS

    @property
    def google_allowed_domains_list(self) -> list[str]:
        return [d.strip().lower() for d in self.google_allowed_domains.split(",") if d.strip()]


settings = Settings()
