from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from carfinder.cli import app
from carfinder.config import Settings
from carfinder.db.engine import create_database_engine
from carfinder.db.models import (
    Listing,
    ListingAnalysis,
    ListingEvent,
    ListingSnapshot,
    ProviderSource,
    ProviderSourceListing,
    SearchProfile,
)
from carfinder.pipeline import runner
from carfinder.pipeline.lock import RunAlreadyActive, run_lock
from carfinder.providers.base import (
    DiscoveredListing,
    NormalizedListing,
    ProviderCapabilities,
    ProviderSearchSource,
    RawListing,
    RunContext,
    ValidationResult,
)


class FakeProvider:
    provider_id = "polovniautomobili"
    capabilities = ProviderCapabilities(supports_search_url=True)

    def __init__(self) -> None:
        self.items = [DiscoveredListing(
            provider=self.provider_id,
            external_id="test-1",
            url="https://www.polovniautomobili.com/auto-oglasi/test-1/fixture",
            title="Volkswagen Golf V",
        )]
        self.price = 4300
        self.description = "Prvi vlasnik, servisna knjiga."
        self.search_error = False

    def validate_source(self, source: ProviderSearchSource) -> ValidationResult:
        return ValidationResult(valid=True)

    async def open_run(self, context: RunContext) -> None:
        return None

    async def close_run(self) -> None:
        return None

    async def search(self, source: ProviderSearchSource, context: RunContext):
        if self.search_error:
            raise RuntimeError("synthetic search failure")
        for item in self.items:
            yield item

    async def fetch_listing(self, discovered: DiscoveredListing, context: RunContext) -> RawListing:
        return RawListing(provider=self.provider_id, external_id=discovered.external_id, url=discovered.url)

    def normalize(self, raw: RawListing) -> NormalizedListing:
        return NormalizedListing(
            provider=self.provider_id,
            external_id=raw.external_id,
            url=raw.url,
            title="Volkswagen Golf V 1.9 TDI",
            description=self.description,
            price_amount=self.price,
            price_currency="EUR",
            make="Volkswagen",
            model="Golf",
            generation="Golf V",
            year=2008,
            fuel="diesel",
            mileage_km=198000,
            engine_cc=1896,
            power_kw=77,
            transmission="manual",
            city="Novi Sad",
        )


def _initialize(monkeypatch, tmp_path: Path) -> tuple[Settings, Path]:
    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / "runtime"))
    result = CliRunner().invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    settings = Settings.load()
    engine = create_database_engine(settings.database_path)
    with Session(engine) as session:
        profile = SearchProfile(name="Golf V", initial_import_mode="seed_only")
        session.add(profile)
        session.flush()
        session.add(ProviderSource(
            profile_id=profile.id,
            provider="polovniautomobili",
            search_url="https://www.polovniautomobili.com/auto-oglasi/pretraga?brand=volkswagen",
        ))
        session.commit()
    engine.dispose()
    return settings, settings.database_path


def test_pipeline_snapshots_events_removal_and_reappearance(monkeypatch, tmp_path: Path) -> None:
    settings, database = _initialize(monkeypatch, tmp_path)
    provider = FakeProvider()
    monkeypatch.setattr(runner, "get_provider", lambda _provider_id: provider)

    first = asyncio.run(runner.run_pipeline(settings, profile_name="Golf V"))
    second = asyncio.run(runner.run_pipeline(settings, profile_name="Golf V"))
    assert first.status == second.status == "success"
    assert first.listings_new == 1 and first.detail_requests == 1
    assert second.listings_new == 0 and second.detail_requests == 0

    engine = create_database_engine(database)
    with Session(engine) as session:
        listing = session.scalar(select(Listing))
        assert listing is not None
        first_seen = listing.first_seen_at
        listing.last_detail_fetch_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
        session.commit()
    provider.price = 3900
    price_run = asyncio.run(runner.run_pipeline(settings, profile_name="Golf V"))
    assert price_run.listings_changed == 1
    assert price_run.price_drops == 1

    with Session(engine) as session:
        listing = session.scalar(select(Listing))
        assert listing is not None and listing.first_seen_at == first_seen
        listing.last_detail_fetch_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
        session.commit()
    provider.description = "Servisna knjiga dostupna."
    asyncio.run(runner.run_pipeline(settings, profile_name="Golf V"))

    provider.items = []
    for expected_misses in (1, 2, 3):
        asyncio.run(runner.run_pipeline(settings, profile_name="Golf V"))
        with Session(engine) as session:
            listing = session.scalar(select(Listing))
            assert listing is not None
            if expected_misses < 3:
                assert listing.status == "active"
            else:
                assert listing.status == "removed"
            link = session.scalar(select(ProviderSourceListing))
            assert link is not None and link.missing_run_count == expected_misses

    provider.items = [DiscoveredListing(
        provider=provider.provider_id,
        external_id="test-1",
        url="https://www.polovniautomobili.com/auto-oglasi/test-1/fixture",
    )]
    reappeared = asyncio.run(runner.run_pipeline(settings, profile_name="Golf V"))
    assert reappeared.status == "success"
    with Session(engine) as session:
        listing = session.scalar(select(Listing))
        assert listing is not None and listing.status == "active" and listing.removed_at is None
        count = session.scalar(select(func.count()).select_from(ListingSnapshot).where(ListingSnapshot.listing_id == listing.id))
        assert count == 3
        event_types = set(session.scalars(select(ListingEvent.event_type).where(ListingEvent.listing_id == listing.id)))
        assert {"discovered", "price_dropped", "description_changed", "removed", "reappeared"} <= event_types
    engine.dispose()


def test_failed_search_does_not_count_as_a_removal_miss(monkeypatch, tmp_path: Path) -> None:
    settings, database = _initialize(monkeypatch, tmp_path)
    provider = FakeProvider()
    monkeypatch.setattr(runner, "get_provider", lambda _provider_id: provider)
    asyncio.run(runner.run_pipeline(settings))
    provider.search_error = True
    summary = asyncio.run(runner.run_pipeline(settings))
    assert summary.status == "failed"
    engine = create_database_engine(database)
    with Session(engine) as session:
        listing = session.scalar(select(Listing))
        link = session.scalar(select(ProviderSourceListing))
        assert listing is not None and listing.status == "active"
        assert link is not None and link.missing_run_count == 0
    engine.dispose()


def test_one_listing_is_shared_and_only_matches_profiles_that_pass_filters(monkeypatch, tmp_path: Path) -> None:
    settings, database = _initialize(monkeypatch, tmp_path)
    provider = FakeProvider()
    monkeypatch.setattr(runner, "get_provider", lambda _provider_id: provider)
    engine = create_database_engine(database)
    with Session(engine) as session:
        nonmatching = session.scalar(select(SearchProfile).where(SearchProfile.name == "Golf V"))
        assert nonmatching is not None
        nonmatching.filters_json = {"makes": ["BMW"]}
        matching = SearchProfile(
            name="Diesel Golf", filters_json={"makes": ["Volkswagen"], "fuel": ["diesel"]}
        )
        session.add(matching)
        session.flush()
        session.add(ProviderSource(
            profile_id=matching.id,
            provider="polovniautomobili",
            search_url="https://www.polovniautomobili.com/auto-oglasi/pretraga?brand=volkswagen",
        ))
        session.commit()

    summary = asyncio.run(runner.run_pipeline(settings))
    assert summary.status == "success" and summary.listings_new == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Listing)) == 1
        matches = session.scalars(select(runner.ProfileListingMatch).order_by(runner.ProfileListingMatch.profile_id)).all()
        assert len(matches) == 2
        assert [item.hard_filter_pass for item in matches] == [False, True]
    engine.dispose()


def test_llm_failure_does_not_abort_listing_ingestion(monkeypatch, tmp_path: Path) -> None:
    _settings, database = _initialize(monkeypatch, tmp_path)
    engine = create_database_engine(database)
    with Session(engine) as session:
        profile = session.scalar(select(SearchProfile).where(SearchProfile.name == "Golf V"))
        assert profile is not None
        profile.initial_import_mode = "analyze_all"
        session.commit()
    engine.dispose()
    settings = Settings.model_validate({
        "database": {"path": str(database)},
        "llm": {"enabled": True, "provider": "codex_exec", "command": ["missing-codex"]},
    })
    provider = FakeProvider()
    monkeypatch.setattr(runner, "get_provider", lambda _provider_id: provider)
    import carfinder.analysis_service as service
    def missing_llm(*_args):
        raise RuntimeError("not installed")
    monkeypatch.setattr(service, "get_llm_provider", missing_llm)

    summary = asyncio.run(runner.run_pipeline(settings, profile_name="Golf V"))
    assert summary.status == "partial"
    assert summary.listings_new == 1 and summary.detail_requests == 1
    assert summary.llm_calls == 1 and summary.warning_count == 1 and summary.error_count == 0
    engine = create_database_engine(database)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Listing)) == 1
        analysis = session.scalar(select(ListingAnalysis))
        assert analysis is not None and analysis.status == "partial"
    engine.dispose()


def test_profile_cli_stores_a_valid_imported_search(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / "runtime"))
    assert CliRunner().invoke(app, ["init"]).exit_code == 0
    result = CliRunner().invoke(app, [
        "profile", "create", "Broad cars",
        "--search-url", "https://www.polovniautomobili.com/auto-oglasi/pretraga?priceTo=5000",
    ])
    assert result.exit_code == 0, result.output
    invalid = CliRunner().invoke(app, [
        "profile", "create", "Invalid",
        "--search-url", "https://evil.example/auto-oglasi/pretraga",
    ])
    assert invalid.exit_code == 2

    settings = Settings.load()
    engine = create_database_engine(settings.database_path)
    with Session(engine) as session:
        profile = session.scalar(select(SearchProfile).where(SearchProfile.name == "Broad cars"))
        assert profile is not None and profile.initial_import_mode == "seed_only"
        source = session.scalar(select(ProviderSource).where(ProviderSource.profile_id == profile.id))
        assert source is not None and "priceTo=5000" in source.search_url
    engine.dispose()


def test_global_lock_rejects_an_overlapping_run(tmp_path: Path) -> None:
    lock_path = tmp_path / "run.lock"
    with run_lock(lock_path):
        try:
            with run_lock(lock_path):
                raise AssertionError("second lock unexpectedly succeeded")
        except RunAlreadyActive:
            pass
