from __future__ import annotations

import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from carfinder.cli import app
from carfinder.db.engine import create_database_engine
from carfinder.db.migrations import upgrade_database


def test_db_backup_copies_committed_wal_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / "runtime"))
    database = tmp_path / "runtime/data/carfinder.sqlite3"
    upgrade_database(database)
    engine = create_database_engine(database)
    writer = engine.connect()
    try:
        writer.exec_driver_sql("INSERT INTO search_profiles (name, enabled, filters_json, preferences_json, initial_import_mode, created_at, updated_at) VALUES ('Backup check', 1, '{}', '{}', 'seed_only', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        writer.commit()
        assert Path(f"{database}-wal").exists()

        destination = tmp_path / "backup.sqlite3"
        result = CliRunner().invoke(app, ["db", "backup", "--output", str(destination)])
        assert result.exit_code == 0, result.output
        with sqlite3.connect(destination) as backup:
            assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert backup.execute("SELECT name FROM search_profiles").fetchone() == ("Backup check",)
    finally:
        writer.close()
        engine.dispose()


def test_systemd_install_renders_user_units(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / "runtime"))
    monkeypatch.setenv("PATH", "/opt/carfinder/bin:/usr/bin")
    monkeypatch.setattr("carfinder.cli.shutil.which", lambda name: {
        "systemd-analyze": None,
        "carfinder": "/opt/carfinder/bin/carfinder",
    }.get(name))

    result = CliRunner().invoke(app, ["systemd", "install", "--calendar", "weekly", "--randomized-delay-seconds", "42"])
    assert result.exit_code == 0, result.output
    unit_dir = tmp_path / "runtime/systemd/user"
    service = (unit_dir / "carfinder.service").read_text(encoding="utf-8")
    timer = (unit_dir / "carfinder.timer").read_text(encoding="utf-8")
    assert 'Environment="PATH=/opt/carfinder/bin:/usr/bin"' in service
    assert 'ExecStart="/opt/carfinder/bin/carfinder" run' in service
    assert "OnCalendar=weekly" in timer
    assert "RandomizedDelaySec=42" in timer
    assert "Persistent=true" in timer
