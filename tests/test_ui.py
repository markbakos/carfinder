from __future__ import annotations

import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import uvicorn
from sqlalchemy.orm import Session

from carfinder.api.app import create_app
from carfinder.config import Settings
from carfinder.db.engine import create_database_engine
from carfinder.db.migrations import upgrade_database
from carfinder.db.models import Listing, ListingAnalysis, ListingSnapshot, ProfileListingMatch, ProviderSource, ScrapeRun, SearchProfile


def test_local_ui_core_workflows(monkeypatch, tmp_path) -> None:
    frontend = Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html"
    if not frontend.is_file():
        pytest.skip("build the Vite frontend before running UI smoke coverage")
    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / "runtime"))
    settings = Settings.load()
    upgrade_database(settings.database_path)
    engine = create_database_engine(settings.database_path)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(engine) as session:
        profile = SearchProfile(name="Seed profile", filters_json={"makes": ["Volkswagen"]}, preferences_json={})
        session.add(profile)
        session.flush()
        session.add(ProviderSource(profile_id=profile.id, provider="polovniautomobili", search_url=None))
        for index in (1, 2):
            listing = Listing(provider="polovniautomobili", external_id=f"ui-{index}", url=f"https://www.polovniautomobili.com/auto-oglasi/ui-{index}", first_seen_at=now, last_seen_at=now)
            session.add(listing)
            session.flush()
            snapshot = ListingSnapshot(
                listing_id=listing.id, content_hash=f"{index:064x}", title=f"Volkswagen Golf V 1.9 TDI {index}",
                description="Seller description with service details.", price_amount=4000 + index * 100,
                price_currency="EUR", year=2008, make="Volkswagen", model="Golf", generation="Golf V",
                mileage_km=190000, fuel="diesel", engine_cc=1896, power_kw=77,
                transmission="manual_5", location_raw="Novi Sad", features_json=["air_conditioning"], images_json=[],
            )
            session.add(snapshot)
            session.flush()
            listing.current_snapshot_id = snapshot.id
            session.add(ProfileListingMatch(profile_id=profile.id, listing_id=listing.id, hard_filter_pass=True))
            session.add(ListingAnalysis(
                listing_id=listing.id, snapshot_id=snapshot.id, semantic_hash=f"{index:064x}", status="complete",
                result_json={"positive_claims": [], "concerns": [], "missing_information": [], "questions_to_ask": [], "extracted_claims": [], "risk_signals": []},
            ))
        session.add(ScrapeRun(started_at=now, finished_at=now, status="success", trigger="cli", hostname="ui-test", profiles_processed=1, sources_processed=1, listings_seen=2, listings_new=2))
        session.commit()
    engine.dispose()

    app = create_app(settings)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        listener.settimeout(0.2)
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            if server.started:
                break
            time.sleep(0.1)
        assert server.started, "local API did not start"

        from playwright.sync_api import Error as PlaywrightError, sync_playwright

        try:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(headless=True)
                except PlaywrightError as error:
                    pytest.skip(f"install Playwright Chromium to run UI smoke coverage: {error}")
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.goto(base_url, wait_until="networkidle")
                assert page.get_by_role("heading", name="Good morning.").is_visible()
                page.get_by_role("link", name="Listings", exact=True).click()
                title = "Volkswagen Golf V 1.9 TDI 1"
                page.get_by_role("link", name=title, exact=True).click()
                page.get_by_text("Seller description with service details.").wait_for(state="visible")
                page.get_by_label("Shopping state").select_option("watching")
                page.get_by_label("Notes").fill("Ask about the service invoice")
                page.get_by_role("button", name="Save decision").click()
                page.get_by_role("status").filter(has_text="Shopping notes saved").wait_for()
                page.reload(wait_until="networkidle")
                assert page.get_by_label("Shopping state").input_value() == "watching"

                page.get_by_role("link", name="All listings").click()
                page.get_by_label(f"Select {title} for comparison").check()
                page.get_by_label("Select Volkswagen Golf V 1.9 TDI 2 for comparison").check()
                page.get_by_role("link", name="Compare 2 cars").click()
                page.get_by_role("heading", name="2 selected cars").wait_for(state="visible")

                page.get_by_role("link", name="Search profiles", exact=True).click()
                page.get_by_role("button", name="New profile").click()
                page.get_by_label("Profile name").fill("Created from browser")
                page.get_by_label("Makes").fill("Volkswagen")
                page.get_by_role("button", name="Save profile").click()
                page.get_by_role("heading", name="Created from browser").wait_for(state="visible")

                page.get_by_role("link", name="Runs", exact=True).click()
                page.get_by_role("button", name="Run #1").click()
                page.get_by_text("No warnings or errors were recorded.").wait_for(state="visible")
                page.goto(f"{base_url}/listings/1", wait_until="networkidle")
                page.get_by_role("heading", name=title).wait_for(state="visible")
                page.goto(f"{base_url}/import", wait_until="networkidle")
                page.get_by_label("Listing JSON").fill('''{
                  "url": "https://www.facebook.com/marketplace/item/ui-import-1/",
                  "title": "Manual import example",
                  "description": "Seller claims the major service was performed.",
                  "make": "Volkswagen",
                  "model": "Golf",
                  "price_amount": 3900,
                  "price_currency": "EUR"
                }''')
                with page.expect_response("**/api/import") as import_response:
                    page.get_by_role("button", name="Import listing").click()
                response = import_response.value
                assert response.status == 201, response.text()
                page.get_by_role("heading", name="Manual import example").wait_for(state="visible")
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=5)
