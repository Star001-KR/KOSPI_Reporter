from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.symbol_catalog import (
    normalize_code as normalize_symbol_code,
    normalize_market as normalize_symbol_market,
    normalize_text,
)


class HoldingInput(BaseModel):
    quantity: float | None = Field(default=None, ge=0)
    average_cost: float | None = Field(default=None, ge=0)
    market_value: float | None = Field(default=None, ge=0)
    portfolio_weight: float | None = Field(default=None, ge=0, le=100)


class HoldingRead(HoldingInput):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol_id: int
    created_at: datetime
    updated_at: datetime


class SymbolBase(BaseModel):
    market: str = Field(min_length=1, max_length=16)
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    memo: str | None = None

    @field_validator("market", mode="before")
    @classmethod
    def normalize_market(cls, value: str) -> str:
        normalized = normalize_symbol_market(str(value))
        if normalized is None:
            raise ValueError("market must be KOSPI or KOSDAQ")
        return normalized

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return normalize_symbol_code(str(value)) or ""

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_text(str(value)) or ""

    @field_validator("memo", mode="before")
    @classmethod
    def normalize_memo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None


class SymbolCreate(BaseModel):
    market: str = Field(default="KOSPI", min_length=1, max_length=16)
    code: str | None = Field(default=None, max_length=32)
    name: str | None = Field(default=None, max_length=120)
    memo: str | None = None
    holding: HoldingInput | None = None

    @field_validator("market", mode="before")
    @classmethod
    def normalize_market(cls, value: str) -> str:
        normalized = normalize_symbol_market(str(value))
        if normalized is None:
            raise ValueError("market must be KOSPI or KOSDAQ")
        return normalized

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return normalize_symbol_code(value)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return normalize_text(value)

    @field_validator("memo", mode="before")
    @classmethod
    def normalize_memo(cls, value: str | None) -> str | None:
        return normalize_text(value)


class SymbolPatch(BaseModel):
    market: str | None = Field(default=None, min_length=1, max_length=16)
    code: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    memo: str | None = None
    holding: HoldingInput | None = None

    @field_validator("market", mode="before")
    @classmethod
    def normalize_optional_market(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_symbol_market(value)
        if normalized is None:
            raise ValueError("market must be KOSPI or KOSDAQ")
        return normalized

    @field_validator("code", mode="before")
    @classmethod
    def normalize_optional_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_symbol_code(value)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_text(value)

    @field_validator("memo", mode="before")
    @classmethod
    def normalize_optional_memo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_text(value)


class SymbolLookupRead(BaseModel):
    market: str
    code: str
    name: str


class SymbolRead(SymbolBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    holding: HoldingRead | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    created_at: datetime
    last_login_at: datetime | None = None


class AnalysisResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_type: Literal["news", "disclosure"]
    target_id: int
    summary: str
    sentiment: Literal["positive", "negative", "neutral"]
    importance: int
    portfolio_impact: str
    rationale: str | None = None
    model_name: str
    model_version: str
    created_at: datetime


class NewsItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol_id: int
    title: str
    summary: str | None = None
    source: str | None = None
    original_url: str
    canonical_url: str
    published_at: datetime | None = None
    collected_at: datetime
    ai_summary: str | None = None
    ai_summary_model: str | None = None
    ai_summary_at: datetime | None = None


class DisclosureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol_id: int
    rcept_no: str
    report_name: str
    corp_code: str | None = None
    corp_name: str | None = None
    submitted_at: datetime | None = None
    original_url: str
    collected_at: datetime


class AnalyzedNewsItem(BaseModel):
    item: NewsItemRead
    analysis: AnalysisResultRead | None = None


class AnalyzedDisclosure(BaseModel):
    item: DisclosureRead
    analysis: AnalysisResultRead | None = None


class SymbolDetail(SymbolRead):
    news_items: list[AnalyzedNewsItem] = Field(default_factory=list)
    disclosures: list[AnalyzedDisclosure] = Field(default_factory=list)


class BriefPosition(BaseModel):
    symbol: SymbolRead
    news_count: int
    disclosure_count: int
    latest_collected_at: datetime | None = None


class BriefItem(BaseModel):
    kind: Literal["news", "disclosure"]
    symbol_id: int
    symbol_name: str
    title: str
    source: str | None = None
    original_url: str
    occurred_at: datetime | None = None
    sentiment: Literal["positive", "negative", "neutral"] | None = None
    importance: int | None = None


class PortfolioBrief(BaseModel):
    total_symbols: int
    total_market_value: float
    latest_collected_at: datetime | None = None
    positions: list[BriefPosition]
    latest_items: list[BriefItem]


class MockActivityResult(BaseModel):
    symbol_id: int
    news_inserted: int
    disclosures_inserted: int


class CollectionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    symbols_processed: int
    news_inserted: int
    disclosures_inserted: int
    message: str | None = None


class CollectionRunRequest(BaseModel):
    symbol_ids: list[int] | None = None
    import_corp_codes: bool = False
    include_disclosures: bool = True
    include_news: bool = True
    include_prices: bool = True
    analyze: bool = True


class DailyPriceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trade_date: str
    close: float
