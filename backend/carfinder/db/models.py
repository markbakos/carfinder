from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running", server_default="running")
    trigger: Mapped[str] = mapped_column(String(24), nullable=False, default="cli", server_default="cli")
    hostname: Mapped[str | None] = mapped_column(String(255))
    profiles_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sources_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    listings_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    listings_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    listings_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    price_drops: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    listings_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    detail_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    llm_cache_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class SearchProfile(Base):
    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("1"))
    filters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    preferences_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    initial_import_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="analyze_all", server_default="analyze_all")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class ProviderSource(Base):
    __tablename__ = "provider_sources"
    __table_args__ = (UniqueConstraint("profile_id", "provider", "search_url", name="uq_source_profile_provider_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("search_profiles.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(48), nullable=False)
    search_url: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("1"))
    source_settings_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    first_scan_completed: Mapped[bool] = mapped_column(nullable=False, default=False, server_default=text("0"))


class ProviderSourceListing(Base):
    __tablename__ = "provider_source_listings"
    __table_args__ = (Index("ix_source_listings_listing_active", "listing_id", "active"),)

    source_id: Mapped[int] = mapped_column(ForeignKey("provider_sources.id", ondelete="CASCADE"), primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    missing_run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("1"))


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_listing_provider_external_id"),
        Index("ix_listings_status_last_seen", "status", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False)
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    last_detail_fetch_at: Mapped[datetime | None] = mapped_column(DateTime)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", server_default="active")
    missing_run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    current_snapshot_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class ListingSnapshot(Base):
    __tablename__ = "listing_snapshots"
    __table_args__ = (Index("ix_snapshots_listing_observed", "listing_id", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price_amount: Mapped[int | None] = mapped_column(Integer)
    price_currency: Mapped[str | None] = mapped_column(String(3))
    year: Mapped[int | None] = mapped_column(Integer)
    make: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    generation: Mapped[str | None] = mapped_column(String(120))
    trim: Mapped[str | None] = mapped_column(String(160))
    mileage_km: Mapped[int | None] = mapped_column(Integer)
    fuel: Mapped[str | None] = mapped_column(String(32))
    engine_cc: Mapped[int | None] = mapped_column(Integer)
    power_kw: Mapped[int | None] = mapped_column(Integer)
    transmission: Mapped[str | None] = mapped_column(String(32))
    drive: Mapped[str | None] = mapped_column(String(24))
    body_type: Mapped[str | None] = mapped_column(String(48))
    doors: Mapped[int | None] = mapped_column(Integer)
    seats: Mapped[int | None] = mapped_column(Integer)
    location_raw: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    seller_type: Mapped[str | None] = mapped_column(String(32))
    structured_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    features_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    condition_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    provider_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    images_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class ListingEvent(Base):
    __tablename__ = "listing_events"
    __table_args__ = (Index("ix_listing_events_listing_occurred", "listing_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    old_value_json: Mapped[dict | None] = mapped_column(JSON)
    new_value_json: Mapped[dict | None] = mapped_column(JSON)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("listing_snapshots.id", ondelete="SET NULL"))


class ProfileListingMatch(Base):
    __tablename__ = "profile_listing_matches"
    __table_args__ = (Index("ix_profile_matches_last_matched", "last_matched_at"),)

    profile_id: Mapped[int] = mapped_column(ForeignKey("search_profiles.id", ondelete="CASCADE"), primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True)
    first_matched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    last_matched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    hard_filter_pass: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("1"))
    profile_fit_score: Mapped[int | None] = mapped_column(Integer)
    match_details_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ListingUserState(Base):
    __tablename__ = "listing_user_state"

    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="new", server_default="new")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    rejection_reason: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class ListingAnalysis(Base):
    __tablename__ = "listing_analysis"
    __table_args__ = (
        UniqueConstraint("snapshot_id", name="uq_analysis_snapshot"),
        Index("ix_analysis_listing_created", "listing_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("listing_snapshots.id", ondelete="CASCADE"), nullable=False)
    semantic_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    llm_provider: Mapped[str | None] = mapped_column(String(48))
    llm_model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())


class ListingClaim(Base):
    __tablename__ = "listing_claims"
    __table_args__ = (Index("ix_claims_listing_snapshot", "listing_id", "snapshot_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("listing_snapshots.id", ondelete="CASCADE"), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(80), nullable=False)
    value_json: Mapped[object] = mapped_column(JSON, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="claimed", server_default="claimed")
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())


class LlmCache(Base):
    __tablename__ = "llm_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    knowledge_version: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())


class ScrapeRunMessage(Base):
    __tablename__ = "scrape_run_messages"
    __table_args__ = (Index("ix_run_messages_run_created", "run_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
