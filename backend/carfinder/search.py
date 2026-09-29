from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ValueRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def ordered(self) -> ValueRange:
        if self.min is None and self.max is None:
            raise ValueError("at least one of min or max is required")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must be less than or equal to max")
        return self


class PriceRange(ValueRange):
    currency: str = "EUR"

    @model_validator(mode="after")
    def valid_currency(self) -> PriceRange:
        if self.currency not in {"EUR", "RSD"}:
            raise ValueError("currency must be EUR or RSD")
        return self


class HardFilters(BaseModel):
    """Portable hard filters; values within a dimension are OR, dimensions are AND."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    makes: list[str] | None = None
    models: list[str] | None = None
    generations: list[str] | None = None
    fuel: list[str] | None = None
    transmission: list[str] | None = None
    body_type: list[str] | None = None
    regions: list[str] | None = None
    seller_type: list[str] | None = None
    vehicle_origin: list[str] | None = None
    damage: list[str] | None = None
    year: ValueRange | None = None
    price: PriceRange | None = None
    mileage_km: ValueRange | None = None
    engine_cc: ValueRange | None = None
    power_kw: ValueRange | None = None

    @model_validator(mode="after")
    def nonblank_values(self) -> HardFilters:
        for name in (
            "makes", "models", "generations", "fuel", "transmission", "body_type",
            "regions", "seller_type", "vehicle_origin", "damage",
        ):
            values = getattr(self, name)
            if values is not None and any(not value for value in values):
                raise ValueError(f"{name} values must not be blank")
        return self


def _norm(value: Any) -> str:
    return " ".join(str(value).strip().casefold().split())


def matches_filters(filters: HardFilters | Mapping[str, Any], listing: Mapping[str, Any]) -> bool:
    """Match normalized listing fields without treating missing data as a match."""
    hard = filters if isinstance(filters, HardFilters) else HardFilters.model_validate(filters)
    condition = listing.get("condition") or {}
    dimensions = {
        "makes": ("make",),
        "models": ("model",),
        "generations": ("generation",),
        "fuel": ("fuel",),
        "transmission": ("transmission",),
        "body_type": ("body_type",),
        "regions": ("region", "city", "location_raw"),
        "seller_type": ("seller_type",),
        "vehicle_origin": ("origin",),
        "damage": ("damage",),
    }
    for dimension, fields in dimensions.items():
        accepted = getattr(hard, dimension)
        if not accepted:
            continue
        candidates = {_norm(listing.get(field)) for field in fields if listing.get(field) is not None}
        if dimension in {"vehicle_origin", "damage"}:
            value = condition.get("origin" if dimension == "vehicle_origin" else "damage")
            if value is not None:
                candidates.add(_norm(value))
        if not candidates.intersection(map(_norm, accepted)):
            return False

    ranges = {
        "year": ("year", None),
        "price": ("price_amount", "price_currency"),
        "mileage_km": ("mileage_km", None),
        "engine_cc": ("engine_cc", None),
        "power_kw": ("power_kw", None),
    }
    for dimension, (field, currency_field) in ranges.items():
        value_range = getattr(hard, dimension)
        if value_range is None:
            continue
        value = listing.get(field)
        if value is None:
            return False
        if currency_field and listing.get(currency_field) != value_range.currency:
            return False
        if value_range.min is not None and value < value_range.min:
            return False
        if value_range.max is not None and value > value_range.max:
            return False
    return True


def filter_dict(filters: HardFilters | Mapping[str, Any]) -> dict[str, Any]:
    hard = filters if isinstance(filters, HardFilters) else HardFilters.model_validate(filters)
    return hard.model_dump(mode="json", exclude_none=True)
