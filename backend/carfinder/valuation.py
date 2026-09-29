from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

from pydantic import BaseModel, ConfigDict

from carfinder.db.models import ListingSnapshot


class MarketValuation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    median_amount: int | None
    lower_amount: int | None
    upper_amount: int | None
    difference_pct: float | None
    sample_count: int
    excluded_outliers: int
    confidence: str
    details: dict[str, Any]


@dataclass(frozen=True)
class ComparableSet:
    items: list[ListingSnapshot]
    relaxed: list[str]


def _same(left: str | None, right: str | None) -> bool:
    return bool(left and right and left.strip().casefold() == right.strip().casefold())


def _transmission_family(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.casefold()
    if normalized.startswith("manual") or normalized.startswith("manuel"):
        return "manual"
    if normalized.startswith("auto") or normalized.startswith("automatski"):
        return "automatic"
    return normalized


def _base_comparables(target: ListingSnapshot, candidates: list[ListingSnapshot]) -> list[ListingSnapshot]:
    if not target.make or not target.model or target.year is None or target.price_currency is None:
        return []
    selected = []
    for item in candidates:
        if item.listing_id == target.listing_id or item.price_amount is None or item.price_amount <= 0:
            continue
        if not _same(item.make, target.make) or not _same(item.model, target.model):
            continue
        if item.price_currency != target.price_currency or item.year is None or abs(item.year - target.year) > 2:
            continue
        if target.fuel and not _same(item.fuel, target.fuel):
            continue
        if target.transmission and _transmission_family(item.transmission) != _transmission_family(target.transmission):
            continue
        selected.append(item)
    return selected


def select_comparables(target: ListingSnapshot, candidates: list[ListingSnapshot]) -> ComparableSet:
    """Prefer matching generation, engine, and mileage; relax in that order if sparse."""
    base = _base_comparables(target, candidates)
    strict: list[ListingSnapshot] = []
    same_generation: list[ListingSnapshot] = []
    for item in base:
        if target.generation and not _same(item.generation, target.generation):
            continue
        same_generation.append(item)
        if target.engine_cc is not None:
            if item.engine_cc is None or abs(item.engine_cc - target.engine_cc) > max(250, target.engine_cc * 0.3):
                continue
        if target.mileage_km is not None:
            if item.mileage_km is None or abs(item.mileage_km - target.mileage_km) > max(50000, target.mileage_km * 0.35):
                continue
        strict.append(item)

    if len(strict) >= 3 or len(base) < 3:
        return ComparableSet(strict, [])
    if len(same_generation) >= 3:
        return ComparableSet(same_generation, ["engine_cc", "mileage_km"])
    if len(base) >= 3:
        relaxed = [name for name, value in (("generation", target.generation), ("engine_cc", target.engine_cc), ("mileage_km", target.mileage_km)) if value is not None]
        return ComparableSet(base, relaxed)
    return ComparableSet(strict, [])


def _percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _robust_filter(values: list[int]) -> tuple[list[int], int]:
    if len(values) < 3:
        return values, 0
    center = median(values)
    mad = median([abs(value - center) for value in values])
    # A small floor handles MAD=0 while still rejecting listings far outside the local cluster.
    threshold = max(3.5 * 1.4826 * mad, abs(center) * 0.15)
    retained = [value for value in values if abs(value - center) <= threshold]
    return retained, len(values) - len(retained)


def estimate_market_value(target: ListingSnapshot, candidates: list[ListingSnapshot]) -> MarketValuation:
    selection = select_comparables(target, candidates)
    prices = [item.price_amount for item in selection.items if item.price_amount is not None and item.price_amount > 0]
    retained, excluded = _robust_filter(prices)
    count = len(retained)
    confidence = "high" if count >= 10 else "medium" if count >= 5 else "low" if count >= 3 else "insufficient"
    median_amount = round(median(retained)) if count >= 3 else None
    difference = None
    if median_amount is not None and target.price_amount is not None and median_amount > 0:
        difference = round((target.price_amount - median_amount) / median_amount * 100, 1)
    return MarketValuation(
        median_amount=median_amount,
        lower_amount=_percentile(retained, 0.25) if count >= 3 else None,
        upper_amount=_percentile(retained, 0.75) if count >= 3 else None,
        difference_pct=difference,
        sample_count=count,
        excluded_outliers=excluded,
        confidence=confidence,
        details={
            "method": "same make/model, year ±2, currency, fuel and transmission; robust median/MAD",
            "relaxed_criteria": selection.relaxed,
            "candidate_count": len(prices),
            "comparable_listing_ids": [item.listing_id for item in selection.items],
            "excluded_outliers": excluded,
        },
    )
