from __future__ import annotations

from carfinder.providers.base import ListingProvider
from carfinder.providers.polovniautomobili.provider import PolovniAutomobiliProvider

_PROVIDERS: dict[str, type[ListingProvider]] = {
    "polovniautomobili": PolovniAutomobiliProvider,
}


def get_provider(provider_id: str) -> ListingProvider:
    try:
        provider = _PROVIDERS[provider_id]
    except KeyError as error:
        raise ValueError(f"Unknown listing provider: {provider_id}") from error
    return provider()


def list_providers() -> list[ListingProvider]:
    return [provider() for provider in _PROVIDERS.values()]
