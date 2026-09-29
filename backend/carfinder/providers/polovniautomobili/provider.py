from __future__ import annotations

from collections.abc import AsyncIterator
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from carfinder.providers.base import (
    DiscoveredListing,
    ListingProvider,
    NormalizedListing,
    ProviderCapabilities,
    ProviderSearchSource,
    RawListing,
    RunContext,
    ValidationResult,
)
from carfinder.providers.polovniautomobili.fetcher import PlaywrightFetcher, ProviderFetchError
from carfinder.providers.polovniautomobili.parser import (
    extract_discovered_listings,
    is_explicitly_empty_search,
    extract_search_page_count,
    normalize_listing,
    parse_listing,
)


class PolovniAutomobiliProvider(ListingProvider):
    provider_id = "polovniautomobili"
    capabilities = ProviderCapabilities(
        supports_search_url=True,
        supports_native_filters=True,
        supports_description=True,
        supports_location=True,
        supports_images=True,
        supports_seller_metadata=True,
    )

    def __init__(self) -> None:
        self._fetcher: PlaywrightFetcher | None = None

    def validate_source(self, source: ProviderSearchSource) -> ValidationResult:
        if source.provider != self.provider_id:
            return ValidationResult(valid=False, message="Source provider does not match PolovniAutomobili")
        if not source.search_url:
            return ValidationResult(valid=True)
        parsed = urlsplit(source.search_url.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (host == "polovniautomobili.com" or host.endswith(".polovniautomobili.com")):
            return ValidationResult(valid=False, message="Use an HTTPS PolovniAutomobili search URL")
        if parsed.username or parsed.password:
            return ValidationResult(valid=False, message="Search URLs must not contain credentials")
        if parsed.path != "/auto-oglasi/pretraga" and not parsed.path.startswith("/auto-oglasi/pretraga/"):
            return ValidationResult(valid=False, message="URL is not a PolovniAutomobili search page")
        return ValidationResult(valid=True)

    async def open_run(self, context: RunContext) -> None:
        if self._fetcher is not None:
            raise RuntimeError("Provider run is already open")
        self._fetcher = PlaywrightFetcher(context)
        await self._fetcher.start()

    async def close_run(self) -> None:
        if self._fetcher is not None:
            fetcher, self._fetcher = self._fetcher, None
            await fetcher.close()

    async def search(
        self, source: ProviderSearchSource, context: RunContext
    ) -> AsyncIterator[DiscoveredListing]:
        result = self.validate_source(source)
        if not result.valid:
            raise ValueError(result.message)
        if self._fetcher is None:
            raise RuntimeError("Open a provider run before searching")
        urls = [source.search_url] if source.search_url else _native_search_urls(source.native_filters)
        seen: set[str] = set()
        for search_url in urls:
            page = 1
            last_page = 1
            while page <= last_page:
                url = _search_page_url(search_url, page)
                html = await self._fetcher.get(url)
                last_page = max(last_page, extract_search_page_count(html, url))
                discovered = extract_discovered_listings(html, url)
                if not discovered and not is_explicitly_empty_search(html):
                    raise ProviderFetchError("Search page had no listing cards and no recognized empty-results message")
                for listing in discovered:
                    if listing.external_id not in seen:
                        seen.add(listing.external_id)
                        yield listing
                page += 1

    async def fetch_listing(
        self, discovered: DiscoveredListing, context: RunContext
    ) -> RawListing:
        del context
        if discovered.provider != self.provider_id:
            raise ValueError("Discovered listing belongs to another provider")
        if self._fetcher is None:
            raise RuntimeError("Open a provider run before fetching details")
        html = await self._fetcher.get(discovered.url)
        return parse_listing(html, discovered.url, discovered.external_id)

    def normalize(self, raw: RawListing) -> NormalizedListing:
        if raw.provider != self.provider_id:
            raise ValueError("Raw listing belongs to another provider")
        return normalize_listing(raw)


def _provider_slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return "-".join(part for part in "".join(char if char.isalnum() else " " for char in ascii_value).split() if part)


def _native_search_urls(filters: dict) -> list[str]:
    """Build conservative Polovni search URLs; remaining filters are enforced locally."""
    makes = filters.get("makes") or [None]
    params: list[tuple[str, str]] = [("city_distance", "0"), ("page", "1"), ("sort", "basic")]
    for key, lower, upper in (("year", "year_from", "year_to"), ("price", "price_from", "price_to")):
        value_range = filters.get(key) or {}
        if key == "price" and value_range.get("currency", "EUR") != "EUR":
            continue
        if value_range.get("min") is not None:
            params.append((lower, str(value_range["min"])))
        if value_range.get("max") is not None:
            params.append((upper, str(value_range["max"])))
    models = filters.get("models") or []
    urls = []
    for make in makes:
        query = list(params)
        if make:
            query.append(("brand", _provider_slug(make)))
        query.extend(("model[]", _provider_slug(model)) for model in models)
        urls.append("https://www.polovniautomobili.com/auto-oglasi/pretraga?" + urlencode(query))
    return urls


def _search_page_url(search_url: str, page: int) -> str:
    parsed = urlsplit(search_url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "page"]
    query.append(("page", str(page)))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), ""))
