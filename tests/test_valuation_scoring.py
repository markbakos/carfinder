from __future__ import annotations

from carfinder.db.models import ListingSnapshot
from carfinder.scoring import calculate_profile_fit, calculate_quality, rank_score
from carfinder.valuation import MarketValuation, estimate_market_value


def _snapshot(
    listing_id: int,
    price: int | None = 4300,
    *,
    generation: str | None = "Golf V",
    mileage: int | None = 200000,
    year: int | None = 2008,
) -> ListingSnapshot:
    return ListingSnapshot(
        listing_id=listing_id, content_hash=f"{listing_id:064x}",
        title="Volkswagen Golf V", description="Detailed seller description " * 20,
        price_amount=price, price_currency="EUR", make="Volkswagen", model="Golf",
        generation=generation, year=year, fuel="diesel", mileage_km=mileage,
        engine_cc=1896, power_kw=77, transmission="manual_5", location_raw="Novi Sad",
        features_json=["cruise_control"], images_json=["https://images.example/car.jpg"],
    )


def test_market_valuation_uses_median_and_removes_robust_outlier() -> None:
    target = _snapshot(1)
    candidates = [_snapshot(index, price) for index, price in enumerate((4000, 4100, 4200, 4500, 50000), start=2)]
    valuation = estimate_market_value(target, candidates)
    assert valuation.sample_count == 4
    assert valuation.excluded_outliers == 1
    assert valuation.median_amount == 4150
    assert valuation.lower_amount == 4075 and valuation.upper_amount == 4275
    assert valuation.difference_pct == 3.6
    assert valuation.confidence == "low"


def test_insufficient_comparables_never_emit_a_market_median() -> None:
    target = _snapshot(1)
    valuation = estimate_market_value(target, [_snapshot(2, 4000), _snapshot(3, 4100)])
    assert valuation.sample_count == 2
    assert valuation.confidence == "insufficient"
    assert valuation.median_amount is None and valuation.lower_amount is None


def test_comparable_fallback_records_relaxed_generation() -> None:
    target = _snapshot(1)
    candidates = [_snapshot(index, 4000 + index * 100, generation="Golf VI") for index in range(2, 5)]
    valuation = estimate_market_value(target, candidates)
    assert valuation.confidence == "low"
    assert "generation" in valuation.details["relaxed_criteria"]


def test_quality_renormalizes_supported_dimensions_and_keeps_unknowns_unscored() -> None:
    snapshot = _snapshot(1)
    valuation = MarketValuation(
        median_amount=5000, lower_amount=4500, upper_amount=5500, difference_pct=-10,
        sample_count=8, excluded_outliers=0, confidence="medium", details={},
    )
    analysis = {
        "extracted_claims": [
            {"claim_type": "major_service_completed", "value": True, "evidence": "Veliki servis urađen", "confidence": 0.95},
            {"claim_type": "first_owner", "value": True, "evidence": "Prvi vlasnik", "confidence": 0.95},
        ],
        "missing_information": [{"field": "major_service_details"}],
        "concerns": [], "risk_signals": [],
    }
    result = calculate_quality(snapshot, analysis, valuation)
    assert result["dimensions"]["market_value"]["score"] == 70
    assert result["dimensions"]["mechanical_risk"]["score"] is None
    assert result["dimensions"]["seller_listing_risk"]["score"] is None
    assert result["coverage_pct"] == 70
    assert result["quality_score"] is not None


def test_profile_fit_explains_preferences_and_rank_needs_both_scores() -> None:
    snapshot = _snapshot(1, mileage=198000)
    valuation = MarketValuation(
        median_amount=5000, lower_amount=4500, upper_amount=5500, difference_pct=-10,
        sample_count=8, excluded_outliers=0, confidence="medium", details={},
    )
    fit = calculate_profile_fit({
        "mileage_km": {"ideal_max": 180000},
        "equipment": {"prefer": ["cruise_control", "parking_sensors"]},
        "fuel": {"prefer": ["diesel"]},
        "market_discount": {"preferred_min_pct": 15},
    }, snapshot, valuation, hard_filter_pass=True)
    assert fit["score"] == 77
    assert {item["field"] for item in fit["preferences"]} == {"mileage_km", "equipment", "fuel", "market_discount"}
    assert rank_score(80, fit["score"]) == round(80 * 0.7 + 77 * 0.3)
    assert rank_score(None, fit["score"]) is None
    assert calculate_profile_fit({}, snapshot, valuation, hard_filter_pass=True)["score"] == 100
    assert calculate_profile_fit({}, snapshot, valuation, hard_filter_pass=False)["score"] is None


def test_unknown_preference_evidence_does_not_receive_a_perfect_fit() -> None:
    snapshot = _snapshot(1, mileage=None)
    valuation = MarketValuation(
        median_amount=None, lower_amount=None, upper_amount=None, difference_pct=None,
        sample_count=2, excluded_outliers=0, confidence="insufficient", details={},
    )
    fit = calculate_profile_fit({
        "mileage_km": {"ideal_max": 180000},
        "market_discount": {"preferred_min_pct": 15},
    }, snapshot, valuation, hard_filter_pass=True)
    assert fit["score"] is None
    assert set(fit["not_evaluated"]) == {"mileage_km", "market_discount"}
