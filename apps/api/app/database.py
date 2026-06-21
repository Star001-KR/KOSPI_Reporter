from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DEFAULT_DB_PATH, get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")
if _is_sqlite:
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the API shares a connection across request
    # threads. timeout: how long the driver waits on a locked database before
    # raising, the connection-level companion to the busy_timeout pragma below.
    connect_args = {"check_same_thread": False, "timeout": 30}
else:
    connect_args = {}

engine = create_engine(settings.database_url, connect_args=connect_args)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # noqa: ANN001
        """Make concurrent API + worker access safe.

        WAL lets readers run while the single writer holds the lock instead of
        blocking; busy_timeout makes a contending writer wait up to 30s rather
        than failing instantly with "database is locked". Both the API and the
        launchd worker open this same engine, so both processes inherit these
        settings. WAL is persisted on the file, so re-asserting it per
        connection is cheap and harmless (and a no-op for in-memory test DBs).
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_symbol_owner_column()
    _backfill_symbol_owner()
    _ensure_one_running_collection_index()
    _ensure_news_ai_summary_columns()


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


def _backfill_symbol_owner(bind=None) -> None:
    """Attribute legacy unowned symbols to the sole user account.

    Symbols registered before per-user ownership existed have
    ``owner_user_id IS NULL``. The per-user scoping on symbol reads, the
    portfolio brief, and daily reports excludes those rows, which would hide a
    single-user instance's own pre-auth watchlist and holdings. When exactly
    one user account exists — the single-user history this app grew from —
    those rows unambiguously belong to that user, so claim them. With zero or
    multiple users we cannot safely attribute ownership and leave them as-is.

    Idempotent: once the rows are claimed there is nothing left to update, and
    new symbols always get an owner at creation time.
    """
    bind = bind or engine
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "symbols" not in table_names or "users" not in table_names:
        return
    if "owner_user_id" not in {c["name"] for c in inspector.get_columns("symbols")}:
        return
    with bind.begin() as connection:
        user_ids = connection.execute(text("SELECT id FROM users")).fetchall()
        if len(user_ids) != 1:
            return
        connection.execute(
            text("UPDATE symbols SET owner_user_id = :uid WHERE owner_user_id IS NULL"),
            {"uid": user_ids[0][0]},
        )


def _ensure_one_running_collection_index() -> None:
    """Add the partial unique index that lets at most one unified collection
    run be ``running`` at a time.

    ``create_all()`` never adds an index to an existing table, so a database
    from an earlier build needs this one-time creation. Any leftover
    ``running`` collection rows are failed first so the unique index can be
    built; a fresh database already has the index and skips this.
    """
    inspector = inspect(engine)
    if "collection_runs" not in inspector.get_table_names():
        return
    indexes = {ix["name"] for ix in inspector.get_indexes("collection_runs")}
    if "uq_collection_runs_one_running" in indexes:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE collection_runs SET status = 'failed' "
                "WHERE status = 'running' AND run_type = 'collection'"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_collection_runs_one_running "
                "ON collection_runs (run_type) "
                "WHERE status = 'running' AND run_type = 'collection'"
            )
        )


def _ensure_news_ai_summary_columns() -> None:
    """Add the AI-summary columns to ``news_items`` for databases predating them.

    The columns are nullable so existing rows stay valid without a backfill;
    they pick up summaries on the next collection or on first read.
    """
    inspector = inspect(engine)
    if "news_items" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("news_items")}
    additions = [
        ("ai_summary", "TEXT"),
        ("ai_summary_model", "VARCHAR(80)"),
        ("ai_summary_at", "DATETIME"),
    ]
    missing = [(name, ddl) for name, ddl in additions if name not in columns]
    if not missing:
        return
    with engine.begin() as connection:
        for name, ddl in missing:
            connection.execute(
                text(f"ALTER TABLE news_items ADD COLUMN {name} {ddl}")
            )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
