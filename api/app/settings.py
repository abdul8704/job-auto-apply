"""Application settings, read from environment variables (or a .env file)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = f"sqlite:///{API_ROOT / 'data' / 'dev.db'}"
    auto_create_tables: bool = True  # dev convenience; use Alembic migrations in Docker / prod

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_expires_minutes: int = 60 * 24 * 7
    # Comma-separated emails allowed to sign up. The very first account can always sign up.
    signup_allowlist: str = ""

    # Background jobs
    redis_url: str = "redis://localhost:6379/0"
    celery_eager: bool = True  # run tasks inline (no Redis needed) for local dev and tests

    # File storage
    storage_backend: str = "local"  # "local" or "s3"
    local_storage_dir: Path = API_ROOT / "data" / "files"
    s3_bucket: str = ""
    aws_region: str = "ap-south-1"

    # LLM
    llm_config_path: Path = API_ROOT / "config" / "llm.yaml"

    # LaTeX
    tectonic_bin: str = "tectonic"
    latex_timeout_seconds: int = 90

    # Job postings: fetched server-side from the link the user gives
    job_fetch_timeout_seconds: float = 20.0
    job_fetch_max_bytes: int = 3_000_000
    job_text_max_chars: int = 30_000

    # Contact finding. Providers run in this order; a provider without its API key is skipped.
    # The posting itself (names/emails it mentions) and name-pattern guessing always run.
    contact_providers: str = "hunter,apollo"
    hunter_api_key: str = ""
    apollo_api_key: str = ""
    contact_search_limit: int = Field(default=10, ge=1, le=50)
    # Spend Hunter verification credits on the best guessed addresses (at most this many per job)
    hunter_verify_guesses: int = Field(default=3, ge=0, le=20)

    # GitHub import (optional token raises the API rate limit from 60 to 5,000 requests/hour)
    github_token: str = ""

    # Email: console (log only) | smtp | ses
    mail_backend: str = "console"
    mail_from: str = "job-auto-apply <no-reply@localhost>"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True

    # Browser clients allowed to call the API (web app dev server, the Chrome extension)
    cors_origins: str = "http://localhost:5173"
    cors_origin_regex: str = r"chrome-extension://.*"

    max_upload_mb: int = Field(default=5, ge=1)

    @property
    def contact_provider_names(self) -> list[str]:
        return [p.strip().lower() for p in self.contact_providers.split(",") if p.strip()]

    @property
    def allowlist(self) -> set[str]:
        return {e.strip().lower() for e in self.signup_allowlist.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
