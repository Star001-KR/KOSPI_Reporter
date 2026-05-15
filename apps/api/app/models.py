from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Symbol(Base):
    __tablename__ = "symbols"
    __table_args__ = (
        UniqueConstraint("market", "code", name="uq_symbols_market_code"),
        Index("ix_symbols_market_code", "market", "code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    memo: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    holding: Mapped[Holding | None] = relationship(
        back_populates="symbol",
        cascade="all, delete-orphan",
        uselist=False,
    )
    news_items: Mapped[list[NewsItem]] = relationship(
        back_populates="symbol",
        cascade="all, delete-orphan",
    )
    disclosures: Mapped[list[Disclosure]] = relationship(
        back_populates="symbol",
        cascade="all, delete-orphan",
    )


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol_id: Mapped[int] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    quantity: Mapped[float | None] = mapped_column(Numeric(20, 4))
    average_cost: Mapped[float | None] = mapped_column(Numeric(20, 4))
    market_value: Mapped[float | None] = mapped_column(Numeric(20, 2))
    portfolio_weight: Mapped[float | None] = mapped_column(Numeric(8, 4))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    symbol: Mapped[Symbol] = relationship(back_populates="holding")


class DartCorpCode(Base):
    __tablename__ = "dart_corp_codes"
    __table_args__ = (
        UniqueConstraint("corp_code", name="uq_dart_corp_codes_corp_code"),
        Index("ix_dart_corp_codes_stock_code", "stock_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corp_code: Mapped[str] = mapped_column(String(8), nullable=False)
    stock_code: Mapped[str | None] = mapped_column(String(16))
    corp_name: Mapped[str] = mapped_column(String(160), nullable=False)
    market: Mapped[str | None] = mapped_column(String(16))
    modified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_news_items_canonical_url"),
        Index("ix_news_items_symbol_collected", "symbol_id", "collected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol_id: Mapped[int] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(120))
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSON)

    symbol: Mapped[Symbol] = relationship(back_populates="news_items")


class Disclosure(Base):
    __tablename__ = "disclosures"
    __table_args__ = (
        UniqueConstraint("rcept_no", name="uq_disclosures_rcept_no"),
        Index("ix_disclosures_symbol_collected", "symbol_id", "collected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol_id: Mapped[int] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False
    )
    rcept_no: Mapped[str] = mapped_column(String(32), nullable=False)
    report_name: Mapped[str] = mapped_column(String(300), nullable=False)
    corp_code: Mapped[str | None] = mapped_column(String(8))
    corp_name: Mapped[str | None] = mapped_column(String(160))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSON)

    symbol: Mapped[Symbol] = relationship(back_populates="disclosures")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    __table_args__ = (
        Index("ix_analysis_target", "target_type", "target_id"),
        Index("ix_analysis_importance", "importance"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[str] = mapped_column(String(16), nullable=False)
    importance: Mapped[int] = mapped_column(Integer, nullable=False)
    portfolio_impact: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(80), default="mock-analyzer")
    model_version: Mapped[str] = mapped_column(String(40), default="0.1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    __table_args__ = (Index("ix_collection_runs_started", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    symbols_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    news_inserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    disclosures_inserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
