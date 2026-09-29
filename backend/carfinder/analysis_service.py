from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from carfinder.analysis import (
    KNOWLEDGE_VERSION,
    PROMPT_VERSION,
    ListingAnalysisResult,
    deterministic_analysis,
    llm_cache_key,
    semantic_hash,
)
from carfinder.config import Settings
from carfinder.db.models import Listing, ListingAnalysis, ListingClaim, ListingSnapshot, LlmCache, ScrapeRun, ScrapeRunMessage
from carfinder.llm import ListingAnalysisRequest, get_llm_provider
from carfinder.privacy import redact_contact_details


def _unique(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result = []
    for item in items:
        key = item.model_dump_json(exclude_none=True)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _llm_request(snapshot: ListingSnapshot, deterministic: ListingAnalysisResult) -> ListingAnalysisRequest:
    return ListingAnalysisRequest(
        listing={
            "title": redact_contact_details(snapshot.title or ""),
            "description": redact_contact_details(snapshot.description or ""),
            "vehicle": {
                "make": snapshot.make, "model": snapshot.model, "generation": snapshot.generation,
                "trim": snapshot.trim, "year": snapshot.year, "fuel": snapshot.fuel,
                "mileage_km": snapshot.mileage_km, "engine_cc": snapshot.engine_cc,
                "power_kw": snapshot.power_kw, "transmission": snapshot.transmission,
                "drive": snapshot.drive, "body_type": snapshot.body_type,
            },
            "features": snapshot.features_json or [],
            "condition": snapshot.condition_json or {},
        },
        existing_deterministic_signals=[item.model_dump(mode="json") for item in deterministic.risk_signals],
    )


async def analyze_snapshot(
    session: Session,
    run: ScrapeRun,
    listing: Listing,
    snapshot: ListingSnapshot,
    settings: Settings,
    *,
    allow_llm: bool = True,
    force: bool = False,
    bypass_cache: bool = False,
) -> ListingAnalysis:
    existing = session.scalar(select(ListingAnalysis).where(ListingAnalysis.snapshot_id == snapshot.id))
    llm_active = settings.llm.enabled and settings.llm.provider != "none"
    if existing is not None and not force and existing.status == "complete":
        if not llm_active or (
            existing.llm_provider == settings.llm.provider and existing.llm_model == settings.llm.model
        ):
            return existing

    deterministic = deterministic_analysis(snapshot)
    combined = deterministic
    status = "complete"
    cache_key: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    if llm_active and not allow_llm:
        status = "pending"
    if llm_active and allow_llm:
        provider_name = settings.llm.provider
        model_name = settings.llm.model
        cache_key = llm_cache_key(snapshot, provider_name, model_name)
        cached = None if bypass_cache else session.get(LlmCache, cache_key)
        if cached is not None:
            try:
                llm_result = ListingAnalysisResult.model_validate(cached.response_json)
                run.llm_cache_hits += 1
            except Exception:
                cached = None
        if cached is None:
            run.llm_calls += 1
            try:
                provider = get_llm_provider(
                    provider_name, settings.llm.command, settings.llm.timeout_seconds, model_name
                )
                llm_result = await provider.analyze_listing(_llm_request(snapshot, deterministic))
                session.merge(LlmCache(
                    cache_key=cache_key, provider=provider_name, model=model_name,
                    prompt_version=PROMPT_VERSION, knowledge_version=KNOWLEDGE_VERSION,
                    response_json=llm_result.model_dump(mode="json"),
                ))
            except Exception as error:
                status = "partial"
                session.add(ScrapeRunMessage(
                    run_id=run.id, level="warning", code="llm_analysis_failed",
                    message=f"Optional LLM analysis failed: {type(error).__name__}",
                    context_json={"listing_id": listing.id, "provider": provider_name},
                ))
                run.warning_count += 1
                llm_result = None
        if llm_result is not None:
            combined = deterministic.model_copy(update={
                "positive_claims": _unique(deterministic.positive_claims + llm_result.positive_claims),
                "concerns": _unique(deterministic.concerns + llm_result.concerns),
                "missing_information": _unique(deterministic.missing_information + llm_result.missing_information),
                "questions_to_ask": _unique(deterministic.questions_to_ask + llm_result.questions_to_ask),
                "extracted_claims": _unique(deterministic.extracted_claims + llm_result.extracted_claims),
                "risk_signals": _unique(deterministic.risk_signals + llm_result.risk_signals),
            })

    if existing is None:
        existing = ListingAnalysis(
            listing_id=listing.id, snapshot_id=snapshot.id,
            semantic_hash=semantic_hash(snapshot), status=status,
            result_json=combined.model_dump(mode="json"),
            llm_provider=provider_name, llm_model=model_name,
            prompt_version=PROMPT_VERSION if provider_name else None,
        )
        session.add(existing)
    else:
        existing.semantic_hash = semantic_hash(snapshot)
        existing.status = status
        existing.result_json = combined.model_dump(mode="json")
        existing.llm_provider = provider_name
        existing.llm_model = model_name
        existing.prompt_version = PROMPT_VERSION if provider_name else None

    session.execute(delete(ListingClaim).where(ListingClaim.snapshot_id == snapshot.id))
    claim_sources = [(claim, "seller_description") for claim in deterministic.extracted_claims]
    if llm_active and allow_llm and status == "complete" and provider_name:
        llm_only = [claim for claim in combined.extracted_claims if claim not in deterministic.extracted_claims]
        claim_sources.extend((claim, "llm_extraction") for claim in llm_only)
    for claim, source_type in claim_sources:
        session.add(ListingClaim(
            listing_id=listing.id, snapshot_id=snapshot.id,
            claim_type=claim.claim_type, value_json=claim.value,
            source_type=source_type, source_text=claim.evidence,
            verification_status="claimed", confidence=claim.confidence,
        ))
    session.flush()
    return existing


async def analyze_stored_listings(
    settings: Settings,
    *,
    listing_id: int | None = None,
    force: bool = False,
) -> dict[str, int | str]:
    from carfinder.db.engine import create_database_engine

    engine = create_database_engine(settings.database_path)
    try:
        with Session(engine) as session:
            run = ScrapeRun(trigger="analyze")
            session.add(run)
            session.flush()
            query = select(Listing).order_by(Listing.id)
            if listing_id is not None:
                query = query.where(Listing.id == listing_id)
            listings = session.scalars(query).all()
            if listing_id is not None and not listings:
                raise LookupError(f"Listing {listing_id} not found")
            analyzed_count = 0
            for listing in listings:
                snapshot = session.get(ListingSnapshot, listing.current_snapshot_id) if listing.current_snapshot_id else None
                if snapshot is None:
                    continue
                await analyze_snapshot(session, run, listing, snapshot, settings, force=force, bypass_cache=force)
                analyzed_count += 1
                session.commit()
            from carfinder.scoring_service import recompute_all_scores
            try:
                with session.begin_nested():
                    recompute_all_scores(session)
            except Exception as error:
                session.add(ScrapeRunMessage(
                    run_id=run.id, level="warning", code="scoring_recompute_failed",
                    message=f"Valuation or score refresh failed: {type(error).__name__}",
                ))
                run.warning_count += 1
            run.status = "partial" if run.warning_count else "success"
            run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()
            return {"run_id": run.id, "status": run.status, "listings_analyzed": analyzed_count,
                    "llm_calls": run.llm_calls, "llm_cache_hits": run.llm_cache_hits,
                    "warning_count": run.warning_count}
    finally:
        engine.dispose()
