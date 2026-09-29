from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from carfinder.config import Settings
from carfinder.db.engine import create_database_engine
from carfinder.db.models import (
    Listing,
    ListingAnalysis,
    ListingClaim,
    ListingEvent,
    ListingSnapshot,
    ListingScore,
    ListingUserState,
    ListingValuation,
    ProfileListingMatch,
    ProviderSource,
    ScrapeRun,
    ScrapeRunMessage,
    SearchProfile,
)
from carfinder.paths import AppPaths
from carfinder.pipeline.lock import RunAlreadyActive, run_lock
from carfinder.pipeline.runner import run_pipeline
from carfinder.analysis_service import analyze_stored_listings
from carfinder.providers.base import ProviderSearchSource
from carfinder.providers.registry import get_provider
from carfinder.search import HardFilters, SoftPreferences, filter_dict, preferences_dict

UserStateName = Literal[
    "new", "watching", "interested", "maybe", "rejected", "contacted",
    "viewing_planned", "viewed", "inspected", "offer_made", "purchased",
]
RejectionReason = Literal[
    "too_expensive", "bad_value", "mechanical_risk", "too_far", "suspicious",
    "accident_history", "seller_issue", "wrong_spec", "other",
]


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "polovniautomobili"
    search_url: str | None = None
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    filters: HardFilters = Field(default_factory=HardFilters)
    preferences: SoftPreferences = Field(default_factory=SoftPreferences)
    initial_import_mode: Literal["seed_only", "analyze_all", "analyze_top_n"] = "seed_only"
    sources: list[SourceInput] = Field(default_factory=list)
    provider: str = "polovniautomobili"
    search_url: str | None = None

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def source_required(self) -> ProfileCreate:
        if not self.sources and not self.search_url and not filter_dict(self.filters) and not preferences_dict(self.preferences):
            raise ValueError("provide a search URL, source, hard filters, or soft preferences")
        return self


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    filters: HardFilters | None = None
    preferences: SoftPreferences | None = None
    initial_import_mode: Literal["seed_only", "analyze_all", "analyze_top_n"] | None = None
    sources: list[SourceInput] | None = None


class UserStatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: UserStateName
    notes: str = Field(default="", max_length=10000)
    rejection_reason: RejectionReason | None = None


def _engine(settings: Settings):
    return create_database_engine(settings.database_path)


def _snapshot_dict(item: ListingSnapshot) -> dict[str, Any]:
    return {
        "id": item.id,
        "observed_at": item.observed_at.isoformat(),
        "title": item.title,
        "description": item.description,
        "price": {"amount": item.price_amount, "currency": item.price_currency},
        "vehicle": {
            "make": item.make, "model": item.model, "generation": item.generation,
            "trim": item.trim, "year": item.year, "fuel": item.fuel,
            "mileage_km": item.mileage_km, "engine_cc": item.engine_cc,
            "power_kw": item.power_kw, "transmission": item.transmission,
            "drive": item.drive, "body_type": item.body_type,
            "doors": item.doors, "seats": item.seats,
        },
        "location": {"raw": item.location_raw, "city": item.city, "region": item.region},
        "seller_type": item.seller_type,
        "features": item.features_json,
        "condition": item.condition_json,
        "images": item.images_json,
        "structured": item.structured_json,
    }


def _user_state_dict(item: ListingUserState | None) -> dict[str, Any]:
    if item is None:
        return {"state": "new", "notes": "", "rejection_reason": None, "updated_at": None}
    return {
        "state": item.state, "notes": item.notes,
        "rejection_reason": item.rejection_reason, "updated_at": item.updated_at.isoformat(),
    }


def _listing_dict(
    session: Session,
    item: Listing,
    snapshot: ListingSnapshot | None,
    profile_id: int | None = None,
) -> dict[str, Any]:
    state = session.get(ListingUserState, item.id)
    valuation = session.scalar(select(ListingValuation).where(ListingValuation.snapshot_id == snapshot.id)) if snapshot else None
    score = session.scalar(select(ListingScore).where(ListingScore.snapshot_id == snapshot.id)) if snapshot else None
    match_count = session.scalar(
        select(func.count()).select_from(ProfileListingMatch).where(
            ProfileListingMatch.listing_id == item.id,
            ProfileListingMatch.hard_filter_pass.is_(True),
        )
    ) or 0
    match_query = select(ProfileListingMatch).where(
        ProfileListingMatch.listing_id == item.id,
        ProfileListingMatch.hard_filter_pass.is_(True),
    )
    if profile_id is not None:
        match_query = match_query.where(ProfileListingMatch.profile_id == profile_id)
    match = session.scalar(match_query.order_by(ProfileListingMatch.rank_score.desc().nullslast()).limit(1))
    return {
        "id": item.id,
        "provider": item.provider,
        "external_id": item.external_id,
        "url": item.url,
        "status": item.status,
        "first_seen_at": item.first_seen_at.isoformat(),
        "last_seen_at": item.last_seen_at.isoformat(),
        "last_detail_fetch_at": item.last_detail_fetch_at.isoformat() if item.last_detail_fetch_at else None,
        "removed_at": item.removed_at.isoformat() if item.removed_at else None,
        "missing_run_count": item.missing_run_count,
        "current": _snapshot_dict(snapshot) if snapshot else None,
        "market_value": _valuation_dict(valuation) if valuation else None,
        "scores": _score_dict(score) if score else None,
        "profile_fit_score": match.profile_fit_score if match else None,
        "rank_score": match.rank_score if match else None,
        "profile_fit_explanation": match.profile_fit_explanation_json if match else None,
        "user_state": _user_state_dict(state),
        "matched_profile_count": match_count,
    }


def _valuation_dict(item: ListingValuation) -> dict[str, Any]:
    return {
        "median_amount": item.median_amount,
        "range": {"low": item.lower_amount, "high": item.upper_amount},
        "difference_pct": item.difference_pct,
        "sample_count": item.sample_count,
        "excluded_outliers": item.excluded_outliers,
        "confidence": item.confidence,
        "details": item.details_json,
        "computed_at": item.computed_at.isoformat(),
    }


def _score_dict(item: ListingScore) -> dict[str, Any]:
    return {
        "quality_score": item.quality_score,
        "coverage_pct": item.coverage_pct,
        "dimensions": item.dimensions_json,
        "explanation": item.explanation_json,
        "computed_at": item.computed_at.isoformat(),
    }


def _create_source(session: Session, profile: SearchProfile, source: SourceInput, filters: dict[str, Any]) -> None:
    try:
        adapter = get_provider(source.provider)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    validation = adapter.validate_source(
        ProviderSearchSource(provider=source.provider, search_url=source.search_url, native_filters=filters)
    )
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.message)
    session.add(ProviderSource(
        profile_id=profile.id,
        provider=source.provider,
        search_url=source.search_url.strip() if source.search_url else None,
        enabled=source.enabled,
        source_settings_json=source.settings,
    ))


def _profile_dict(session: Session, profile: SearchProfile) -> dict[str, Any]:
    sources = session.scalars(select(ProviderSource).where(ProviderSource.profile_id == profile.id).order_by(ProviderSource.id)).all()
    return {
        "id": profile.id,
        "name": profile.name,
        "enabled": profile.enabled,
        "filters": profile.filters_json,
        "preferences": profile.preferences_json,
        "initial_import_mode": profile.initial_import_mode,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
        "sources": [
            {"id": source.id, "provider": source.provider, "search_url": source.search_url,
             "enabled": source.enabled, "settings": source.source_settings_json}
            for source in sources
        ],
    }


def _run_locked(settings: Settings, profile_name: str | None = None) -> dict[str, Any]:
    with run_lock(AppPaths.from_environment().lock_file):
        result = asyncio.run(run_pipeline(settings, profile_name=profile_name, trigger="api"))
    return result.__dict__


def _analyze_locked(settings: Settings, listing_id: int, force: bool = False) -> dict[str, int | str]:
    with run_lock(AppPaths.from_environment().lock_file):
        return asyncio.run(analyze_stored_listings(settings, listing_id=listing_id, force=force))


def create_router(settings: Settings) -> APIRouter:
    api = APIRouter(prefix="/api")

    @api.get("/settings")
    def settings_summary() -> dict[str, Any]:
        paths = AppPaths.from_environment()
        return {
            "config_path": str(settings.config_path or paths.config_file),
            "database_path": str(settings.database_path),
            "server": settings.server.model_dump(),
            "scraping": settings.scraping.model_dump(),
            "provider": {
                "id": "polovniautomobili",
                "enabled": settings.providers.polovniautomobili.enabled,
                "headless": settings.providers.polovniautomobili.headless,
                "browser_profile": str(settings.browser_profile),
            },
            "llm": {
                "enabled": settings.llm.enabled,
                "provider": settings.llm.provider,
                "model": settings.llm.model,
                "timeout_seconds": settings.llm.timeout_seconds,
            },
            "image_mode": settings.storage.images.mode,
        }

    @api.get("/providers")
    def providers() -> list[dict[str, Any]]:
        adapter = get_provider("polovniautomobili")
        return [{"id": adapter.provider_id, "capabilities": adapter.capabilities.model_dump()}]

    @api.get("/profiles")
    def profiles() -> list[dict[str, Any]]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                return [_profile_dict(session, item) for item in session.scalars(select(SearchProfile).order_by(SearchProfile.id))]
        finally:
            engine.dispose()

    @api.post("/profiles", status_code=201)
    def create_profile(payload: ProfileCreate) -> dict[str, Any]:
        filters = filter_dict(payload.filters)
        sources = payload.sources or [SourceInput(provider=payload.provider, search_url=payload.search_url)]
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                profile = SearchProfile(
                    name=payload.name.strip(), enabled=payload.enabled,
                    filters_json=filters, preferences_json=preferences_dict(payload.preferences),
                    initial_import_mode=payload.initial_import_mode,
                )
                session.add(profile)
                session.flush()
                for source in sources:
                    _create_source(session, profile, source, filters)
                session.commit()
                session.refresh(profile)
                return _profile_dict(session, profile)
        except IntegrityError as error:
            raise HTTPException(status_code=409, detail="A profile with that name already exists") from error
        finally:
            engine.dispose()

    @api.get("/profiles/{profile_id}")
    def get_profile(profile_id: int) -> dict[str, Any]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                profile = session.get(SearchProfile, profile_id)
                if profile is None:
                    raise HTTPException(status_code=404, detail="Profile not found")
                return _profile_dict(session, profile)
        finally:
            engine.dispose()

    @api.patch("/profiles/{profile_id}")
    def patch_profile(profile_id: int, payload: ProfilePatch) -> dict[str, Any]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                profile = session.get(SearchProfile, profile_id)
                if profile is None:
                    raise HTTPException(status_code=404, detail="Profile not found")
                data = payload.model_dump(exclude_unset=True)
                if "name" in data and data["name"] is not None:
                    profile.name = data["name"].strip()
                if "enabled" in data and data["enabled"] is not None:
                    profile.enabled = data["enabled"]
                if "filters" in data:
                    filters = filter_dict(data["filters"] or {})
                    profile.filters_json = filters
                else:
                    filters = profile.filters_json
                if "preferences" in data and data["preferences"] is not None:
                    profile.preferences_json = preferences_dict(data["preferences"])
                if "initial_import_mode" in data and data["initial_import_mode"] is not None:
                    profile.initial_import_mode = data["initial_import_mode"]
                if "sources" in data:
                    session.query(ProviderSource).filter_by(profile_id=profile.id).delete(synchronize_session=False)
                    for source_data in data["sources"] or []:
                        _create_source(session, profile, SourceInput.model_validate(source_data), filters)
                session.commit()
                session.refresh(profile)
                return _profile_dict(session, profile)
        except IntegrityError as error:
            raise HTTPException(status_code=409, detail="A profile with that name or source already exists") from error
        finally:
            engine.dispose()

    @api.delete("/profiles/{profile_id}", status_code=204)
    def delete_profile(profile_id: int) -> None:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                profile = session.get(SearchProfile, profile_id)
                if profile is None:
                    raise HTTPException(status_code=404, detail="Profile not found")
                session.delete(profile)
                session.commit()
        finally:
            engine.dispose()

    @api.post("/profiles/{profile_id}/run")
    async def run_profile(profile_id: int) -> dict[str, Any]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                profile = session.get(SearchProfile, profile_id)
                if profile is None:
                    raise HTTPException(status_code=404, detail="Profile not found")
                name = profile.name
        finally:
            engine.dispose()
        try:
            return await asyncio.to_thread(_run_locked, settings, name)
        except RunAlreadyActive as error:
            raise HTTPException(status_code=409, detail="run already active") from error

    @api.get("/listings")
    def listings(
        profile: int | None = None,
        provider: str | None = None,
        make: str | None = None,
        model: str | None = None,
        generation: str | None = None,
        fuel: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        price_currency: Literal["EUR", "RSD"] = "EUR",
        mileage_max: int | None = None,
        status: str | None = None,
        user_state: UserStateName | None = None,
        minimum_score: int | None = Query(default=None, ge=0, le=100),
        new_since: datetime | None = None,
        price_drop: bool = False,
        q: str | None = None,
        sort: Literal["newest", "changed", "price_asc", "price_desc", "quality_desc", "rank_desc", "first_seen"] = "newest",
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                stmt = select(Listing, ListingSnapshot, ListingUserState).outerjoin(
                    ListingSnapshot, ListingSnapshot.id == Listing.current_snapshot_id
                ).outerjoin(ListingUserState, ListingUserState.listing_id == Listing.id).outerjoin(
                    ListingScore, ListingScore.snapshot_id == ListingSnapshot.id
                )
                if profile is not None:
                    stmt = stmt.join(ProfileListingMatch, ProfileListingMatch.listing_id == Listing.id).where(
                        ProfileListingMatch.profile_id == profile,
                        ProfileListingMatch.hard_filter_pass.is_(True),
                    )
                conditions = []
                if provider:
                    conditions.append(Listing.provider == provider)
                for supplied, column in ((make, ListingSnapshot.make), (model, ListingSnapshot.model),
                                         (generation, ListingSnapshot.generation), (fuel, ListingSnapshot.fuel)):
                    if supplied:
                        conditions.append(func.lower(column) == supplied.strip().lower())
                if year_min is not None:
                    conditions.append(ListingSnapshot.year >= year_min)
                if year_max is not None:
                    conditions.append(ListingSnapshot.year <= year_max)
                if price_min is not None:
                    conditions.extend((ListingSnapshot.price_amount >= price_min, ListingSnapshot.price_currency == price_currency))
                if price_max is not None:
                    conditions.extend((ListingSnapshot.price_amount <= price_max, ListingSnapshot.price_currency == price_currency))
                if mileage_max is not None:
                    conditions.append(ListingSnapshot.mileage_km <= mileage_max)
                if status:
                    conditions.append(Listing.status == status)
                if user_state:
                    if user_state == "new":
                        conditions.append(or_(ListingUserState.state == "new", ListingUserState.listing_id.is_(None)))
                    else:
                        conditions.append(ListingUserState.state == user_state)
                if minimum_score is not None:
                    conditions.append(ListingScore.quality_score >= minimum_score)
                if new_since:
                    utc_since = new_since.replace(tzinfo=timezone.utc) if new_since.tzinfo is None else new_since.astimezone(timezone.utc)
                    conditions.append(Listing.first_seen_at >= utc_since.replace(tzinfo=None))
                if price_drop:
                    conditions.append(exists(select(1).where(
                        ListingEvent.listing_id == Listing.id, ListingEvent.event_type == "price_dropped"
                    )))
                if q:
                    needle = f"%{q.strip()}%"
                    conditions.append(or_(ListingSnapshot.title.ilike(needle), ListingSnapshot.description.ilike(needle)))
                if conditions:
                    stmt = stmt.where(*conditions)
                if sort in {"price_asc", "price_desc"}:
                    stmt = stmt.where(ListingSnapshot.price_currency == price_currency)
                count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
                total = session.scalar(count_stmt) or 0
                ordering = {
                    "newest": Listing.first_seen_at.desc(),
                    "changed": ListingSnapshot.observed_at.desc().nullslast(),
                    "first_seen": Listing.first_seen_at.asc(),
                    "price_asc": ListingSnapshot.price_amount.asc().nullslast(),
                    "price_desc": ListingSnapshot.price_amount.desc().nullslast(),
                    "quality_desc": ListingScore.quality_score.desc().nullslast(),
                    "rank_desc": (ProfileListingMatch.rank_score.desc().nullslast() if profile is not None
                                  else ListingScore.quality_score.desc().nullslast()),
                }[sort]
                rows = session.execute(stmt.order_by(ordering, Listing.id).limit(limit).offset(offset)).all()
                return {"items": [_listing_dict(session, listing, snapshot, profile) for listing, snapshot, _state in rows],
                        "total": total, "limit": limit, "offset": offset}
        finally:
            engine.dispose()

    @api.get("/listings/{listing_id}")
    def get_listing(listing_id: int, profile: int | None = None) -> dict[str, Any]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                listing = session.get(Listing, listing_id)
                if listing is None:
                    raise HTTPException(status_code=404, detail="Listing not found")
                snapshot = session.get(ListingSnapshot, listing.current_snapshot_id) if listing.current_snapshot_id else None
                return _listing_dict(session, listing, snapshot, profile)
        finally:
            engine.dispose()

    @api.get("/listings/{listing_id}/history")
    def listing_history(listing_id: int) -> dict[str, Any]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                listing = session.get(Listing, listing_id)
                if listing is None:
                    raise HTTPException(status_code=404, detail="Listing not found")
                snapshots = session.scalars(select(ListingSnapshot).where(
                    ListingSnapshot.listing_id == listing_id
                ).order_by(ListingSnapshot.observed_at, ListingSnapshot.id)).all()
                events = session.scalars(select(ListingEvent).where(
                    ListingEvent.listing_id == listing_id
                ).order_by(ListingEvent.occurred_at, ListingEvent.id)).all()
                return {
                    "snapshots": [{
                        **_snapshot_dict(item),
                        "market_value": (_valuation_dict(value) if (value := session.scalar(select(ListingValuation).where(ListingValuation.snapshot_id == item.id))) else None),
                        "scores": (_score_dict(score) if (score := session.scalar(select(ListingScore).where(ListingScore.snapshot_id == item.id))) else None),
                    } for item in snapshots],
                    "events": [{"id": event.id, "type": event.event_type, "occurred_at": event.occurred_at.isoformat(),
                                "old": event.old_value_json, "new": event.new_value_json, "snapshot_id": event.snapshot_id}
                               for event in events],
                }
        finally:
            engine.dispose()

    @api.get("/listings/{listing_id}/analysis")
    def listing_analysis(listing_id: int) -> dict[str, Any]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                listing = session.get(Listing, listing_id)
                if listing is None:
                    raise HTTPException(status_code=404, detail="Listing not found")
                snapshot = session.get(ListingSnapshot, listing.current_snapshot_id) if listing.current_snapshot_id else None
                analysis = session.scalar(select(ListingAnalysis).where(
                    ListingAnalysis.listing_id == listing_id,
                    ListingAnalysis.snapshot_id == snapshot.id,
                )) if snapshot else None
                claims = session.scalars(select(ListingClaim).where(
                    ListingClaim.listing_id == listing_id,
                    ListingClaim.snapshot_id == snapshot.id,
                ).order_by(ListingClaim.id)) if snapshot else []
                return {
                    "status": analysis.status if analysis else "pending",
                    "snapshot_id": snapshot.id if snapshot else None,
                    "result": analysis.result_json if analysis else None,
                    "claims": [{
                        "id": claim.id, "type": claim.claim_type, "value": claim.value_json,
                        "source_type": claim.source_type, "source_text": claim.source_text,
                        "verification_status": claim.verification_status, "confidence": claim.confidence,
                    } for claim in claims],
                }
        finally:
            engine.dispose()

    @api.post("/listings/{listing_id}/reanalyze")
    async def reanalyze_listing(listing_id: int) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(_analyze_locked, settings, listing_id, True)
        except RunAlreadyActive as error:
            raise HTTPException(status_code=409, detail="run already active") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.get("/listings/{listing_id}/matches")
    def listing_matches(listing_id: int) -> list[dict[str, Any]]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                if session.get(Listing, listing_id) is None:
                    raise HTTPException(status_code=404, detail="Listing not found")
                rows = session.execute(select(ProfileListingMatch, SearchProfile).join(
                    SearchProfile, SearchProfile.id == ProfileListingMatch.profile_id
                ).where(ProfileListingMatch.listing_id == listing_id).order_by(SearchProfile.name)).all()
                return [{"profile_id": match.profile_id, "profile_name": profile.name,
                         "first_matched_at": match.first_matched_at.isoformat(),
                         "last_matched_at": match.last_matched_at.isoformat(),
                         "hard_filter_pass": match.hard_filter_pass,
                         "profile_fit_score": match.profile_fit_score,
                         "rank_score": match.rank_score,
                         "profile_fit_explanation": match.profile_fit_explanation_json,
                         "details": match.match_details_json}
                        for match, profile in rows]
        finally:
            engine.dispose()

    @api.patch("/listings/{listing_id}/user-state")
    def patch_user_state(listing_id: int, payload: UserStatePatch) -> dict[str, Any]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                if session.get(Listing, listing_id) is None:
                    raise HTTPException(status_code=404, detail="Listing not found")
                state = session.get(ListingUserState, listing_id)
                if state is None:
                    state = ListingUserState(listing_id=listing_id)
                    session.add(state)
                state.state = payload.state
                state.notes = payload.notes
                state.rejection_reason = payload.rejection_reason if payload.state == "rejected" else None
                session.commit()
                session.refresh(state)
                return _user_state_dict(state)
        finally:
            engine.dispose()

    @api.get("/runs")
    def runs(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)) -> dict[str, Any]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                total = session.scalar(select(func.count()).select_from(ScrapeRun)) or 0
                items = session.scalars(select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(limit).offset(offset)).all()
                return {"items": [_run_dict(item) for item in items], "total": total, "limit": limit, "offset": offset}
        finally:
            engine.dispose()

    @api.get("/runs/{run_id}")
    def get_run(run_id: int) -> dict[str, Any]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                run = session.get(ScrapeRun, run_id)
                if run is None:
                    raise HTTPException(status_code=404, detail="Run not found")
                messages = session.scalars(select(ScrapeRunMessage).where(
                    ScrapeRunMessage.run_id == run_id
                ).order_by(ScrapeRunMessage.created_at, ScrapeRunMessage.id)).all()
                result = _run_dict(run)
                result["messages"] = [{"id": item.id, "level": item.level, "code": item.code,
                                       "message": item.message, "context": item.context_json,
                                       "created_at": item.created_at.isoformat()} for item in messages]
                return result
        finally:
            engine.dispose()

    @api.post("/runs")
    async def run_all() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(_run_locked, settings)
        except RunAlreadyActive as error:
            raise HTTPException(status_code=409, detail="run already active") from error

    @api.get("/stats")
    def stats() -> dict[str, Any]:
        engine = _engine(settings)
        try:
            with Session(engine) as session:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                last_run = session.scalar(select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(1))
                return {
                    "listings_total": session.scalar(select(func.count()).select_from(Listing)) or 0,
                    "listings_active": session.scalar(select(func.count()).select_from(Listing).where(Listing.status == "active")) or 0,
                    "new_24h": session.scalar(select(func.count()).select_from(Listing).where(Listing.first_seen_at >= now - timedelta(hours=24))) or 0,
                    "price_drops_7d": session.scalar(select(func.count()).select_from(ListingEvent).where(
                        ListingEvent.event_type == "price_dropped", ListingEvent.occurred_at >= now - timedelta(days=7)
                    )) or 0,
                    "watching": session.scalar(select(func.count()).select_from(ListingUserState).where(ListingUserState.state == "watching")) or 0,
                    "strong_deals": session.scalar(select(func.count()).select_from(ListingScore).join(
                        Listing, Listing.current_snapshot_id == ListingScore.snapshot_id
                    ).join(ListingValuation, ListingValuation.snapshot_id == ListingScore.snapshot_id).where(
                        Listing.status == "active", ListingScore.quality_score >= 70,
                        ListingValuation.difference_pct <= -10, ListingValuation.confidence.in_(["medium", "high"]),
                    )) or 0,
                    "last_run": _run_dict(last_run) if last_run else None,
                }
        finally:
            engine.dispose()

    return api


def _run_dict(item: ScrapeRun) -> dict[str, Any]:
    return {
        "id": item.id, "started_at": item.started_at.isoformat(),
        "finished_at": item.finished_at.isoformat() if item.finished_at else None,
        "status": item.status, "trigger": item.trigger, "hostname": item.hostname,
        "profiles_processed": item.profiles_processed, "sources_processed": item.sources_processed,
        "listings_seen": item.listings_seen, "listings_new": item.listings_new,
        "listings_changed": item.listings_changed, "price_drops": item.price_drops,
        "listings_removed": item.listings_removed, "detail_requests": item.detail_requests,
        "llm_calls": item.llm_calls, "llm_cache_hits": item.llm_cache_hits,
        "warning_count": item.warning_count, "error_count": item.error_count,
    }
