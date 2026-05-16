"""Analysis service (MVP-04).

Reads collected news and disclosures that do not yet have an analysis result,
runs them through the keyless ``RuleBasedAnalyzer`` from ``kospi_core``, and
stores structured output in the ``analysis_results`` table.

The analyzer is swappable: any object implementing the ``Analyzer`` protocol
(for example an LLM-backed analyzer) can be passed to :func:`analyze_pending`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from kospi_core import AnalysisDraft, AnalysisSubject, Analyzer, RuleBasedAnalyzer

from app.models import (
    AnalysisResult,
    CollectionRun,
    Disclosure,
    NewsItem,
    Symbol,
    utcnow,
)

ANALYSIS_RUN_TYPE = "analysis"


def _analyzed_target_ids(db: Session, target_type: str) -> set[int]:
    """Return the ids of targets that already have an analysis result."""
    return set(
        db.execute(
            select(AnalysisResult.target_id).where(
                AnalysisResult.target_type == target_type
            )
        ).scalars()
    )


def _store_analysis(
    db: Session, target_type: str, target_id: int, draft: AnalysisDraft
) -> None:
    db.add(
        AnalysisResult(
            target_type=target_type,
            target_id=target_id,
            summary=draft.summary,
            sentiment=draft.sentiment,
            importance=draft.importance,
            portfolio_impact=draft.portfolio_impact,
            rationale=draft.rationale,
            model_name=draft.model_name,
            model_version=draft.model_version,
        )
    )


def _analyze_news(db: Session, analyzer: Analyzer) -> int:
    done = _analyzed_target_ids(db, "news")
    rows = db.execute(
        select(NewsItem, Symbol).join(Symbol, Symbol.id == NewsItem.symbol_id)
    ).all()
    count = 0
    for news, symbol in rows:
        if news.id in done:
            continue
        draft = analyzer.analyze(
            AnalysisSubject(
                kind="news",
                symbol_name=symbol.name,
                title=news.title,
                body=news.summary,
            )
        )
        _store_analysis(db, "news", news.id, draft)
        count += 1
    return count


def _analyze_disclosures(db: Session, analyzer: Analyzer) -> int:
    done = _analyzed_target_ids(db, "disclosure")
    rows = db.execute(
        select(Disclosure, Symbol).join(Symbol, Symbol.id == Disclosure.symbol_id)
    ).all()
    count = 0
    for disclosure, symbol in rows:
        if disclosure.id in done:
            continue
        draft = analyzer.analyze(
            AnalysisSubject(
                kind="disclosure",
                symbol_name=symbol.name,
                title=disclosure.report_name,
                body=None,
            )
        )
        _store_analysis(db, "disclosure", disclosure.id, draft)
        count += 1
    return count


def analyze_pending(
    db: Session, *, analyzer: Analyzer | None = None
) -> CollectionRun:
    """Analyze every news and disclosure row that has no analysis yet.

    The result is recorded as a :class:`CollectionRun`. Re-running only
    analyzes rows added since the previous run, so analysis results are never
    duplicated.
    """
    if analyzer is None:
        analyzer = RuleBasedAnalyzer()

    run = CollectionRun(run_type=ANALYSIS_RUN_TYPE, status="running")
    db.add(run)
    db.commit()

    try:
        news_count = _analyze_news(db, analyzer)
        disclosure_count = _analyze_disclosures(db, analyzer)
        run.status = "success"
        run.finished_at = utcnow()
        run.message = f"분석 완료: 뉴스 {news_count}건, 공시 {disclosure_count}건."
        db.commit()
    except Exception as exc:  # broad: any failure must still be recorded
        db.rollback()
        run.status = "failed"
        run.finished_at = utcnow()
        run.message = f"분석 중 예상치 못한 오류: {exc}"
        db.commit()
    return run
