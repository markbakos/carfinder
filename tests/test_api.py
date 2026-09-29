from __future__ import annotations

import asyncio
from datetime import datetime, timezone

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
            created = await client.post("/api/profiles", json={
                "name": "Golf V diesel",
                "filters": {"makes": ["Volkswagen"], "models": ["Golf"], "fuel": ["diesel"]},
            })
            assert created.status_code == 201, created.text
            profile = created.json()
            assert profile["filters"]["fuel"] == ["diesel"]
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
            history = await client.get(f"/api/listings/{listing_id}/history")
            assert len(history.json()["snapshots"]) == 1
            assert history.json()["events"][0]["type"] == "price_dropped"
            state = await client.patch(f"/api/listings/{listing_id}/user-state", json={
                "state": "watching", "notes": "Ask for service invoices",
            })
            assert state.json()["state"] == "watching"
            assert state.json()["notes"] == "Ask for service invoices"
            assert (await client.get("/api/listings", params={"user_state": "watching"})).json()["total"] == 1
            assert (await client.get("/api/stats")).json()["listings_total"] == 1

    asyncio.run(exercise())
