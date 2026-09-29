from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from carfinder.db.models import (
    Listing,
    ListingAnalysis,
    ListingScore,
    ListingSnapshot,
    ListingValuation,
    ProfileListingMatch,
    SearchProfile,
)
from carfinder.scoring import calculate_profile_fit, calculate_quality, rank_score
from carfinder.valuation import estimate_market_value


def recompute_all_scores(session: Session) -> int:
    rows = session.execute(select(Listing, ListingSnapshot).join(
        ListingSnapshot, ListingSnapshot.id == Listing.current_snapshot_id
    )).all()
    if not rows:
        return 0
    active = [snapshot for listing, snapshot in rows if listing.status == "active"]
    def group_key(snapshot: ListingSnapshot) -> tuple[str, str, str] | None:
        if not snapshot.make or not snapshot.model or not snapshot.price_currency:
            return None
        return (snapshot.make.casefold(), snapshot.model.casefold(), snapshot.price_currency)

    active_groups: dict[tuple[str, str, str], list[ListingSnapshot]] = {}
    for snapshot in active:
        if key := group_key(snapshot):
            active_groups.setdefault(key, []).append(snapshot)
    snapshot_ids = [snapshot.id for _listing, snapshot in rows]
    analyses = {item.snapshot_id: item.result_json for item in session.scalars(
        select(ListingAnalysis).where(ListingAnalysis.snapshot_id.in_(snapshot_ids))
    )}
    valuation_rows = {item.snapshot_id: item for item in session.scalars(
        select(ListingValuation).where(ListingValuation.snapshot_id.in_(snapshot_ids))
    )}
    score_rows = {item.snapshot_id: item for item in session.scalars(
        select(ListingScore).where(ListingScore.snapshot_id.in_(snapshot_ids))
    )}
    matches = session.execute(select(ProfileListingMatch, SearchProfile).join(
        SearchProfile, SearchProfile.id == ProfileListingMatch.profile_id
    )).all()
    matches_by_listing: dict[int, list[tuple[ProfileListingMatch, SearchProfile]]] = {}
    for match, profile in matches:
        matches_by_listing.setdefault(match.listing_id, []).append((match, profile))

    computed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for listing, snapshot in rows:
        # ponytail: O(n²) within make/model groups; add year-bucket indexes if personal datasets grow enough to matter.
        valuation = estimate_market_value(snapshot, active_groups.get(group_key(snapshot), []))
        valuation_row = valuation_rows.get(snapshot.id)
        if valuation_row is None:
            valuation_row = ListingValuation(listing_id=listing.id, snapshot_id=snapshot.id)
            session.add(valuation_row)
        valuation_row.median_amount = valuation.median_amount
        valuation_row.lower_amount = valuation.lower_amount
        valuation_row.upper_amount = valuation.upper_amount
        valuation_row.difference_pct = valuation.difference_pct
        valuation_row.sample_count = valuation.sample_count
        valuation_row.excluded_outliers = valuation.excluded_outliers
        valuation_row.confidence = valuation.confidence
        valuation_row.details_json = valuation.details
        valuation_row.computed_at = computed_at

        score = calculate_quality(snapshot, analyses.get(snapshot.id), valuation)
        score_row = score_rows.get(snapshot.id)
        if score_row is None:
            score_row = ListingScore(listing_id=listing.id, snapshot_id=snapshot.id)
            session.add(score_row)
        score_row.quality_score = score["quality_score"]
        score_row.coverage_pct = score["coverage_pct"]
        score_row.dimensions_json = score["dimensions"]
        score_row.explanation_json = score["explanation"]
        score_row.computed_at = computed_at

        for match, profile in matches_by_listing.get(listing.id, []):
            fit = calculate_profile_fit(
                profile.preferences_json or {}, snapshot, valuation,
                hard_filter_pass=match.hard_filter_pass,
            )
            match.profile_fit_score = fit["score"]
            match.rank_score = rank_score(score["quality_score"], fit["score"])
            match.profile_fit_explanation_json = fit
    session.flush()
    return len(rows)
