"""Unified collection run service (MVP-05).

Ties corp code import, disclosure collection, news collection, and analysis
into a single :class:`CollectionRun` so the whole pipeline can be triggered
with one API call and tracked as one execution unit.

Each step is committed as it finishes so a later failure keeps the data that
already succeeded. The run is marked ``failed`` when any executed step fails
to start (for example a missing API key) and ``success`` otherwise; per-symbol
problems are reported in ``message`` without failing the whole run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kospi_core import Analyzer, RuleBasedAnalyzer

from app.config import get_settings
from app.models import CollectionRun, Symbol, utcnow
from app.services.ai_summarizer import Summarizer
from app.services.analyzer import analyze_targets
from app.services.naver_news import NaverNewsError, collect_news_for_symbols
from app.services.news_summary import summarize_recent_for_symbols
from app.services.opendart import (
    OpenDartError,
    collect_disclosures_for_symbols,
    download_corp_code_zip,
    import_corp_codes,
)
from app.services.prices import collect_prices_for_symbols

COLLECTION_RUN_TYPE = "collection"

# A collection run still 'running' long past this is treated as dead — its
# process was killed before the in-process error handler could record it.
_STALE_RUN_AFTER_SECONDS = 30 * 60


class CollectionInProgressError(RuntimeError):
    """Raised when a collection run cannot start: one is already running."""


@dataclass
class CollectionOptions:
    """Which steps a collection run should execute."""

    symbol_ids: list[int] | None = None
    import_corp_codes: bool = False
    include_disclosures: bool = True
    include_news: bool = True
    include_prices: bool = True
    analyze: bool = True


def _select_symbols(db: Session, symbol_ids: list[int] | None) -> list[Symbol]:
    query = select(Symbol)
    if symbol_ids:
        query = query.where(Symbol.id.in_(symbol_ids))
    return list(db.execute(query.order_by(Symbol.market, Symbol.code)).scalars())


def _step_note(label: str, processed: int, inserted: int, failures: list[str]) -> str:
    note = f"{label} {processed}종목/신규 {inserted}건"
    if failures:
        note += f"/실패 {len(failures)}건"
    return note


def _reclaim_stale_runs(db: Session) -> None:
    """Fail collection runs left ``running`` long past any real run.

    A row stays ``running`` when its process is killed mid-collection. Left
    alone it would hold the single-running slot forever (the partial unique
    index) and block every future run.
    """
    cutoff = utcnow() - timedelta(seconds=_STALE_RUN_AFTER_SECONDS)
    stale = list(
        db.execute(
            select(CollectionRun)
            .where(CollectionRun.run_type == COLLECTION_RUN_TYPE)
            .where(CollectionRun.status == "running")
            .where(CollectionRun.started_at < cutoff)
        ).scalars()
    )
    for run in stale:
        run.status = "failed"
        run.finished_at = utcnow()
        run.message = "수집이 비정상 종료되어 실패로 정리되었습니다."
    if stale:
        db.commit()


def run_collection(
    db: Session,
    options: CollectionOptions | None = None,
    *,
    opendart_api_key: str | None = None,
    naver_client_id: str | None = None,
    naver_client_secret: str | None = None,
    corp_code_downloader=None,
    disclosure_fetcher=None,
    news_fetcher=None,
    price_fetcher=None,
    analyzer: Analyzer | None = None,
    ai_summarizer: Summarizer | None = None,
) -> CollectionRun:
    """Run the requested collection steps as one :class:`CollectionRun`.

    Keys default to the configured settings; the downloader/fetchers/analyzer
    are injectable for tests. Returns the recorded run.
    """
    options = options or CollectionOptions()
    settings = get_settings()
    if opendart_api_key is None:
        opendart_api_key = settings.opendart_api_key
    if naver_client_id is None:
        naver_client_id = settings.naver_client_id
    if naver_client_secret is None:
        naver_client_secret = settings.naver_client_secret
    if analyzer is None:
        analyzer = RuleBasedAnalyzer()

    _reclaim_stale_runs(db)
    run = CollectionRun(run_type=COLLECTION_RUN_TYPE, status="running")
    db.add(run)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CollectionInProgressError(
            "이미 수집이 진행 중입니다. 잠시 후 다시 시도해 주세요."
        ) from exc

    notes: list[str] = []
    step_failed = False
    try:
        symbols = _select_symbols(db, options.symbol_ids)
        disclosures_inserted = 0
        news_inserted = 0

        if options.import_corp_codes:
            try:
                inserted, updated, total = import_corp_codes(
                    db,
                    opendart_api_key or "",
                    corp_code_downloader or download_corp_code_zip,
                )
                db.commit()
                notes.append(
                    f"corp code 신규 {inserted}/갱신 {updated}/전체 {total}"
                )
            except OpenDartError as exc:
                db.rollback()
                step_failed = True
                notes.append(f"corp code 실패: {exc}")

        if options.include_disclosures:
            try:
                processed, inserted, failures = collect_disclosures_for_symbols(
                    db,
                    symbols,
                    api_key=opendart_api_key or "",
                    fetcher=disclosure_fetcher,
                )
                db.commit()
                disclosures_inserted = inserted
                notes.append(_step_note("공시", processed, inserted, failures))
            except OpenDartError as exc:
                db.rollback()
                step_failed = True
                notes.append(f"공시 수집 실패: {exc}")

        if options.include_news:
            try:
                processed, inserted, failures = collect_news_for_symbols(
                    db,
                    symbols,
                    client_id=naver_client_id or "",
                    client_secret=naver_client_secret or "",
                    fetcher=news_fetcher,
                )
                db.commit()
                news_inserted = inserted
                notes.append(_step_note("뉴스", processed, inserted, failures))
            except NaverNewsError as exc:
                db.rollback()
                step_failed = True
                notes.append(f"뉴스 수집 실패: {exc}")
            else:
                # Eagerly summarize the most recent news per symbol so the
                # reading pane has a real AI summary ready on first view. A
                # missing API key turns this into a no-op (see _NullSummarizer);
                # any other LLM failure is logged and the row keeps its
                # rule-based fallback.
                eager_count = settings.ai_summary_eager_per_symbol
                if eager_count > 0:
                    summarized = summarize_recent_for_symbols(
                        db,
                        [symbol.id for symbol in symbols],
                        per_symbol=eager_count,
                        summarizer=ai_summarizer,
                    )
                    if summarized:
                        notes.append(f"AI 요약 {summarized}건")

        if options.include_prices:
            # Prices have no auth/quota step that could fail before the loop,
            # so any error is per-symbol and folded into ``failures``. Symbols
            # already refreshed earlier today are skipped without a fetch.
            processed, inserted, skipped, failures = collect_prices_for_symbols(
                db,
                symbols,
                fetcher=price_fetcher,
            )
            db.commit()
            note = _step_note("시세", processed, inserted, failures)
            if skipped:
                note += f"/최신 {skipped}종목"
            notes.append(note)

        if options.analyze:
            news_count, disclosure_count = analyze_targets(db, analyzer)
            db.commit()
            notes.append(f"분석 뉴스 {news_count}/공시 {disclosure_count}")

        run.symbols_processed = len(symbols)
        run.disclosures_inserted = disclosures_inserted
        run.news_inserted = news_inserted
        run.finished_at = utcnow()
        run.status = "failed" if step_failed else "success"
        run.message = " | ".join(notes) if notes else "수행할 단계가 없습니다."
        db.commit()
    except Exception as exc:  # broad: any failure must still be recorded
        db.rollback()
        run.status = "failed"
        run.finished_at = utcnow()
        run.message = f"수집 실행 중 예상치 못한 오류: {exc}"
        db.commit()
    return run


def run_scheduled_collection(
    db: Session, options: CollectionOptions | None = None
) -> CollectionRun | None:
    """Run one collection unless one is already in progress.

    Returns the recorded :class:`CollectionRun`, or ``None`` when another
    collection run is already running. The partial unique index on
    ``collection_runs`` rejects the duplicate atomically, so there is no
    check-then-insert race.
    """
    try:
        return run_collection(db, options or CollectionOptions())
    except CollectionInProgressError:
        return None
