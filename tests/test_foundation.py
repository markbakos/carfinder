from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from typer.testing import CliRunner

from carfinder.cli import app
from carfinder.db.engine import create_database_engine
from carfinder.db.migrations import migration_status, upgrade_database
from carfinder.paths import AppPaths


def test_xdg_paths_and_development_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CARFINDER_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    paths = AppPaths.from_environment()
    assert paths.config_file == tmp_path / "config/carfinder/config.toml"
    assert paths.database_file == tmp_path / "data/carfinder/carfinder.sqlite3"
    assert paths.log_dir == tmp_path / "state/carfinder/logs"

    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / ".data"))
    override = AppPaths.from_environment()
    assert override.config_file == tmp_path / ".data/config/config.toml"
    assert override.database_file == tmp_path / ".data/data/carfinder.sqlite3"


def test_init_migrates_sqlite_with_required_pragmas(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / "runtime"))
    result = CliRunner().invoke(app, ["init"])
    assert result.exit_code == 0, result.output

    database = tmp_path / "runtime/data/carfinder.sqlite3"
    current, head = migration_status(database)
    assert current == head == "3b91ef6a5c20"

    engine = create_database_engine(database)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 5000
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
            assert connection.execute(text("SELECT COUNT(*) FROM scrape_runs")).scalar_one() == 0
    finally:
        engine.dispose()

def test_migration_head_is_defined() -> None:
    config_path = Path(__file__).parents[1] / "backend/carfinder/alembic.ini"
    assert ScriptDirectory.from_config(Config(str(config_path))).get_current_head() == "3b91ef6a5c20"
