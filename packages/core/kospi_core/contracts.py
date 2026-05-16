"""Shared contracts for KOSPI Reporter collectors and analyzers.

These value objects and interfaces carry no framework or database dependency,
so collectors (OpenDART, Naver News, ...) and analyzers (rule-based, LLM, ...)
can be swapped without touching the FastAPI app or the persistence layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

Sentiment = Literal["positive", "negative", "neutral"]
SubjectKind = Literal["news", "disclosure"]


@dataclass(frozen=True)
class SymbolRef:
    """Identity of a listed symbol handed to a collector."""

    market: str
    code: str
    name: str


@dataclass(frozen=True)
class NewsDraft:
    """Raw news article produced by a NewsCollector before persistence."""

    title: str
    original_url: str
    canonical_url: str
    summary: str | None = None
    source: str | None = None
    published_at: datetime | None = None
    raw_payload: dict | None = None


@dataclass(frozen=True)
class DisclosureDraft:
    """Raw disclosure produced by a DisclosureCollector before persistence."""

    rcept_no: str
    report_name: str
    original_url: str
    corp_code: str | None = None
    corp_name: str | None = None
    submitted_at: datetime | None = None
    raw_payload: dict | None = None


@dataclass(frozen=True)
class AnalysisSubject:
    """Text payload handed to an Analyzer.

    `body` is the optional longer text (news summary, disclosure detail) that
    the analyzer reads alongside the title.
    """

    kind: SubjectKind
    symbol_name: str
    title: str
    body: str | None = None


@dataclass(frozen=True)
class AnalysisDraft:
    """Structured analysis output, mirrors the analysis_results table."""

    summary: str
    sentiment: Sentiment
    importance: int
    portfolio_impact: str
    rationale: str
    model_name: str
    model_version: str


class NewsCollector(Protocol):
    """Collects raw news for a symbol from an external source."""

    def collect(self, symbol: SymbolRef) -> Sequence[NewsDraft]: ...


class DisclosureCollector(Protocol):
    """Collects raw disclosures for a symbol from an external source."""

    def collect(self, symbol: SymbolRef) -> Sequence[DisclosureDraft]: ...


class Analyzer(Protocol):
    """Turns a collected item into a structured analysis result."""

    def analyze(self, subject: AnalysisSubject) -> AnalysisDraft: ...
