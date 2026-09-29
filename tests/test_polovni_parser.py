from __future__ import annotations

import json
from pathlib import Path

from carfinder.providers.polovniautomobili.parser import (
    extract_discovered_listings,
    is_explicitly_empty_search,
    normalize_listing,
    parse_listing,
)

FIXTURES = Path(__file__).parent / "fixtures/providers/polovniautomobili"


def _expected(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _normalized_fixture(name: str, listing_id: str):
    html = (FIXTURES / name).read_text(encoding="utf-8")
    url = f"https://www.polovniautomobili.com/auto-oglasi/{listing_id}/fixture"
    return normalize_listing(parse_listing(html, url, listing_id))


def test_detail_parser_uses_labeled_specs_and_jsonld_location() -> None:
    actual = _normalized_fixture("listing_01.html", "10000000").model_dump()
    expected = _expected("listing_01.expected.json")
    for key, value in expected.items():
        if key == "description_contains":
            assert value in actual["description"]
        elif key == "contact_markers":
            for marker in value:
                assert marker in actual["description"]
        else:
            assert actual[key] == value
    assert "01.06.2025" in actual["description"]
    assert "__NOISE__" not in actual["description"]
    assert actual["structured"]["raw_fields"]["Menjač"] == "Automatski / poluautomatski"


def test_missing_price_description_and_old_manual_damaged_car() -> None:
    actual = _normalized_fixture("listing_02.html", "10000002").model_dump()
    expected = _expected("listing_02.expected.json")
    comparable = {key: actual[key] for key in expected if key != "damage_claim"}
    expected_comparable = {key: value for key, value in expected.items() if key != "damage_claim"}
    assert comparable == expected_comparable
    assert actual["condition"]["damage"] == expected["damage_claim"]


def test_search_links_are_unique_and_provider_scoped() -> None:
    html = (FIXTURES / "search_01.html").read_text(encoding="utf-8")
    actual = [item.model_dump() for item in extract_discovered_listings(
        html, "https://www.polovniautomobili.com/auto-oglasi/pretraga"
    )]
    assert actual == _expected("search_01.expected.json")


def test_empty_search_requires_an_explicit_no_results_message() -> None:
    assert is_explicitly_empty_search("<main>Nema oglasa za izabrane filtere</main>")
    assert not is_explicitly_empty_search("<main>Unexpected blank provider response</main>")
