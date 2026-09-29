from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import ConfigDict, Field, HttpUrl, field_validator, model_validator

from carfinder.privacy import redact_contact_details
from carfinder.providers.base import NormalizedListing


class ManualListingImport(NormalizedListing):
    """Validated canonical listing data supplied by the user, without page fetching."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["manual_import"] = "manual_import"
    external_id: str | None = Field(default=None, min_length=1, max_length=200)
    url: HttpUrl
    title: str | None = Field(default=None, max_length=300)
    description: str = Field(default="", max_length=100_000)
    price_amount: int | None = Field(default=None, ge=0, le=1_000_000_000)
    price_currency: Literal["EUR", "RSD"] | None = None
    year: int | None = Field(default=None, ge=1886, le=2100)
    mileage_km: int | None = Field(default=None, ge=0, le=5_000_000)
    engine_cc: int | None = Field(default=None, ge=0, le=20_000)
    power_kw: int | None = Field(default=None, ge=0, le=2_000)
    make: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    generation: str | None = Field(default=None, max_length=120)
    trim: str | None = Field(default=None, max_length=160)
    fuel: str | None = Field(default=None, max_length=32)
    transmission: str | None = Field(default=None, max_length=32)
    drive: str | None = Field(default=None, max_length=24)
    body_type: str | None = Field(default=None, max_length=48)
    location_raw: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    seller_type: str | None = Field(default=None, max_length=32)
    features: list[str] = Field(default_factory=list, max_length=100)
    images: list[HttpUrl] = Field(default_factory=list, max_length=25)
    structured: dict[str, Any] = Field(default_factory=dict, exclude=True)
    condition: dict[str, Any] = Field(default_factory=dict, exclude=True)
    provider_payload: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @field_validator("url")
    @classmethod
    def reject_url_credentials(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password:
            raise ValueError("source URL must not contain credentials")
        return value

    @field_validator("external_id")
    @classmethod
    def clean_external_id(cls, value: str | None) -> str | None:
        cleaned = value.strip() if value else value
        if value is not None and not cleaned:
            raise ValueError("external_id must not be blank")
        return cleaned

    @field_validator("features")
    @classmethod
    def bound_feature_text(cls, value: list[str]) -> list[str]:
        if any(len(feature) > 160 for feature in value):
            raise ValueError("feature values must be 160 characters or fewer")
        return value

    @model_validator(mode="after")
    def require_listing_content(self) -> ManualListingImport:
        if not (self.title or self.description.strip() or self.make or self.model):
            raise ValueError("provide a title, description, or make/model")
        return self

    def to_normalized(self) -> NormalizedListing:
        values: dict[str, Any] = self.model_dump(mode="json", exclude={"provider_payload"})
        values["url"] = str(self.url)
        values["external_id"] = self.external_id or hashlib.sha256(values["url"].encode()).hexdigest()
        values["title"] = redact_contact_details(values["title"] or "") or None
        values["description"] = redact_contact_details(values["description"])
        values.update(structured={}, condition={}, provider_payload={})
        return NormalizedListing.model_validate(values)
