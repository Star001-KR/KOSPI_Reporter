from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "kospi.db"


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    cors_origins: tuple[str, ...]
    opendart_api_key: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        origins = os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        )
        return cls(
            app_name=os.getenv("APP_NAME", "Kospi Portfolio Research API"),
            database_url=os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}"),
            cors_origins=tuple(
                origin.strip() for origin in origins.split(",") if origin.strip()
            ),
            opendart_api_key=os.getenv("OPENDART_API_KEY") or None,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
