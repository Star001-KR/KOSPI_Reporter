from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "kospi.db"

# Load the repository .env (if present) so OPENDART/NAVER keys and other
# settings are picked up automatically. Existing environment variables are not
# overridden, so platform-provided values still take precedence in production.
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    cors_origins: tuple[str, ...]
    frontend_url: str
    opendart_api_key: str | None
    naver_client_id: str | None
    naver_client_secret: str | None
    anthropic_api_key: str | None
    ai_summary_model: str
    ai_summary_eager_per_symbol: int
    google_oauth_client_id: str | None
    google_oauth_client_secret: str | None
    google_oauth_redirect_uri: str
    auth_cookie_secure: bool
    auth_cookie_samesite: str
    auth_session_days: int
    enable_dev_routes: bool

    @classmethod
    def from_env(cls) -> "Settings":
        origins = os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        )
        frontend_url = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173").rstrip("/")
        return cls(
            app_name=os.getenv("APP_NAME", "Kospi Portfolio Research API"),
            database_url=os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}"),
            cors_origins=tuple(
                origin.strip() for origin in origins.split(",") if origin.strip()
            ),
            frontend_url=frontend_url,
            opendart_api_key=os.getenv("OPENDART_API_KEY") or None,
            naver_client_id=os.getenv("NAVER_CLIENT_ID") or None,
            naver_client_secret=os.getenv("NAVER_CLIENT_SECRET") or None,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
            ai_summary_model=os.getenv(
                "AI_SUMMARY_MODEL", "claude-haiku-4-5-20251001"
            ),
            ai_summary_eager_per_symbol=int(
                os.getenv("AI_SUMMARY_EAGER_PER_SYMBOL", "3")
            ),
            google_oauth_client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID") or None,
            google_oauth_client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or None,
            google_oauth_redirect_uri=os.getenv(
                "GOOGLE_OAUTH_REDIRECT_URI",
                "http://127.0.0.1:8000/api/auth/google/callback",
            ),
            auth_cookie_secure=os.getenv("AUTH_COOKIE_SECURE", "").lower()
            in {"1", "true", "yes"},
            auth_cookie_samesite=os.getenv("AUTH_COOKIE_SAMESITE", "lax").lower(),
            auth_session_days=int(os.getenv("AUTH_SESSION_DAYS", "30")),
            enable_dev_routes=os.getenv("ENABLE_DEV_ROUTES", "").lower()
            in {"1", "true", "yes"},
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
