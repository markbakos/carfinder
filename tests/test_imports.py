from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from carfinder.cli import app
from carfinder.db.engine import create_database_engine
from carfinder.db.migrations import upgrade_database
from carfinder.db.models import (
    Listing, ListingAnalysis, ListingClaim, ListingEvent, ListingScore, ListingSnapshot,
    ListingValuation, ProfileListingMatch, SearchProfile, ScrapeRun,
)


def test_manual_json_import_reuses_history_analysis_and_scoring(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / "runtime"))
    database = tmp_path / "runtime/data/carfinder.sqlite3"
    upgrade_database(database)
    engine = create_database_engine(database)
    with Session(engine) as session:
        session.add(SearchProfile(name="Golf diesel", filters_json={"makes": ["Volkswagen"], "fuel": ["diesel"]}))
        session.commit()
    engine.dispose()

    payload = {
        "url": "https://www.facebook.com/marketplace/item/123456789/",
        "title": "Volkswagen Golf V 1.9 TDI",
        "description": "Prvi vlasnik. Veliki servis urađen. Pozvati 0641234567.",
        "price_amount": 4300,
        "price_currency": "EUR",
        "make": "Volkswagen",
        "model": "Golf",
        "generation": "Golf V",
        "year": 2008,
        "fuel": "diesel",
        "mileage_km": 198000,
        "images": ["https://images.example/golf.jpg"],
    }
    runner = CliRunner()
    first = runner.invoke(app, ["import-json", "-"], input=json.dumps(payload))
    assert first.exit_code == 0, first.output
    unchanged = runner.invoke(app, ["import-json", "-"], input=json.dumps(payload))
    assert unchanged.exit_code == 0, unchanged.output
    payload.update(price_amount=4100, description="Prvi vlasnik. Veliki servis urađen pre 5000 km.")
    changed = runner.invoke(app, ["import-json", "-"], input=json.dumps(payload))
    assert changed.exit_code == 0, changed.output

    engine = create_database_engine(database)
    try:
        with Session(engine) as session:
            listing = session.scalar(select(Listing))
            assert listing is not None and listing.provider == "manual_import"
            snapshots = session.scalars(select(ListingSnapshot).where(ListingSnapshot.listing_id == listing.id)).all()
            assert len(snapshots) == 2
            assert snapshots[-1].description.endswith("5000 km.")
            assert "0641234567" not in snapshots[0].description
            assert snapshots[0].provider_payload_json == {}
            assert session.scalar(select(func.count()).select_from(ListingEvent).where(ListingEvent.listing_id == listing.id, ListingEvent.event_type == "price_dropped")) == 1
            assert session.scalar(select(func.count()).select_from(ListingEvent).where(ListingEvent.listing_id == listing.id, ListingEvent.event_type == "description_changed")) == 1
            claim = session.scalar(select(ListingClaim).where(ListingClaim.listing_id == listing.id, ListingClaim.snapshot_id == snapshots[-1].id))
            assert claim is not None and claim.verification_status == "claimed"
            assert claim.source_type == "seller_description"
            assert session.scalar(select(ListingAnalysis).where(ListingAnalysis.snapshot_id == snapshots[-1].id)).status == "complete"
            assert session.scalar(select(ListingValuation).where(ListingValuation.snapshot_id == snapshots[-1].id)) is not None
            assert session.scalar(select(ListingScore).where(ListingScore.snapshot_id == snapshots[-1].id)) is not None
            match = session.scalar(select(ProfileListingMatch).where(ProfileListingMatch.listing_id == listing.id))
            assert match is not None and match.hard_filter_pass is True
            assert session.scalar(select(func.count()).select_from(Listing)) == 1
            assert session.scalar(select(func.count()).select_from(ScrapeRun).where(ScrapeRun.trigger == "manual_import")) == 3
    finally:
        engine.dispose()
