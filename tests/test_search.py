from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from carfinder.providers.base import ProviderSearchSource, RunContext
from carfinder.providers.polovniautomobili.provider import PolovniAutomobiliProvider, _native_search_urls
from carfinder.providers.polovniautomobili.parser import extract_search_page_count
from carfinder.search import HardFilters, matches_filters


def test_filter_dimensions_are_or_but_dimensions_are_and() -> None:
    filters = HardFilters.model_validate({"makes": ["BMW", "Volkswagen"], "fuel": ["diesel"]})
    assert matches_filters(filters, {"make": " volkswagen ", "fuel": "Diesel"})
    assert not matches_filters(filters, {"make": "Audi", "fuel": "Diesel"})
    assert not matches_filters(filters, {"make": "BMW", "fuel": "petrol"})
    assert not matches_filters(filters, {"make": None, "fuel": "diesel"})


def test_numeric_ranges_include_bounds_and_require_known_values() -> None:
    filters = HardFilters.model_validate({"year": {"min": 2004, "max": 2009}, "price": {"max": 5500}})
    values = {"year": 2004, "price_amount": 5500, "price_currency": "EUR"}
    assert matches_filters(filters, values)
    assert not matches_filters(filters, {**values, "year": None})
    assert not matches_filters(filters, {**values, "price_currency": "RSD"})
    assert not matches_filters(filters, {**values, "price_amount": 5501})


def test_invalid_filter_ranges_are_rejected() -> None:
    with pytest.raises(ValidationError):
        HardFilters.model_validate({"year": {"min": 2010, "max": 2000}})
    with pytest.raises(ValidationError):
        HardFilters.model_validate({"year": {}})
    with pytest.raises(ValidationError):
        HardFilters.model_validate({"unreviewed_dimension": ["x"]})


def test_native_search_urls_split_brands_and_keep_supported_ranges() -> None:
    urls = _native_search_urls({
        "makes": ["Volkswagen", "Mercedes-Benz"],
        "models": ["Golf"],
        "year": {"min": 2004, "max": 2009},
        "price": {"max": 5500, "currency": "EUR"},
    })
    assert len(urls) == 2
    assert "brand=volkswagen" in urls[0]
    assert "brand=mercedes-benz" in urls[1]
    assert all("model%5B%5D=golf" in url and "year_from=2004" in url and "price_to=5500" in url for url in urls)


def test_search_scans_every_result_page_and_deduplicates_ids() -> None:
    fixtures = Path(__file__).parent / "fixtures/providers/polovniautomobili"
    expected = json.loads((fixtures / "search_pages.expected.json").read_text())
    html_by_page = {
        page: (fixtures / f"search_page_{page}.html").read_text()
        for page in range(1, expected["page_count"] + 1)
    }
    requested: list[str] = []

    class Fetcher:
        async def get(self, url: str) -> str:
            requested.append(url)
            page = int(url.split("page=")[-1])
            return html_by_page[page]

    async def collect() -> list[str]:
        provider = PolovniAutomobiliProvider()
        provider._fetcher = Fetcher()
        source = ProviderSearchSource(
            provider="polovniautomobili",
            search_url="https://www.polovniautomobili.com/auto-oglasi/pretraga?brand=volkswagen&page=9",
        )
        return [listing.external_id async for listing in provider.search(source, RunContext(browser_profile=fixtures))]

    listing_ids = asyncio.run(collect())
    assert listing_ids == expected["listing_ids"]
    assert [int(url.split("page=")[-1]) for url in requested] == list(range(1, expected["page_count"] + 1))
    assert extract_search_page_count(html_by_page[1], requested[0]) == expected["page_count"]
