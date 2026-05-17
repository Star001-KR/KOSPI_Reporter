from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DEFAULT_DB_PATH, get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

if settings.database_url.startswith("sqlite"):
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False}
else:
    connect_args = {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_symbol_owner_column()


def _ensure_symbol_owner_column() -> None:
    """Add ``symbols.owner_user_id`` to databases created before per-user
    symbol ownership existed.

    ``create_all()`` never alters an existing table, so a database file from
    an earlier build keeps a column-less ``symbols`` table. This one idempotent
    ``ALTER`` brings it up to date; a fresh database already has the column.
    """
    inspector = inspect(engine)
    if "symbols" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("symbols")}
    if "owner_user_id" in columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE symbols ADD COLUMN owner_user_id INTEGER")
        )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
