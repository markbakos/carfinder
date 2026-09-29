from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Engine

from carfinder.db.engine import create_database_engine


def _config(connection=None) -> Config:
    config_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    config = Config(str(config_path))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def upgrade_database(path: Path) -> None:
    engine = create_database_engine(path)
    try:
        with engine.connect() as connection:
            if str(path) != ":memory:":
                connection.exec_driver_sql("PRAGMA journal_mode=WAL")
                connection.commit()
            command.upgrade(_config(connection), "head")
    finally:
        engine.dispose()


def migration_status(path: Path) -> tuple[str | None, str | None]:
    engine: Engine = create_database_engine(path)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        head = ScriptDirectory.from_config(_config()).get_current_head()
        return current, head
    finally:
        engine.dispose()
