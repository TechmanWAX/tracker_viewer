"""Core application configuration using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


# Known-insecure default values for secrets. The startup check
# refuses to boot if the live config still has one of these in
# what looks like a production environment. Add to the set if
# a new placeholder default is introduced elsewhere.
INSECURE_JWT_DEFAULTS: frozenset[str] = frozenset({
    "your-secret-key-change-in-production",
    "your-secret-key-change-in-production-please-use-32-chars",
})
INSECURE_CSRF_DEFAULTS: frozenset[str] = frozenset({
    "your-csrf-secret-key-change-in-production",
})


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "GPS Log Tracker API"
    app_version: str = "0.1.0"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/gps_tracker"
    )
    database_pool_size: int = Field(default=5)
    database_max_overflow: int = Field(default=10)

    # JWT
    jwt_secret_key: str = Field(default="your-secret-key-change-in-production")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=15)
    refresh_token_expire_days: int = Field(default=7)

    # CORS
    # `NoDecode` tells pydantic-settings to hand the raw string from
    # .env straight to `parse_cors_origins` instead of trying to
    # JSON-decode it first. That's how the comma-separated form
    # (`CORS_ORIGINS=http://a,http://b`) works without quoting.
    cors_origins: Annotated[List[str], NoDecode] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:8080",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        validation_alias="CORS_ORIGINS",
    )

    # Rate Limiting
    rate_limit_requests: int = Field(default=10)
    rate_limit_window_seconds: int = Field(default=60)
    rate_limit_enabled: bool = Field(default=True)

    # File Upload
    max_upload_size_mb: int = Field(default=100)
    upload_dir: str = Field(default="/tmp/gps_tracker_uploads")

    # Celery
    celery_broker_url: str = Field(default="redis://localhost:6379/0")
    celery_result_backend: str = Field(default="redis://localhost:6379/0")
    celery_task_always_eager: bool = Field(default=False)

    # CSRF
    csrf_secret_key: str = Field(default="your-csrf-secret-key-change-in-production")
    csrf_enabled: bool = Field(default=True, validation_alias="CSRF_ENABLED")

    # Cookies
    # Set to True in production (HTTPS). Defaults to False for local HTTP dev.
    cookie_secure: bool = Field(default=False, validation_alias="COOKIE_SECURE")

    # Email verification
    # Single-use link TTL. Default 30 minutes per the spec.
    verification_token_ttl_minutes: int = Field(default=30)
    # Public base URL used to build verification links (frontend
    # route is /verify-email?token=…). See APP_BASE_URL in .env.
    app_base_url: str = Field(default="http://localhost:5173")

    # Email transport
    # `mail_enabled=False` writes each email as a JSON file to
    # `mail_dev_out_dir` and logs a one-liner with the link. This is
    # the dev default because there's no SMTP server in this env. To
    # go to prod, set MAIL_ENABLED=true and (optionally) SMTP creds —
    # see `email_service.py`.
    mail_enabled: bool = Field(default=False, validation_alias="MAIL_ENABLED")
    mail_from: str = Field(default="noreply@gpstracker.local")
    mail_dev_out_dir: str = Field(default="/tmp/verification_emails")
    # Reserved for future SMTP support; unused while mail_enabled=False.
    mail_host: Optional[str] = Field(default=None)
    mail_port: int = Field(default=587)
    mail_username: Optional[str] = Field(default=None)
    mail_password: Optional[str] = Field(default=None)
    # If False, skip TLS certificate verification when connecting
    # to the SMTP server. Default True. Setting this to False is a
    # **dev-only** escape hatch for servers with expired or
    # self-signed certs — it makes man-in-the-middle possible.
    # See `email_service._smtp_send_blocking`.
    mail_tls_verify: bool = Field(default=True, validation_alias="MAIL_TLS_VERIFY")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | List[str]) -> List[str]:
        """Parse CORS origins from comma-separated string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # ------------------------------------------------------------------
    # Production-readiness helpers
    # ------------------------------------------------------------------

    @property
    def looks_like_production(self) -> bool:
        """Heuristic: APP_BASE_URL points somewhere other than the
        loopback addresses we use for local dev. We rely on this
        rather than a separate APP_ENV flag so the only thing an
        operator has to set for "prod mode" is the public URL — and
        the public URL is something they have to set anyway, for the
        verification email link to be correct.
        """
        base = self.app_base_url.lower()
        return not (
            base.startswith("http://localhost")
            or base.startswith("http://127.0.0.1")
        )

    @property
    def using_insecure_secrets(self) -> bool:
        return (
            self.jwt_secret_key in INSECURE_JWT_DEFAULTS
            or self.csrf_secret_key in INSECURE_CSRF_DEFAULTS
        )

    def validate_production_readiness(self) -> List[str]:
        """Return a list of human-readable issues. Empty list = safe.

        These are warnings when `looks_like_production` is False
        (i.e. the user is running locally) and **fatal** otherwise.
        See `app.main.lifespan` for the actual fail-loud behavior.
        """
        issues: List[str] = []
        if self.using_insecure_secrets:
            which = []
            if self.jwt_secret_key in INSECURE_JWT_DEFAULTS:
                which.append("JWT_SECRET_KEY")
            if self.csrf_secret_key in INSECURE_CSRF_DEFAULTS:
                which.append("CSRF_SECRET_KEY")
            issues.append(
                f"{', '.join(which)} is using a known-insecure default "
                "value. Generate a new one with "
                "`python -c \"import secrets; print(secrets.token_urlsafe(64))\"`."
            )
        if not self.cookie_secure:
            issues.append(
                "COOKIE_SECURE=false — auth cookies may be sent over "
                "plain HTTP, which exposes session tokens."
            )
        if not self.csrf_enabled:
            issues.append(
                "CSRF_ENABLED=false — CSRF protection is off. Set to "
                "true unless the API is consumed by a non-browser client."
            )
        if not self.rate_limit_enabled:
            issues.append(
                "RATE_LIMIT_ENABLED=false — endpoints are not "
                "rate-limited. Set to true in production."
            )
        if any("localhost" in o or "127.0.0.1" in o for o in self.cors_origins):
            issues.append(
                "cors_origins contains a localhost entry — these should "
                "be removed (and replaced with the production frontend URL)."
            )
        if self.mail_enabled and not self.mail_tls_verify:
            issues.append(
                "MAIL_TLS_VERIFY=false — SMTP TLS certificate "
                "verification is disabled. Set to true once your mail "
                "server's certificate is valid."
            )
        return issues


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()