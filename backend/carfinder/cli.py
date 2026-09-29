from __future__ import annotations

import shutil
from importlib.util import find_spec
from pathlib import Path

import typer
from pydantic import ValidationError
from sqlalchemy import text

from carfinder.config import Settings
from carfinder.db.engine import create_database_engine
from carfinder.db.migrations import migration_status, upgrade_database
from carfinder.logging_config import configure_logging
from carfinder.paths import AppPaths

app = typer.Typer(no_args_is_help=True, help="Local-first used-car discovery and buying intelligence.")
db_app = typer.Typer(no_args_is_help=True)
app.add_typer(db_app, name="db")


@app.callback()
def setup() -> None:
    configure_logging()


def _settings_or_exit() -> Settings:
    try:
        return Settings.load()
    except (OSError, ValueError, ValidationError) as error:
        typer.echo(f"Invalid configuration: {error}", err=True)
        raise typer.Exit(2) from error


@app.command()
def init() -> None:
    """Create local directories, initial config, and database schema."""
    paths = AppPaths.from_environment()
    paths.ensure()
    if not paths.config_file.exists():
        example = Path(__file__).resolve().parents[2] / "config" / "config.example.toml"
        if not example.is_file():
            typer.echo(f"Missing example config: {example}", err=True)
            raise typer.Exit(1)
        shutil.copyfile(example, paths.config_file)

    settings = _settings_or_exit()
    upgrade_database(settings.database_path)
    typer.echo(f"Initialized database: {settings.database_path}")
    typer.echo(f"Configuration: {paths.config_file}")


@app.command()
def doctor() -> None:
    """Check local configuration and runtime prerequisites."""
    settings = _settings_or_exit()
    failures = 0
    warnings = 0

    def report(label: str, state: str, detail: str = "") -> None:
        nonlocal failures, warnings
        typer.echo(f"[{state}] {label}" + (f": {detail}" if detail else ""))
        failures += state == "fail"
        warnings += state == "warn"

    report("configuration", "ok", str(settings.config_path) if settings.config_path else "defaults")
    database_engine = create_database_engine(settings.database_path)
    try:
        with database_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            connection.rollback()
        current, head = migration_status(settings.database_path)
        if current == head and head is not None:
            report("SQLite", "ok", f"{settings.database_path}; revision {current}; writable")
        else:
            report("SQLite", "fail", f"revision {current or 'none'}; expected {head or 'none'}; run carfinder init")
    except Exception as error:
        report("SQLite", "fail", str(error))
    finally:
        database_engine.dispose()

    if find_spec("playwright") is None:
        report("Playwright", "warn", "not installed")
    else:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                chromium = Path(playwright.chromium.executable_path)
            if chromium.is_file():
                report("Playwright Chromium", "ok", str(chromium))
            else:
                report("Playwright Chromium", "warn", "browser missing; run uv run playwright install chromium")
        except Exception as error:
            report("Playwright Chromium", "warn", str(error))

    if settings.providers.polovniautomobili.enabled:
        if settings.browser_profile.exists():
            report("Polovni browser profile", "ok", str(settings.browser_profile))
        else:
            report("Polovni browser profile", "warn", f"will be created on first run: {settings.browser_profile}")
        report("Provider connectivity", "warn", "live check is not part of doctor yet")
    else:
        report("Provider connectivity", "ok", "skipped; no provider enabled")

    if settings.llm.enabled:
        executable = settings.llm.command[0] if settings.llm.command else ""
        if executable and shutil.which(executable):
            report("LLM command", "ok", executable)
        else:
            report("LLM command", "warn", f"not found: {executable or '(empty command)'}")
    else:
        report("LLM", "ok", "disabled")

    frontend_index = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"
    if frontend_index.is_file():
        report("Frontend build", "ok", str(frontend_index))
    else:
        report("Frontend build", "warn", "not built; run npm run build in frontend/")

    if failures:
        typer.echo(f"Doctor found {failures} blocking issue(s) and {warnings} warning(s).", err=True)
        raise typer.Exit(1)
    typer.echo(f"Doctor passed with {warnings} warning(s).")


@app.command()
def run(
    profile: str | None = typer.Option(None, help="Limit to one saved profile."),
    provider: str | None = typer.Option(None, help="Limit to one provider."),
) -> None:
    """Run discovery and analysis without requiring the API or UI."""
    del profile, provider
    typer.echo("Provider ingestion is not implemented yet (Phase 1).", err=True)
    raise typer.Exit(2)


@app.command()
def serve() -> None:
    """Serve the local API and built frontend."""
    settings = _settings_or_exit()
    import uvicorn

    uvicorn.run("carfinder.api.app:app", host=settings.server.host, port=settings.server.port)


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply pending Alembic migrations."""
    settings = _settings_or_exit()
    upgrade_database(settings.database_path)
    typer.echo(f"Database is current: {settings.database_path}")


@db_app.command("path")
def db_path() -> None:
    """Print the configured SQLite path."""
    settings = _settings_or_exit()
    typer.echo(settings.database_path)


if __name__ == "__main__":
    app()
