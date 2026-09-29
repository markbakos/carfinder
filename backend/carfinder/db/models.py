from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    trigger: Mapped[str] = mapped_column(String(24), nullable=False, default="cli")
    hostname: Mapped[str | None] = mapped_column(String(255))
    profiles_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sources_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listings_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listings_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listings_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_drops: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listings_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detail_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_cache_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
