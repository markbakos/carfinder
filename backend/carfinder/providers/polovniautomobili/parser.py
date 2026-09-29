from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from carfinder.privacy import redact_contact_details
from carfinder.providers.base import DiscoveredListing, NormalizedListing, RawListing

_AD_PATH = re.compile(r"^/auto-oglasi/(?P<id>\d+)(?:/[^/]+)?/?$")
_NUMBER = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})+|\d{3,7})(?!\d)")
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_DIACRITICS = str.maketrans({"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "dj"})
_CURRENCY_MARKERS = {
    "€": "EUR",
    "eur": "EUR",
    "евр": "EUR",
    "rsd": "RSD",
    "дин": "RSD",
    "din": "RSD",
}
_FIELD_NAMES = {
    "marka": "make",
    "proizvodjac": "make",
    "model": "model",
    "godiste": "year",
    "kilometraza": "mileage_km",
    "gorivo": "fuel",
    "kubikaza": "engine_cc",
    "snaga": "power_kw",
    "menjac": "transmission",
    "pogon": "drive",
    "karoserija": "body_type",
    "broj vrata": "doors",
    "broj sedišta": "seats",
    "broj sedista": "seats",
    "ostecenje": "damage",
    "poreklo vozila": "origin",
    "vrsta prodavca": "seller_type",
    "tip prodavca": "seller_type",
    "cena": "price",
}


def _norm(value: str) -> str:
    return " ".join(value.translate(_DIACRITICS).lower().split())


def _listing_path(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "polovniautomobili.com" or host.endswith(".polovniautomobili.com")):
        return None
    match = _AD_PATH.fullmatch(parsed.path)
    if not match:
        return None
    clean = urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/"), "", ""))
    return match.group("id"), clean


def extract_discovered_listings(html: str, base_url: str) -> list[DiscoveredListing]:
    """Extract unique listing IDs and URLs from a Polovni search result page."""
    soup = BeautifulSoup(html, "lxml")
    seen: dict[str, DiscoveredListing] = {}
    for anchor in soup.select("a[href]"):
        candidate = _listing_path(urljoin(base_url, str(anchor.get("href", ""))))
        if candidate is None:
            continue
        external_id, url = candidate
        if external_id not in seen:
            title = anchor.get_text(" ", strip=True) or None
            seen[external_id] = DiscoveredListing(
                provider="polovniautomobili", external_id=external_id, url=url, title=title
            )
    return list(seen.values())


def is_explicitly_empty_search(html: str) -> bool:
    text = _norm(BeautifulSoup(html, "lxml").get_text(" ", strip=True))
    return any(marker in text for marker in (
        "nema rezultata", "nema oglasa", "nismo pronasli", "nisu pronadjeni oglasi",
        "0 rezultata", "0 oglasa",
    ))


def _jsonld(soup: BeautifulSoup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        pending = value if isinstance(value, list) else [value]
        while pending:
            item = pending.pop(0)
            if isinstance(item, list):
                pending[0:0] = item
            elif isinstance(item, dict):
                yield item


def _field_rows(soup: BeautifulSoup) -> dict[str, str]:
    fields: dict[str, str] = {}
    for row in soup.select('[class*="InfoCardListItem"], [data-testid*="spec"]'):
        children = row.select('[class*="ItemKey"], dt')
        values = row.select('[class*="ItemValue"], dd')
        if not children or not values:
            parts = row.find_all(["span", "strong"], recursive=False)
            if len(parts) >= 2:
                children, values = parts[:1], parts[1:2]
        if children and values:
            key = children[0].get_text(" ", strip=True).strip().rstrip(":").strip()
            value = values[0].get_text(" ", strip=True)
            if key and value:
                fields[key] = value
    return fields


def _jsonld_location(soup: BeautifulSoup) -> str | None:
    for item in _jsonld(soup):
        address = item.get("address")
        if isinstance(address, dict):
            locality = address.get("addressLocality")
            if isinstance(locality, str) and locality.strip():
                return locality.strip()
    return None


def _description(soup: BeautifulSoup) -> str:
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        if _norm(heading.get_text(" ", strip=True)).rstrip(":") == "opis":
            container = heading.find_next_sibling()
            if container:
                value = container.get_text(" ", strip=True)
                if value:
                    return value
    node = soup.select_one('[data-testid="descriptionContent"], [class*="InfoCardText"]')
    return node.get_text(" ", strip=True) if node else ""


def _price(soup: BeautifulSoup, structured: list[dict[str, object]]) -> str | None:
    for selector in ('[class*="FormattedPrice"]', '[data-testid*="price"]', 'meta[property="product:price:amount"]'):
        node = soup.select_one(selector)
        if node:
            value = node.get("content") or node.get_text(" ", strip=True)
            if value:
                return str(value)
    for item in structured:
        offer = item.get("offers")
        if isinstance(offer, list):
            offer = next((entry for entry in offer if isinstance(entry, dict)), None)
        if isinstance(offer, dict) and offer.get("price") is not None:
            currency = offer.get("priceCurrency") or ""
            return f"{offer['price']} {currency}"
    return None


def _images(soup: BeautifulSoup, page_url: str) -> list[str]:
    urls: list[str] = []
    for node in soup.select("main img[src], main img[data-src], main img[srcset], meta[property='og:image']"):
        raw = node.get("content") or node.get("data-src") or node.get("src")
        if not raw and node.get("srcset"):
            raw = str(node["srcset"]).split(",", 1)[0].strip().split(" ", 1)[0]
        if not raw or raw.startswith("data:"):
            continue
        value = urljoin(page_url, str(raw))
        if value not in urls and urlsplit(value).scheme in {"http", "https"}:
            urls.append(value)
    return urls


def _features(soup: BeautifulSoup) -> list[str]:
    features: list[str] = []
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        if _norm(heading.get_text(" ", strip=True)).rstrip(":") not in {
            "oprema", "dodatna oprema", "bezbednost", "sigurnost"
        }:
            continue
        section = heading.find_parent("section")
        if section is None:
            continue
        candidates = section.select("li, [class*=Feature], [data-testid*=feature]")
        for item in candidates:
            value = item.get_text(" ", strip=True)
            if value and value not in features:
                features.append(value)
    return features


def parse_listing(html: str, url: str, external_id: str) -> RawListing:
    soup = BeautifulSoup(html, "lxml")
    structured_items = list(_jsonld(soup))
    heading = soup.select_one('h1[data-testid="adTitleDesktop"], main h1, h1')
    title = heading.get_text(" ", strip=True) if heading else None
    fields = _field_rows(soup)
    location = _jsonld_location(soup)
    features = _features(soup)
    if location is None:
        node = soup.select_one('[class*="SellerCity"], [class*="SellerLocation"]')
        location = node.get_text(" ", strip=True) if node else None

    # Remove executable and non-visible content before storing provider-derived text.
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    description = redact_contact_details(_description(soup))
    if not description and not soup.select_one('h2, h3'):
        description = ""

    price_raw = _price(soup, structured_items) or _find(fields, "price")

    payload: dict[str, object] = {}
    for item in structured_items:
        if item.get("@type") in {"Car", "Vehicle", "Product", "IndividualProduct"}:
            payload = {key: item[key] for key in ("@type", "name", "brand", "model", "vehicleModelDate", "mileageFromOdometer") if key in item}
            break

    return RawListing(
        provider="polovniautomobili",
        external_id=external_id,
        url=url,
        title=redact_contact_details(title or "") or None,
        description=description,
        asking_price_raw=price_raw,
        fields=fields,
        location_raw=location,
        features=features,
        images=_images(soup, url),
        provider_payload=payload,
    )


def _canonical_seller_type(raw: str | None) -> str | None:
    if not raw:
        return None
    value = _norm(raw)
    if "fizick" in value or "privat" in value:
        return "private"
    if "prav" in value or "diler" in value or "auto plac" in value or "salon" in value:
        return "dealer"
    return None


def _canonical_drive(raw: str | None) -> str | None:
    if not raw:
        return None
    value = _norm(raw)
    if "4x4" in value or "4wd" in value or "sva 4" in value:
        return "4wd"
    if "prednji" in value or "fwd" in value:
        return "fwd"
    if "zadnji" in value or "rwd" in value:
        return "rwd"
    return None


def _number(value: str | None) -> int | None:
    if not value:
        return None
    match = _NUMBER.search(value)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    try:
        return int(digits)
    except ValueError:
        return None


def _price_value(raw: str | None) -> tuple[int | None, str | None]:
    if not raw:
        return None, None
    lowered = raw.lower()
    currency = next((code for marker, code in _CURRENCY_MARKERS.items() if marker in lowered), None)
    match = _NUMBER.search(raw)
    if not match:
        return None, currency
    try:
        return int(re.sub(r"\D", "", match.group(1))), currency
    except ValueError:
        return None, currency


def _canonical_fuel(raw: str | None) -> str | None:
    if not raw:
        return None
    value = _norm(raw)
    for marker, canonical in (
        ("dizel", "diesel"), ("benzin", "petrol"), ("hibrid", "hybrid"),
        ("plug-in", "plug_in_hybrid"), ("elektro", "electric"),
        ("tng", "lpg"), ("lpg", "lpg"), ("cng", "cng"), ("metan", "cng"),
    ):
        if marker in value:
            return canonical
    return None


def _canonical_transmission(raw: str | None) -> str | None:
    if not raw:
        return None
    value = _norm(raw)
    if "automat" in value or "automatic" in value:
        return "automatic"
    if "manuel" in value or "manual" in value:
        return "manual"
    return None


def _canonical_body(raw: str | None) -> str | None:
    if not raw:
        return None
    value = _norm(raw)
    for marker, canonical in (
        ("suv", "suv"), ("dzip", "suv"), ("limuz", "sedan"),
        ("hecbek", "hatchback"), ("hatchback", "hatchback"),
        ("karavan", "wagon"), ("coupe", "coupe"), ("kabrio", "convertible"),
        ("monovol", "mpv"), ("pickup", "pickup"), ("minibus", "minibus"),
    ):
        if marker in value:
            return canonical
    return None


def _find(fields: dict[str, str], canonical: str) -> str | None:
    for key, value in fields.items():
        if _FIELD_NAMES.get(_norm(key)) == canonical:
            return value
    return None


def normalize_listing(raw: RawListing) -> NormalizedListing:
    price, currency = _price_value(raw.asking_price_raw)
    fields = raw.fields
    year_text = _find(fields, "year")
    year_match = _YEAR.search(year_text or "")
    make = _find(fields, "make")
    model = _find(fields, "model")
    transmission_raw = _find(fields, "transmission")
    damage = _find(fields, "damage")
    origin = _find(fields, "origin")
    structured = {
        "raw_fields": fields,
        "raw_price": raw.asking_price_raw,
        "raw_transmission": transmission_raw,
        "raw_fuel": _find(fields, "fuel"),
        "raw_engine_cc": _find(fields, "engine_cc"),
        "raw_power": _find(fields, "power_kw"),
        "raw_location": raw.location_raw,
    }
    if damage:
        structured["damage_claim"] = damage
    if origin:
        structured["origin_claim"] = origin

    return NormalizedListing(
        provider=raw.provider,
        external_id=raw.external_id,
        url=raw.url,
        title=raw.title,
        description=raw.description,
        price_amount=price,
        price_currency=currency,
        make=make,
        model=model,
        year=int(year_match.group(1)) if year_match else None,
        fuel=_canonical_fuel(_find(fields, "fuel")),
        mileage_km=_number(_find(fields, "mileage_km")),
        engine_cc=_number(_find(fields, "engine_cc")),
        power_kw=_number(_find(fields, "power_kw")),
        transmission=_canonical_transmission(transmission_raw),
        drive=_canonical_drive(_find(fields, "drive")),
        body_type=_canonical_body(_find(fields, "body_type")),
        location_raw=raw.location_raw,
        city=raw.location_raw,
        seller_type=_canonical_seller_type(_find(fields, "seller_type")),
        features=raw.features,
        condition={key: value for key, value in (("damage", damage), ("origin", origin)) if value},
        images=raw.images,
        structured=structured,
        provider_payload=raw.provider_payload,
    )
