from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ProviderCapabilities(BaseModel):
    supports_search_url: bool = False
    supports_native_filters: bool = False
    supports_description: bool = False
    supports_seller_metadata: bool = False
    supports_posted_at: bool = False
    supports_price_history_from_source: bool = False
    supports_location: bool = False
    supports_images: bool = False


class ProviderSearchSource(BaseModel):
    id: int | None = None
    provider: str
    search_url: str
    profile_id: int | None = None


class ValidationResult(BaseModel):
    valid: bool
    message: str = ""


class RunContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    browser_profile: Path
    headless: bool = True
    request_delay_seconds: float = Field(default=2.5, ge=0)
    timeout_seconds: int = Field(default=45, ge=1)


class DiscoveredListing(BaseModel):
    provider: str
    external_id: str
    url: str
    title: str | None = None


class RawListing(BaseModel):
    provider: str
    external_id: str
    url: str
    title: str | None = None
    description: str = ""
    asking_price_raw: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)
    location_raw: str | None = None
    features: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    provider_payload: dict[str, Any] = Field(default_factory=dict)


class NormalizedListing(BaseModel):
    provider: str
    external_id: str
    url: str
    title: str | None = None
    description: str = ""
    price_amount: int | None = None
    price_currency: str | None = None
    make: str | None = None
    model: str | None = None
    generation: str | None = None
    trim: str | None = None
    year: int | None = None
    fuel: str | None = None
    mileage_km: int | None = None
    engine_cc: int | None = None
    power_kw: int | None = None
    transmission: str | None = None
    drive: str | None = None
    body_type: str | None = None
    doors: int | None = None
    seats: int | None = None
    location_raw: str | None = None
    city: str | None = None
    region: str | None = None
    seller_type: str | None = None
    features: list[str] = Field(default_factory=list)
    condition: dict[str, Any] = Field(default_factory=dict)
    images: list[str] = Field(default_factory=list)
    structured: dict[str, Any] = Field(default_factory=dict)
    provider_payload: dict[str, Any] = Field(default_factory=dict)


class ListingProvider(Protocol):
    provider_id: str
    capabilities: ProviderCapabilities

    def validate_source(self, source: ProviderSearchSource) -> ValidationResult: ...

    async def open_run(self, context: RunContext) -> None: ...

    async def close_run(self) -> None: ...

    def search(
        self, source: ProviderSearchSource, context: RunContext
    ) -> AsyncIterator[DiscoveredListing]: ...

    async def fetch_listing(
        self, discovered: DiscoveredListing, context: RunContext
    ) -> RawListing: ...

    def normalize(self, raw: RawListing) -> NormalizedListing: ...
