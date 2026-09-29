from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from carfinder.config import Settings
from carfinder.db.engine import create_database_engine
from carfinder.db.models import (
    Listing,
    ListingEvent,
    ListingSnapshot,
    ProfileListingMatch,
    ProviderSource,
    ProviderSourceListing,
    ScrapeRun,
    ScrapeRunMessage,
    SearchProfile,
)
from carfinder.providers.base import DiscoveredListing, NormalizedListing, ProviderSearchSource, RunContext
from carfinder.providers.registry import get_provider


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    status: str
    profiles_processed: int
    sources_processed: int
    listings_seen: int
    listings_new: int
    listings_changed: int
    price_drops: int
    listings_removed: int
    detail_requests: int
    warning_count: int
    error_count: int


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _content_hash(listing: NormalizedListing) -> str:
    payload = listing.model_dump(
        mode="json",
        exclude={"provider", "external_id", "url", "structured", "provider_payload"},
    )
    payload["description"] = " ".join((listing.description or "").split())
    payload["features"] = sorted(set(listing.features))
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _snapshot(listing_id: int, listing: NormalizedListing) -> ListingSnapshot:
    return ListingSnapshot(
        listing_id=listing_id,
        content_hash=_content_hash(listing),
        title=listing.title,
        description=listing.description,
        price_amount=listing.price_amount,
        price_currency=listing.price_currency,
        year=listing.year,
        make=listing.make,
        model=listing.model,
        generation=listing.generation,
        trim=listing.trim,
        mileage_km=listing.mileage_km,
        fuel=listing.fuel,
        engine_cc=listing.engine_cc,
        power_kw=listing.power_kw,
        transmission=listing.transmission,
        drive=listing.drive,
        body_type=listing.body_type,
        doors=listing.doors,
        seats=listing.seats,
        location_raw=listing.location_raw,
        city=listing.city,
        region=listing.region,
        seller_type=listing.seller_type,
        structured_json=listing.structured,
        features_json=listing.features,
        condition_json=listing.condition,
        provider_payload_json=listing.provider_payload,
        images_json=listing.images,
    )


def _message(session: Session, run: ScrapeRun, level: str, code: str, message: str, context: dict[str, Any] | None = None) -> None:
    session.add(ScrapeRunMessage(run_id=run.id, level=level, code=code, message=message, context_json=context or {}))
    if level == "warning":
        run.warning_count += 1
    elif level == "error":
        run.error_count += 1


def _event(
    session: Session,
    listing: Listing,
    event_type: str,
    snapshot_id: int | None,
    old: Any = None,
    new: Any = None,
) -> None:
    session.add(
        ListingEvent(
            listing_id=listing.id,
            event_type=event_type,
            snapshot_id=snapshot_id,
            old_value_json=old,
            new_value_json=new,
        )
    )


def _changed_fields(previous: ListingSnapshot, current: NormalizedListing) -> dict[str, tuple[Any, Any]]:
    names = (
        "title", "year", "make", "model", "generation", "trim", "mileage_km", "fuel",
        "engine_cc", "power_kw", "transmission", "drive", "body_type", "doors", "seats",
        "location_raw", "city", "region", "seller_type",
    )
    changed = {
        name: (getattr(previous, name), getattr(current, name))
        for name in names
        if getattr(previous, name) != getattr(current, name)
    }
    for name, old_value, new_value in (
        ("features", previous.features_json, current.features),
        ("condition", previous.condition_json, current.condition),
        ("images", previous.images_json, current.images),
    ):
        if old_value != new_value:
            changed[name] = (old_value, new_value)
    return changed


async def _store_listing(
    session: Session,
    run: ScrapeRun,
    profile: SearchProfile,
    source: ProviderSource,
    discovered: DiscoveredListing,
    provider,
    context: RunContext,
    detail_recheck_hours: int,
) -> None:
    now = _utcnow()
    listing = session.scalar(
        select(Listing).where(Listing.provider == discovered.provider, Listing.external_id == discovered.external_id)
    )
    created = listing is None
    if listing is None:
        listing = Listing(
            provider=discovered.provider,
            external_id=discovered.external_id,
            url=discovered.url,
            first_seen_at=now,
            last_seen_at=now,
            status="active",
        )
        session.add(listing)
        session.flush()
        run.listings_new += 1
        _event(session, listing, "discovered", None)
    else:
        was_removed = listing.status == "removed"
        listing.url = discovered.url
        listing.last_seen_at = now
        listing.missing_run_count = 0
        if was_removed:
            listing.status = "active"
            listing.removed_at = None
            _event(session, listing, "reappeared", listing.current_snapshot_id)

    source_listing = session.get(ProviderSourceListing, (source.id, listing.id))
    if source_listing is None:
        source_listing = ProviderSourceListing(source_id=source.id, listing_id=listing.id, first_seen_at=now, last_seen_at=now)
        session.add(source_listing)
    else:
        source_listing.last_seen_at = now
        source_listing.missing_run_count = 0
        source_listing.active = True

    match = session.get(ProfileListingMatch, (profile.id, listing.id))
    if match is None:
        match = ProfileListingMatch(
            profile_id=profile.id,
            listing_id=listing.id,
            hard_filter_pass=True,
            match_details_json={"source_id": source.id, "selection": "provider_search"},
        )
        session.add(match)
    else:
        match.last_matched_at = now

    session_listing = session.get(ListingSnapshot, listing.current_snapshot_id) if listing.current_snapshot_id else None
    should_fetch = (
        created
        or listing.last_detail_fetch_at is None
        or listing.last_detail_fetch_at <= now - timedelta(hours=detail_recheck_hours)
    )
    run.listings_seen += 1
    if not should_fetch:
        return

    run.detail_requests += 1
    try:
        raw = await provider.fetch_listing(discovered, context)
        normalized_detail = provider.normalize(raw)
    except Exception as error:
        _message(
            session,
            run,
            "error",
            "listing_detail_failed",
            f"Detail fetch or parsing failed: {type(error).__name__}: {error}",
            {"listing_id": listing.id, "source_id": source.id},
        )
        return
    if (normalized_detail.provider, normalized_detail.external_id) != (discovered.provider, discovered.external_id):
        _message(session, run, "error", "listing_identity_mismatch", "Provider detail identity did not match search result", {"listing_id": listing.id})
        return
    listing.url = normalized_detail.url
    listing.last_detail_fetch_at = now
    digest = _content_hash(normalized_detail)
    if session_listing is not None and session_listing.content_hash == digest:
        return

    previous = session_listing
    snapshot = _snapshot(listing.id, normalized_detail)
    session.add(snapshot)
    session.flush()
    listing.current_snapshot_id = snapshot.id
    if previous is None:
        return

    changed = _changed_fields(previous, normalized_detail)
    price_changed = previous.price_amount != normalized_detail.price_amount or previous.price_currency != normalized_detail.price_currency
    description_changed = previous.description != normalized_detail.description
    if price_changed:
        old_price = {"amount": previous.price_amount, "currency": previous.price_currency}
        new_price = {"amount": normalized_detail.price_amount, "currency": normalized_detail.price_currency}
        event_type = "price_changed"
        if previous.price_currency in {"EUR", "RSD"} and previous.price_currency == normalized_detail.price_currency and previous.price_amount is not None and normalized_detail.price_amount is not None:
            event_type = "price_dropped" if normalized_detail.price_amount < previous.price_amount else "price_increased"
        _event(session, listing, event_type, snapshot.id, old_price, new_price)
        if event_type == "price_dropped":
            run.price_drops += 1
    if description_changed:
        _event(
            session,
            listing,
            "description_changed",
            snapshot.id,
            {"description": previous.description},
            {"description": normalized_detail.description},
        )
    remaining = {key: value for key, value in changed.items() if key not in {"title"}}
    if remaining:
        _event(
            session,
            listing,
            "specifications_changed",
            snapshot.id,
            {key: pair[0] for key, pair in remaining.items()},
            {key: pair[1] for key, pair in remaining.items()},
        )
    if changed and not price_changed and not description_changed and not remaining:
        _event(session, listing, "listing_changed", snapshot.id, {"title": previous.title}, {"title": normalized_detail.title})
    run.listings_changed += 1


async def _process_source(
    session: Session,
    run: ScrapeRun,
    profile: SearchProfile,
    source: ProviderSource,
    provider,
    context: RunContext,
    settings: Settings,
) -> bool:
    source_model = ProviderSearchSource(
        id=source.id, provider=source.provider, search_url=source.search_url, profile_id=profile.id
    )
    validation = provider.validate_source(source_model)
    if not validation.valid:
        _message(session, run, "error", "invalid_source", validation.message, {"source_id": source.id})
        session.commit()
        return False

    try:
        discovered_listings = [item async for item in provider.search(source_model, context)]
    except Exception as error:
        _message(session, run, "error", "source_search_failed", f"Search failed: {type(error).__name__}: {error}", {"source_id": source.id})
        session.commit()
        return False

    seen_ids: set[int] = set()
    identity_error = False
    for discovered in discovered_listings:
        if discovered.provider != source.provider or not discovered.external_id.strip():
            _message(session, run, "error", "invalid_listing_identity", "Provider returned a listing with an invalid identity", {"source_id": source.id})
            identity_error = True
            continue
        listing = session.scalar(
            select(Listing).where(Listing.provider == discovered.provider, Listing.external_id == discovered.external_id)
        )
        if listing is not None:
            seen_ids.add(listing.id)
        await _store_listing(
            session, run, profile, source, discovered, provider, context, settings.scraping.detail_recheck_hours
        )
        if listing is None:
            listing = session.scalar(
                select(Listing).where(Listing.provider == discovered.provider, Listing.external_id == discovered.external_id)
            )
        if listing is not None:
            seen_ids.add(listing.id)
        session.commit()

    if identity_error:
        session.commit()
        return False

    now = _utcnow()
    links = session.scalars(
        select(ProviderSourceListing).where(ProviderSourceListing.source_id == source.id, ProviderSourceListing.active.is_(True))
    ).all()
    for link in links:
        if link.listing_id in seen_ids:
            continue
        link.missing_run_count += 1
        listing = session.get(Listing, link.listing_id)
        if listing is None:
            continue
        listing.missing_run_count = max(listing.missing_run_count, link.missing_run_count)
        if link.missing_run_count >= settings.scraping.removed_after_missing_runs:
            link.active = False
            other_sources = session.scalar(
                select(ProviderSourceListing.source_id).where(
                    ProviderSourceListing.listing_id == listing.id,
                    ProviderSourceListing.active.is_(True),
                    ProviderSourceListing.source_id != source.id,
                ).limit(1)
            )
            if other_sources is None and listing.status != "removed":
                listing.status = "removed"
                listing.removed_at = now
                run.listings_removed += 1
                _event(session, listing, "removed", listing.current_snapshot_id)

    source.first_scan_completed = True
    run.sources_processed += 1
    session.commit()
    return True


async def run_pipeline(
    settings: Settings,
    *,
    profile_name: str | None = None,
    provider_id: str | None = None,
    trigger: str = "cli",
) -> RunSummary:
    engine = create_database_engine(settings.database_path)
    run_id: int | None = None
    try:
        with Session(engine) as session:
            run = ScrapeRun(trigger=trigger, hostname=socket.gethostname())
            session.add(run)
            session.commit()
            run_id = run.id
            query = select(SearchProfile).where(SearchProfile.enabled.is_(True))
            if profile_name:
                query = select(SearchProfile).where(SearchProfile.name == profile_name)
            profiles = session.scalars(query.order_by(SearchProfile.id)).all()
            if profile_name and not profiles:
                _message(session, run, "error", "profile_not_found", f"No profile named {profile_name!r}")
                run.status = "failed"
            else:
                work: list[tuple[SearchProfile, ProviderSource]] = []
                for profile in profiles:
                    sources = session.scalars(
                        select(ProviderSource).where(ProviderSource.profile_id == profile.id, ProviderSource.enabled.is_(True))
                    ).all()
                    work.extend((profile, source) for source in sources if provider_id is None or source.provider == provider_id)
                run.profiles_processed = len({profile.id for profile, _ in work})
                if not work:
                    _message(session, run, "info", "no_sources", "No enabled provider sources matched this run")
                else:
                    grouped: dict[str, list[tuple[SearchProfile, ProviderSource]]] = {}
                    for item in work:
                        grouped.setdefault(item[1].provider, []).append(item)

                    for current_provider_id, sources in grouped.items():
                        if current_provider_id == "polovniautomobili" and not settings.providers.polovniautomobili.enabled:
                            _message(session, run, "warning", "provider_disabled", f"Provider {current_provider_id} is disabled")
                            session.commit()
                            continue
                        try:
                            provider = get_provider(current_provider_id)
                        except ValueError as error:
                            _message(session, run, "error", "provider_unavailable", str(error))
                            session.commit()
                            continue
                        context = RunContext(
                            browser_profile=settings.browser_profile,
                            headless=settings.providers.polovniautomobili.headless,
                            request_delay_seconds=settings.scraping.request_delay_seconds,
                        )
                        try:
                            await provider.open_run(context)
                        except Exception as error:
                            for _profile, source in sources:
                                _message(session, run, "error", "provider_start_failed", f"Provider startup failed: {type(error).__name__}: {error}", {"source_id": source.id})
                            session.commit()
                            continue
                        try:
                            for profile, source in sources:
                                await _process_source(session, run, profile, source, provider, context, settings)
                        finally:
                            try:
                                await provider.close_run()
                            except Exception as error:
                                _message(session, run, "warning", "provider_close_failed", f"Provider shutdown warning: {type(error).__name__}: {error}")
            if run.status == "running":
                run.status = "failed" if run.error_count and not run.sources_processed else "partial" if run.error_count else "success"
            run.finished_at = _utcnow()
            session.commit()
            result = _summary(run)
    except Exception as error:
        if run_id is None:
            engine.dispose()
            raise
        with Session(engine) as session:
            run = session.get(ScrapeRun, run_id)
            if run is None:
                engine.dispose()
                raise
            _message(session, run, "error", "run_failed", f"Run failed: {type(error).__name__}: {error}")
            run.status = "failed"
            run.finished_at = _utcnow()
            session.commit()
            result = _summary(run)
    finally:
        engine.dispose()
    return result


def _summary(run: ScrapeRun) -> RunSummary:
    return RunSummary(
        run_id=run.id,
        status=run.status,
        profiles_processed=run.profiles_processed,
        sources_processed=run.sources_processed,
        listings_seen=run.listings_seen,
        listings_new=run.listings_new,
        listings_changed=run.listings_changed,
        price_drops=run.price_drops,
        listings_removed=run.listings_removed,
        detail_requests=run.detail_requests,
        warning_count=run.warning_count,
        error_count=run.error_count,
    )
