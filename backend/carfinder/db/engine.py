from __future__ import annotations

from pathlib import Path

from sqlalchemy import URL, create_engine, event
from sqlalchemy.engine import Engine


def create_database_engine(path: Path | str, *, busy_timeout_ms: int = 5000) -> Engine:
    database = str(path)
    if database != ":memory:":
        Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        URL.create("sqlite", database=database),
        connect_args={"check_same_thread": False, "timeout": busy_timeout_ms / 1000},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        cursor.close()

    return engine
