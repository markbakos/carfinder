from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import urlsplit

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
    normalize_listing,
    parse_listing,
)


class PolovniAutomobiliProvider(ListingProvider):
    provider_id = "polovniautomobili"
    capabilities = ProviderCapabilities(
        supports_search_url=True,
        supports_description=True,
        supports_location=True,
        supports_images=True,
        supports_seller_metadata=True,
    )

    def __init__(self) -> None:
        self._fetcher: PlaywrightFetcher | None = None

    def validate_source(self, source: ProviderSearchSource) -> ValidationResult:
        parsed = urlsplit(source.search_url.strip())
        host = (parsed.hostname or "").lower()
        if source.provider != self.provider_id:
            return ValidationResult(valid=False, message="Source provider does not match PolovniAutomobili")
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
        del context
        result = self.validate_source(source)
        if not result.valid:
            raise ValueError(result.message)
        if self._fetcher is None:
            raise RuntimeError("Open a provider run before searching")
        html = await self._fetcher.get(source.search_url)
        discovered = extract_discovered_listings(html, source.search_url)
        if not discovered and not is_explicitly_empty_search(html):
            raise ProviderFetchError("Search page had no listing cards and no recognized empty-results message")
        for listing in discovered:
            yield listing

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
