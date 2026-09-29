from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
from sqlalchemy.orm import Session

from carfinder.api.app import create_app
from carfinder.config import Settings
from carfinder.db.engine import create_database_engine
from carfinder.db.migrations import upgrade_database
from carfinder.db.models import (
    Listing,
    ListingEvent,
    ListingSnapshot,
    ProfileListingMatch,
    SearchProfile,
)


def test_profile_listing_history_and_user_state_api(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / "runtime"))
    settings = Settings.load()
    upgrade_database(settings.database_path)
    app = create_app(settings)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            settings_response = await client.get("/api/settings")
            assert settings_response.status_code == 200
            assert settings_response.json()["database_path"].endswith("carfinder.sqlite3")
            assert "command" not in settings_response.json()["llm"]
            created = await client.post("/api/profiles", json={
                "name": "Golf V diesel",
                "filters": {"makes": ["Volkswagen"], "models": ["Golf"], "fuel": ["diesel"]},
                "preferences": {"mileage_km": {"ideal_max": 180000}, "equipment": {"prefer": ["cruise_control"]}},
            })
            assert created.status_code == 201, created.text
            profile = created.json()
            assert profile["filters"]["fuel"] == ["diesel"]
            assert profile["preferences"]["mileage_km"]["ideal_max"] == 180000
            assert profile["sources"][0]["search_url"] is None
            assert (await client.get("/api/profiles")).json()[0]["id"] == profile["id"]

            engine = create_database_engine(settings.database_path)
            try:
                with Session(engine) as session:
                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                    listing = Listing(
                        provider="polovniautomobili", external_id="api-1",
                        url="https://www.polovniautomobili.com/auto-oglasi/api-1/test",
                        first_seen_at=now, last_seen_at=now,
                    )
                    session.add(listing)
                    session.flush()
                    snapshot = ListingSnapshot(
                        listing_id=listing.id, content_hash="a" * 64,
                        title="Volkswagen Golf V 1.9 TDI", description="Seller description",
                        price_amount=4300, price_currency="EUR", make="Volkswagen", model="Golf",
                        generation="Golf V", year=2008, fuel="diesel", mileage_km=198000,
                        city="Novi Sad", features_json=["air_conditioning"], images_json=["https://images.example/1.jpg"],
                    )
                    session.add(snapshot)
                    session.flush()
                    listing.current_snapshot_id = snapshot.id
                    session.add(ProfileListingMatch(profile_id=profile["id"], listing_id=listing.id, hard_filter_pass=True))
                    session.add(ListingEvent(listing_id=listing.id, event_type="price_dropped", old_value_json={"amount": 4500}, new_value_json={"amount": 4300}))
                    listing_id = listing.id
                    session.commit()
            finally:
                engine.dispose()

            listing_response = await client.get(f"/api/listings/{listing_id}")
            assert listing_response.status_code == 200
            assert listing_response.json()["current"]["description"] == "Seller description"
            filtered = await client.get("/api/listings", params={"profile": profile["id"], "fuel": "diesel", "price_drop": "true"})
            assert filtered.json()["total"] == 1
            ranked = await client.get("/api/listings", params={"profile": profile["id"], "sort": "rank_desc"})
            assert ranked.json()["total"] == 1
            changed = await client.get("/api/listings", params={"sort": "changed"})
            assert changed.json()["items"][0]["id"] == listing_id
            assert (await client.get("/api/listings", params={"minimum_score": 0})).json()["total"] == 0
            history = await client.get(f"/api/listings/{listing_id}/history")
            assert len(history.json()["snapshots"]) == 1
            assert history.json()["events"][0]["type"] == "price_dropped"
            state = await client.patch(f"/api/listings/{listing_id}/user-state", json={
                "state": "watching", "notes": "Ask for service invoices",
            })
            assert state.json()["state"] == "watching"
            assert state.json()["notes"] == "Ask for service invoices"
            assert (await client.get("/api/listings", params={"user_state": "watching"})).json()["total"] == 1
            analysis_run = await client.post(f"/api/listings/{listing_id}/reanalyze")
            assert analysis_run.status_code == 200, analysis_run.text
            assert analysis_run.json()["listings_analyzed"] == 1
            analysis = await client.get(f"/api/listings/{listing_id}/analysis")
            assert analysis.json()["status"] == "complete"
            assert any(item["field"] == "vin" for item in analysis.json()["result"]["missing_information"])
            scored = (await client.get(f"/api/listings/{listing_id}", params={"profile": profile["id"]})).json()
            assert scored["market_value"]["confidence"] == "insufficient"
            assert scored["market_value"]["median_amount"] is None
            assert scored["profile_fit_score"] == 45
            assert scored["scores"]["quality_score"] is None
            matches = await client.get(f"/api/listings/{listing_id}/matches")
            assert matches.json()[0]["profile_fit_explanation"]["preferences"]
            stats = (await client.get("/api/stats")).json()
            assert stats["listings_total"] == 1
            assert stats["strong_deals"] == 0
            runs = await client.get("/api/runs")
            assert any(item["trigger"] == "analyze" for item in runs.json()["items"])

    asyncio.run(exercise())


def test_manual_import_api_is_idempotent_and_validates_input(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / "runtime"))
    settings = Settings.load()
    upgrade_database(settings.database_path)
    app = create_app(settings)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            payload = {
                "url": "https://www.facebook.com/marketplace/item/api-import-1/",
                "title": "Manual Marketplace listing",
                "description": "Seller says the major service was done.",
                "price_amount": 4100,
                "price_currency": "EUR",
                "make": "Volkswagen",
                "model": "Golf",
            }
            imported = await client.post("/api/import", json=payload)
            assert imported.status_code == 201, imported.text
            result = imported.json()
            assert result["snapshot_created"] is True
            repeated = await client.post("/api/import", json=payload)
            assert repeated.status_code == 201, repeated.text
            assert repeated.json()["listing_id"] == result["listing_id"]
            assert repeated.json()["snapshot_created"] is False
            assert (await client.get("/api/listings", params={"provider": "manual_import"})).json()["total"] == 1

            invalid = await client.post("/api/import", json={**payload, "year": 3000})
            assert invalid.status_code == 422

    asyncio.run(exercise())


def test_schedule_can_be_enabled_through_local_api(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / "runtime"))
    settings = Settings.load()
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="active", stderr="")

    monkeypatch.setattr("carfinder.api.routes.subprocess.run", run)
    app = create_app(settings)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/schedule", json={"calendar": "*-*-* 09:00:00"})
            assert response.status_code == 200, response.text
            assert response.json()["active"] is True
            assert calls[0][1:] == ["systemd", "install", "--calendar", "*-*-* 09:00:00"]
            assert calls[1] == ["/usr/bin/systemctl", "--user", "daemon-reload"]
            assert calls[2] == ["/usr/bin/systemctl", "--user", "enable", "--now", "carfinder.timer"]
            assert calls[3] == ["/usr/bin/systemctl", "--user", "restart", "carfinder.timer"]
            assert calls[4][2] == "is-enabled"
            assert calls[5][2] == "is-active"

    monkeypatch.setattr("carfinder.api.routes.sys.argv", ["pytest"])
    monkeypatch.setattr("carfinder.api.routes.shutil.which", lambda name: {
        "systemctl": "/usr/bin/systemctl", "carfinder": "/opt/carfinder/bin/carfinder",
    }.get(name))
    asyncio.run(exercise())
