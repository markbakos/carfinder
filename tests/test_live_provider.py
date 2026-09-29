from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from carfinder.providers.base import ProviderSearchSource, RunContext
from carfinder.providers.polovniautomobili.provider import PolovniAutomobiliProvider


@pytest.mark.live_provider
@pytest.mark.skipif(not os.environ.get("CARFINDER_LIVE_SEARCH_URL"), reason="set CARFINDER_LIVE_SEARCH_URL to opt in")
def test_polovni_search_page_returns_listing_identities(tmp_path: Path) -> None:
    search_url = os.environ["CARFINDER_LIVE_SEARCH_URL"]
    provider = PolovniAutomobiliProvider()
    source = ProviderSearchSource(provider=provider.provider_id, search_url=search_url)
    result = provider.validate_source(source)
    assert result.valid, result.message
    context = RunContext(browser_profile=tmp_path / "browser", request_delay_seconds=2.5)

    async def scan() -> list[tuple[str, str]]:
        await provider.open_run(context)
        try:
            return [(item.external_id, item.url) async for item in provider.search(source, context)]
        finally:
            await provider.close_run()

    listings = asyncio.run(scan())
    assert listings
    assert all(
        listing_id
        and (urlsplit(url).hostname or "").endswith("polovniautomobili.com")
        and "/auto-oglasi/" in urlsplit(url).path
        for listing_id, url in listings
    )
