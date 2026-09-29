from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from importlib.util import find_spec
from pathlib import Path

import httpx
import typer
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from carfinder.config import Settings
from carfinder.db.engine import create_database_engine
from carfinder.db.migrations import migration_status, upgrade_database
from carfinder.db.models import ProviderSource, SearchProfile
from carfinder.logging_config import configure_logging
from carfinder.paths import AppPaths
from carfinder.analysis_service import analyze_stored_listings
from carfinder.pipeline.lock import RunAlreadyActive, run_lock
from carfinder.pipeline.runner import run_pipeline
from carfinder.providers.base import ProviderSearchSource
from carfinder.providers.registry import get_provider
from carfinder.search import HardFilters, SoftPreferences, filter_dict, preferences_dict
from carfinder.llm import ListingAnalysisRequest, get_llm_provider

app = typer.Typer(no_args_is_help=True, help="Local-first used-car discovery and buying intelligence.")
db_app = typer.Typer(no_args_is_help=True)
profile_app = typer.Typer(no_args_is_help=True)
systemd_app = typer.Typer(no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(profile_app, name="profile")
app.add_typer(systemd_app, name="systemd")


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
        try:
            with httpx.Client(timeout=8, follow_redirects=True) as client:
                response = client.get("https://www.polovniautomobili.com/")
            state = "ok" if response.status_code < 500 else "warn"
            report("Provider connectivity", state, f"PolovniAutomobili returned HTTP {response.status_code}")
        except httpx.HTTPError as error:
            report("Provider connectivity", "warn", f"{type(error).__name__}; live searches may be unavailable")
    else:
        report("Provider connectivity", "ok", "skipped; no provider enabled")

    if settings.llm.enabled:
        executable = settings.llm.command[0] if settings.llm.command else ""
        resolved = shutil.which(executable) if executable else None
        if resolved:
            report("LLM command", "ok", resolved)
            try:
                provider = get_llm_provider(
                    settings.llm.provider, [resolved, *settings.llm.command[1:]],
                    settings.llm.timeout_seconds, settings.llm.model,
                )
                asyncio.run(provider.analyze_listing(ListingAnalysisRequest(listing={
                    "title": "Synthetic CarFinder doctor check",
                    "description": "Synthetic input used only to check structured output; no real seller or vehicle.",
                })))
                report("LLM structured output", "ok", f"{settings.llm.provider}; schema validated")
            except Exception as error:
                report("LLM structured output", "warn", f"{type(error).__name__}; ingestion remains available")
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


def _run_pipeline_command(profile: str | None, provider: str | None) -> None:
    """Execute the full local pipeline without an API or UI process."""
    settings = _settings_or_exit()
    paths = AppPaths.from_environment()
    try:
        with run_lock(paths.lock_file):
            summary = asyncio.run(run_pipeline(settings, profile_name=profile, provider_id=provider))
    except RunAlreadyActive:
        typer.echo("run already active")
        return
    except Exception as error:
        typer.echo(f"Run failed: {type(error).__name__}: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"Run #{summary.run_id}: {summary.status}")
    typer.echo(f"Profiles processed: {summary.profiles_processed}")
    typer.echo(f"Sources processed: {summary.sources_processed}")
    typer.echo(f"Listings encountered: {summary.listings_seen}")
    typer.echo(f"New listings: {summary.listings_new}")
    typer.echo(f"Changed listings: {summary.listings_changed}")
    typer.echo(f"Price drops: {summary.price_drops}")
    typer.echo(f"Removed listings: {summary.listings_removed}")
    typer.echo(f"Detail requests: {summary.detail_requests}")
    typer.echo(f"LLM calls: {summary.llm_calls}; cache hits: {summary.llm_cache_hits}")
    typer.echo(f"Warnings: {summary.warning_count}; errors: {summary.error_count}")
    if summary.status == "failed":
        raise typer.Exit(1)


@app.command()
def run(
    profile: str | None = typer.Option(None, help="Limit to one saved profile."),
    provider: str | None = typer.Option(None, help="Limit to one provider."),
) -> None:
    """Run discovery and analysis without requiring the API or UI."""
    _run_pipeline_command(profile, provider)


@app.command()
def scrape(
    profile: str | None = typer.Option(None, help="Limit to one saved profile."),
    provider: str | None = typer.Option(None, help="Limit to one provider."),
) -> None:
    """Alias for run, useful for scripts that call the collection step scrape."""
    _run_pipeline_command(profile, provider)


@app.command()
def analyze(
    listing_id: int | None = typer.Option(None, "--listing", help="Analyze one stored listing."),
    force: bool = typer.Option(False, "--force", help="Re-run the configured LLM, bypassing its cache."),
) -> None:
    """Analyze stored listing snapshots without contacting providers."""
    settings = _settings_or_exit()
    paths = AppPaths.from_environment()
    try:
        with run_lock(paths.lock_file):
            result = asyncio.run(analyze_stored_listings(settings, listing_id=listing_id, force=force))
    except RunAlreadyActive:
        typer.echo("run already active")
        return
    except LookupError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    typer.echo(f"Analysis run #{result['run_id']}: {result['status']}")
    typer.echo(f"Listings analyzed: {result['listings_analyzed']}")
    typer.echo(f"LLM calls: {result['llm_calls']}; cache hits: {result['llm_cache_hits']}")
    typer.echo(f"Warnings: {result['warning_count']}")


@app.command()
def serve() -> None:
    """Serve the local API and built frontend."""
    settings = _settings_or_exit()
    import uvicorn

    uvicorn.run("carfinder.api.app:app", host=settings.server.host, port=settings.server.port)


@profile_app.command("create")
def profile_create(
    name: str,
    search_url: str | None = typer.Option(None, "--search-url", help="Imported PolovniAutomobili search URL."),
    filters_json: str = typer.Option("{}", "--filters-json", help="Hard filters as a JSON object."),
    preferences_json: str = typer.Option("{}", "--preferences-json", help="Soft preferences as a JSON object."),
    provider: str = typer.Option("polovniautomobili", help="Listing provider ID."),
    initial_import_mode: str = typer.Option("seed_only", help="seed_only, analyze_all, or analyze_top_n."),
    analyze_top_n: int = typer.Option(25, min=1, help="Maximum initial listings for analyze_top_n."),
) -> None:
    """Create a profile backed by native filters, an imported URL, or both."""
    if initial_import_mode not in {"seed_only", "analyze_all", "analyze_top_n"}:
        typer.echo("initial-import-mode must be seed_only, analyze_all, or analyze_top_n", err=True)
        raise typer.Exit(2)
    try:
        filters = filter_dict(HardFilters.model_validate_json(filters_json))
    except Exception as error:
        typer.echo(f"Invalid filters JSON: {error}", err=True)
        raise typer.Exit(2) from error
    try:
        preferences = preferences_dict(SoftPreferences.model_validate_json(preferences_json))
    except Exception as error:
        typer.echo(f"Invalid preferences JSON: {error}", err=True)
        raise typer.Exit(2) from error
    if not search_url and not filters and not preferences:
        typer.echo("Provide --search-url, non-empty --filters-json, or --preferences-json", err=True)
        raise typer.Exit(2)
    try:
        adapter = get_provider(provider)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    source = ProviderSearchSource(provider=provider, search_url=search_url, native_filters=filters)
    result = adapter.validate_source(source)
    if not result.valid:
        typer.echo(result.message, err=True)
        raise typer.Exit(2)

    settings = _settings_or_exit()
    engine = create_database_engine(settings.database_path)
    try:
        with Session(engine) as session:
            profile = SearchProfile(
                name=name, filters_json=filters, preferences_json=preferences,
                initial_import_mode=initial_import_mode,
            )
            session.add(profile)
            session.flush()
            session.add(ProviderSource(
                profile_id=profile.id,
                provider=provider,
                search_url=search_url.strip() if search_url else None,
                source_settings_json={"analyze_top_n": analyze_top_n} if initial_import_mode == "analyze_top_n" else {},
            ))
            session.commit()
            typer.echo(f"Created profile #{profile.id}: {profile.name}")
            if filters:
                typer.echo(f"Hard filters: {json.dumps(filters, ensure_ascii=False, sort_keys=True)}")
            if preferences:
                typer.echo(f"Soft preferences: {json.dumps(preferences, ensure_ascii=False, sort_keys=True)}")
    except Exception as error:
        typer.echo(f"Could not create profile: {error}", err=True)
        raise typer.Exit(1) from error
    finally:
        engine.dispose()


@profile_app.command("list")
def profile_list() -> None:
    """List saved search profiles."""
    settings = _settings_or_exit()
    engine = create_database_engine(settings.database_path)
    try:
        with Session(engine) as session:
            profiles = session.scalars(select(SearchProfile).order_by(SearchProfile.id)).all()
            if not profiles:
                typer.echo("No saved profiles.")
                return
            for item in profiles:
                state = "enabled" if item.enabled else "disabled"
                typer.echo(f"{item.id}\t{item.name}\t{state}\t{item.initial_import_mode}")
    finally:
        engine.dispose()


@profile_app.command("show")
def profile_show(profile_id: int) -> None:
    """Show a saved search profile and its provider sources."""
    settings = _settings_or_exit()
    engine = create_database_engine(settings.database_path)
    try:
        with Session(engine) as session:
            item = session.get(SearchProfile, profile_id)
            if item is None:
                typer.echo(f"Profile not found: {profile_id}", err=True)
                raise typer.Exit(1)
            typer.echo(f"Profile #{item.id}: {item.name}")
            typer.echo(f"Enabled: {item.enabled}; initial import: {item.initial_import_mode}")
            typer.echo(f"Hard filters: {json.dumps(item.filters_json, ensure_ascii=False, sort_keys=True)}")
            typer.echo(f"Preferences: {json.dumps(item.preferences_json, ensure_ascii=False, sort_keys=True)}")
            for source in session.scalars(select(ProviderSource).where(ProviderSource.profile_id == item.id)):
                typer.echo(f"Source #{source.id} [{source.provider}] {'enabled' if source.enabled else 'disabled'}")
                typer.echo(f"  {source.search_url or 'native filters'}")
    finally:
        engine.dispose()


def _profile_set_enabled(profile_id: int, enabled: bool) -> None:
    settings = _settings_or_exit()
    engine = create_database_engine(settings.database_path)
    try:
        with Session(engine) as session:
            item = session.get(SearchProfile, profile_id)
            if item is None:
                typer.echo(f"Profile not found: {profile_id}", err=True)
                raise typer.Exit(1)
            item.enabled = enabled
            session.commit()
            typer.echo(f"Profile {item.id} {'enabled' if enabled else 'disabled'}.")
    finally:
        engine.dispose()


@profile_app.command("enable")
def profile_enable(profile_id: int) -> None:
    _profile_set_enabled(profile_id, True)


@profile_app.command("disable")
def profile_disable(profile_id: int) -> None:
    _profile_set_enabled(profile_id, False)


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply pending Alembic migrations."""
    settings = _settings_or_exit()
    upgrade_database(settings.database_path)
    typer.echo(f"Database is current: {settings.database_path}")


@db_app.command("backup")
def db_backup(output: Path | None = typer.Option(None, "--output", help="Write the backup to this path.")) -> None:
    """Create a consistent SQLite backup, including committed WAL data."""
    settings = _settings_or_exit()
    source_path = settings.database_path
    if not source_path.is_file():
        typer.echo(f"Database does not exist: {source_path}", err=True)
        raise typer.Exit(1)
    if output is None:
        backup_dir = AppPaths.from_environment().backup_dir
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H%M%S")
        destination = backup_dir / f"carfinder-{timestamp}.sqlite3"
        suffix = 1
        while destination.exists():
            destination = backup_dir / f"carfinder-{timestamp}-{suffix}.sqlite3"
            suffix += 1
    else:
        destination = output.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
    if destination == source_path.resolve():
        typer.echo("Backup destination must differ from the active database", err=True)
        raise typer.Exit(2)
    if destination.exists():
        typer.echo(f"Backup destination already exists: {destination}", err=True)
        raise typer.Exit(2)

    source_uri = source_path.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(source_uri, uri=True, timeout=5)) as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target, pages=256, sleep=0.1)
            target.commit()
            integrity = target.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise sqlite3.DatabaseError("backup integrity check failed")
    except Exception as error:
        destination.unlink(missing_ok=True)
        typer.echo(f"Backup failed: {type(error).__name__}: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"Database backup created: {destination}")


@db_app.command("path")
def db_path() -> None:
    """Print the configured SQLite path."""
    settings = _settings_or_exit()
    typer.echo(settings.database_path)


def _unit_quote(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("systemd unit values must be a single line")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


@systemd_app.command("install")
def systemd_install(
    calendar: str = typer.Option("*-*-* 08,14,20:00:00", "--calendar", help="systemd OnCalendar expression."),
    randomized_delay_seconds: int = typer.Option(300, "--randomized-delay-seconds", min=0, max=86400),
) -> None:
    """Generate a user service and timer for the current CarFinder executable."""
    if not calendar.strip() or "\n" in calendar or "\r" in calendar:
        typer.echo("Calendar must be a non-empty single line", err=True)
        raise typer.Exit(2)
    analyzer = shutil.which("systemd-analyze")
    if analyzer:
        try:
            subprocess.run([analyzer, "calendar", calendar], check=True, capture_output=True, text=True, timeout=5)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else "validation timed out"
            typer.echo(f"Invalid systemd calendar: {detail}", err=True)
            raise typer.Exit(2) from error

    executable = shutil.which("carfinder") or str(Path(sys.argv[0]).resolve())
    project_root = Path(__file__).resolve().parents[2]
    template_dir = project_root / "systemd"
    replacements = {
        "@CARFINDER_EXECUTABLE@": _unit_quote(executable),
        "@PATH@": _unit_quote(f"PATH={os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}"),
        "@CALENDAR@": calendar.strip().replace("%", "%%"),
        "@RANDOMIZED_DELAY_SECONDS@": str(randomized_delay_seconds),
    }
    unit_dir = AppPaths.from_environment().config_dir.parent / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name in ("carfinder.service", "carfinder.timer"):
        template = template_dir / f"{name}.in"
        content = template.read_text(encoding="utf-8")
        for token, value in replacements.items():
            content = content.replace(token, value)
        destination = unit_dir / name
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(destination)
    typer.echo(f"Generated user units in {unit_dir}")
    typer.echo("Enable the schedule with: systemctl --user daemon-reload && systemctl --user enable --now carfinder.timer")


if __name__ == "__main__":
    app()
