from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from carfinder.db.models import ListingSnapshot
from carfinder.search import SoftPreferences
from carfinder.valuation import MarketValuation

QUALITY_WEIGHTS = {
    "market_value": 30,
    "mechanical_risk": 20,
    "maintenance_evidence": 15,
    "listing_transparency": 15,
    "ownership_history": 10,
    "seller_listing_risk": 10,
}


def _clamp(value: float) -> int:
    return round(max(0, min(100, value)))


def _dimension(score: int | None, key: str, inputs: dict[str, Any], explanation: str) -> dict[str, Any]:
    return {"score": score, "weight_pct": QUALITY_WEIGHTS[key], "inputs": inputs, "explanation": explanation}


def calculate_quality(
    snapshot: ListingSnapshot,
    analysis: dict[str, Any] | None,
    valuation: MarketValuation,
) -> dict[str, Any]:
    analysis = analysis or {}
    claims = analysis.get("extracted_claims", [])
    concerns = analysis.get("concerns", [])
    risk_signals = analysis.get("risk_signals", [])
    delta = valuation.difference_pct
    value_score = _clamp(50 - 2 * delta) if delta is not None and valuation.sample_count >= 3 else None
    dimensions: dict[str, Any] = {
        "market_value": _dimension(
            value_score, "market_value",
            {"asking_price": {"amount": snapshot.price_amount, "currency": snapshot.price_currency},
             "comparable_median": valuation.median_amount, "difference_pct": delta,
             "sample_count": valuation.sample_count, "confidence": valuation.confidence},
            "50 - (asking-price difference percentage × 2); available only with at least three robust comparables.",
        )
    }

    mechanical = [item for item in concerns if item.get("category") in {"mechanical", "engine", "transmission", "known_issue"}]
    penalties = {"low": 20, "medium": 45, "high": 75}
    mechanical_score = _clamp(100 - sum(penalties.get(item.get("severity"), 20) for item in mechanical)) if mechanical else None
    dimensions["mechanical_risk"] = _dimension(
        mechanical_score, "mechanical_risk", {"signals": mechanical},
        "Starts unscored until a mechanical concern has specific listing evidence.",
    )

    maintenance = [item for item in claims if item.get("claim_type") in {"major_service_completed", "service_book_available"}]
    maintenance_score = None
    if maintenance:
        has_negative = any(item.get("value") is False for item in maintenance)
        details_missing = any(item.get("field") == "major_service_details" for item in analysis.get("missing_information", []))
        maintenance_score = 25 if has_negative else 55 if details_missing else 65
    dimensions["maintenance_evidence"] = _dimension(
        maintenance_score, "maintenance_evidence", {"seller_claims": maintenance,
        "details_missing": any(item.get("field") == "major_service_details" for item in analysis.get("missing_information", []))},
        "Seller statements remain unverified; missing date, mileage, or invoice lowers the evidence score.",
    )

    core_fields = {
        "make": snapshot.make, "model": snapshot.model, "year": snapshot.year,
        "mileage_km": snapshot.mileage_km, "fuel": snapshot.fuel,
        "engine_cc": snapshot.engine_cc, "transmission": snapshot.transmission,
        "location": snapshot.location_raw or snapshot.city or snapshot.region,
    }
    core_present = [name for name, value in core_fields.items() if value is not None]
    description_length = len((snapshot.description or "").strip())
    description_points = 20 if description_length >= 300 else 10 if description_length >= 80 else 0
    image_points = 8 if snapshot.images_json else 0
    feature_points = 8 if snapshot.features_json else 0
    transparency_score = _clamp(len(core_present) / len(core_fields) * 64 + description_points + image_points + feature_points)
    dimensions["listing_transparency"] = _dimension(
        transparency_score, "listing_transparency",
        {"core_fields_present": core_present, "core_fields_total": len(core_fields),
         "description_characters": description_length, "description_points": description_points,
         "image_count": len(snapshot.images_json or []), "image_points": image_points,
         "feature_count": len(snapshot.features_json or []), "feature_points": feature_points},
        "Measures listing completeness and supporting detail, not vehicle condition.",
    )

    history_types = {"first_owner", "mileage_original", "accident_free", "bought_new_locally"}
    history = [item for item in claims if item.get("claim_type") in history_types]
    history_score = None if not history else 35 if any(item.get("value") is False for item in history) else 55
    dimensions["ownership_history"] = _dimension(
        history_score, "ownership_history", {"seller_claims": history},
        "History evidence is only a seller claim unless separately verified.",
    )

    seller_signals = [item for item in risk_signals if item.get("category") in {"scam", "seller_risk", "listing_risk"}]
    seller_score = _clamp(100 - sum(penalties.get(item.get("severity"), 20) for item in seller_signals)) if seller_signals else None
    dimensions["seller_listing_risk"] = _dimension(
        seller_score, "seller_listing_risk", {"signals": seller_signals},
        "Unscored unless a concrete seller or listing risk signal is present.",
    )

    available_weight = sum(item["weight_pct"] for item in dimensions.values() if item["score"] is not None)
    weighted_total = sum(item["score"] * item["weight_pct"] for item in dimensions.values() if item["score"] is not None)
    quality_score = round(weighted_total / available_weight) if available_weight >= 60 else None
    return {
        "quality_score": quality_score,
        "coverage_pct": available_weight,
        "dimensions": dimensions,
        "explanation": {
            "formula": "weighted mean of evidence-supported dimensions; configured weights are renormalized",
            "weight_coverage_pct": available_weight,
            "minimum_coverage_pct": 60,
            "unsupported_dimensions_are_unscored": True,
        },
    }


def _range_score(value: int, lower: int | None, upper: int | None) -> int:
    if lower is not None and value < lower:
        return _clamp(100 - (lower - value) * 25)
    if upper is not None and value > upper:
        return _clamp(100 - (value - upper) * 25)
    return 100


def calculate_profile_fit(
    preferences: dict[str, Any],
    snapshot: ListingSnapshot,
    valuation: MarketValuation,
    *,
    hard_filter_pass: bool,
) -> dict[str, Any]:
    if not hard_filter_pass:
        return {"score": None, "preferences": [], "not_evaluated": [], "reason": "hard filters did not pass"}
    try:
        soft = SoftPreferences.model_validate(preferences or {})
    except ValidationError as error:
        return {"score": None, "preferences": [], "not_evaluated": [], "reason": f"invalid saved preferences: {error.error_count()} validation error(s)"}
    if not preferences:
        return {"score": 100, "preferences": [], "not_evaluated": [], "reason": "hard filters passed; no soft preferences configured"}

    scores: list[int] = []
    evaluated: list[dict[str, Any]] = []
    skipped: list[str] = []

    def add(field: str, score: int, inputs: dict[str, Any]) -> None:
        scores.append(score)
        evaluated.append({"field": field, "score": score, "inputs": inputs})

    if soft.mileage_km:
        value = snapshot.mileage_km
        if value is None:
            skipped.append("mileage_km")
        else:
            ideal = soft.mileage_km.ideal_max
            add("mileage_km", 100 if value <= ideal else _clamp(100 - (value - ideal) / max(ideal, 1) * 100), {"value": value, "ideal_max": ideal})
    if soft.price:
        if snapshot.price_amount is None or snapshot.price_currency != soft.price.currency:
            skipped.append("price")
        else:
            ideal = soft.price.ideal_max
            add("price", 100 if snapshot.price_amount <= ideal else _clamp(100 - (snapshot.price_amount - ideal) / max(ideal, 1) * 100),
                {"value": snapshot.price_amount, "currency": snapshot.price_currency, "ideal_max": ideal})
    if soft.year:
        if snapshot.year is None:
            skipped.append("year")
        else:
            add("year", _range_score(snapshot.year, soft.year.min, soft.year.max),
                {"value": snapshot.year, "min": soft.year.min, "max": soft.year.max})
    for name, preference, value in (
        ("fuel", soft.fuel, snapshot.fuel),
        ("transmission", soft.transmission, snapshot.transmission),
        ("body_type", soft.body_type, snapshot.body_type),
    ):
        if preference:
            if value is None:
                skipped.append(name)
            else:
                matched = any(value.strip().casefold() == preferred.strip().casefold() for preferred in preference.prefer)
                add(name, 100 if matched else 0, {"value": value, "preferred": preference.prefer})
    if soft.location:
        location = snapshot.region or snapshot.city or snapshot.location_raw
        if location is None:
            skipped.append("location")
        else:
            matched = any(location.strip().casefold() == preferred.strip().casefold() for preferred in soft.location.prefer)
            add("location", 100 if matched else 0, {"value": location, "preferred": soft.location.prefer})
    if soft.equipment:
        features = {value.casefold() for value in snapshot.features_json or []}
        if not features:
            skipped.append("equipment")
        else:
            matched = [value for value in soft.equipment.prefer if value.casefold() in features]
            add("equipment", round(len(matched) / len(soft.equipment.prefer) * 100),
                {"matched": matched, "preferred": soft.equipment.prefer})
    if soft.market_discount:
        discount = -valuation.difference_pct if valuation.difference_pct is not None and valuation.sample_count >= 3 else None
        if discount is None:
            skipped.append("market_discount")
        else:
            threshold = soft.market_discount.preferred_min_pct
            score = 100 if discount >= threshold else 0 if threshold == 0 else _clamp(discount / threshold * 100)
            add("market_discount", score, {"discount_pct": discount, "preferred_min_pct": threshold,
                                           "sample_count": valuation.sample_count, "confidence": valuation.confidence})

    return {
        "score": round(sum(scores) / len(scores)) if scores else None,
        "preferences": evaluated,
        "not_evaluated": skipped,
        "reason": "equal mean of evaluated soft preferences; unavailable evidence is omitted" if scores else "no preference had sufficient listing evidence",
    }


def rank_score(quality_score: int | None, profile_fit_score: int | None) -> int | None:
    if quality_score is None or profile_fit_score is None:
        return None
    return round(quality_score * 0.70 + profile_fit_score * 0.30)
