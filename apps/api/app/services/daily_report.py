"""Daily per-symbol report generator.

For every registered symbol this builds a short morning briefing — the most
recent trading day's close/move plus the latest news and disclosures — and asks
the local ``claude`` CLI (Sonnet) for a light summary and a buy/hold/sell
opinion. It mirrors :mod:`app.services.ai_summarizer` (the subprocess+stdin
adapter) and :mod:`app.services.news_summary` (per-target persistence), but kept
separate because a whole-symbol report is a different prompt, model, and cadence
from a single-article summary.

Every public entrypoint degrades instead of raising: a missing CLI yields a
no-op generator, a per-symbol failure is isolated so one bad symbol never aborts
the batch, and a malformed model reply falls back to a ``hold`` opinion.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DailyReport, Disclosure, NewsItem, Symbol
# research_symbol_ids unions a common stock with its preferred siblings so a
# preferred symbol's report still sees news collected under the common name.
from app.routers.symbols import research_symbol_ids
from app.services.prices import get_symbol_prices

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))
# Reports publish on weekday mornings once the clock passes 08:30 KST.
_REPORT_AFTER = dt_time(8, 30)
_RECENT_NEWS = 8
_RECENT_DISCLOSURES = 5
_DEFAULT_TIMEOUT_SECONDS = 120.0

_VALID_RECOMMENDATIONS = ("buy", "hold", "sell")

_SYSTEM_PROMPT = (
    "당신은 한국 주식 투자자를 위한 애널리스트입니다. 주어진 종목의 직전 거래일 "
    "시장 상황과 최근 뉴스·공시를 종합해, 오늘 아침에 읽을 가벼운 데일리 리포트를 "
    "작성합니다. 반드시 아래 형식을 그대로 지키세요:\n"
    "OPINION: BUY 또는 HOLD 또는 SELL 중 하나\n"
    "(빈 줄)\n"
    "3~5문장으로 핵심 상황과 판단을 한국어로 요약\n"
    "RATIONALE: 의견의 한 줄 근거\n\n"
    "제공된 사실에만 근거하고 과장이나 단정은 피하세요. 이 의견은 참고용이며 "
    "투자 권유가 아닙니다. 마크다운 기호나 따옴표는 쓰지 마세요."
)


# --- generator adapter ---------------------------------------------------


class ReportGenerator(Protocol):
    """Pluggable LLM adapter — returns the raw report text or ``None``."""

    model_name: str

    def generate(self, prompt: str) -> str | None: ...


@dataclass
class _NullReportGenerator:
    """Returned when no usable backend is found — every call is a no-op."""

    model_name: str = "disabled"

    def generate(self, prompt: str) -> str | None:
        return None


class ClaudeReportGenerator:
    """Generator that pipes the prompt through the local ``claude`` CLI.

    Mirrors :class:`app.services.ai_summarizer.ClaudeCodeSummarizer`: one-shot
    ``claude --print`` with tools off, prompt on stdin (argv is world-readable
    via ``ps``), errors and non-zero exits logged and swallowed.
    """

    def __init__(
        self,
        *,
        model: str,
        cli_path: str = "claude",
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.model_name = model
        self._cli_path = cli_path
        self._timeout = timeout_seconds

    def generate(self, prompt: str) -> str | None:
        try:
            result = subprocess.run(
                [
                    self._cli_path,
                    "--print",
                    "--model", self.model_name,
                    "--tools", "",
                    "--output-format", "text",
                    "--no-session-persistence",
                    "--system-prompt", _SYSTEM_PROMPT,
                ],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            logger.warning("claude CLI daily report failed", exc_info=True)
            return None
        if result.returncode != 0:
            logger.warning(
                "claude CLI exited %s for daily report: %s",
                result.returncode,
                (result.stderr or "")[:200].strip(),
            )
            return None
        text = (result.stdout or "").strip()
        return text or None


def get_report_generator() -> ReportGenerator:
    """Build a report generator from runtime settings.

    Degrades to :class:`_NullReportGenerator` when the ``claude`` CLI is not on
    PATH, so a host without Claude Code simply produces no reports.
    """
    settings = get_settings()
    cli_path = shutil.which(settings.claude_cli_path) or shutil.which("claude")
    if cli_path is None:
        return _NullReportGenerator()
    try:
        return ClaudeReportGenerator(
            model=settings.ai_daily_report_model,
            cli_path=cli_path,
            timeout_seconds=settings.ai_daily_report_timeout_seconds,
        )
    except Exception:
        logger.warning("Failed to initialise ClaudeReportGenerator", exc_info=True)
        return _NullReportGenerator()


# --- context aggregation -------------------------------------------------


@dataclass(frozen=True)
class _SymbolContext:
    prompt: str
    prev_trade_date: str | None
    prev_close: float | None
    change_pct: float | None


def _price_snapshot(
    db: Session, symbol: Symbol
) -> tuple[str | None, float | None, float | None]:
    """Return ``(prev_trade_date, prev_close, change_pct)`` for the symbol.

    Uses the two most recent cached closes; "yesterday" is the latest trading
    day on record, not the calendar day, so a holiday simply means the last
    open day is used. A cold cache yields all ``None``.
    """
    prices = get_symbol_prices(db, symbol, days=2)
    if not prices:
        return None, None, None
    latest = prices[-1]
    prev_close = float(latest.close)
    change_pct: float | None = None
    if len(prices) >= 2:
        before = float(prices[-2].close)
        if before:
            change_pct = (prev_close - before) / before * 100
    return latest.trade_date, prev_close, change_pct


def _recent_news_lines(db: Session, research_ids: list[int]) -> list[str]:
    rows = db.execute(
        select(NewsItem)
        .where(NewsItem.symbol_id.in_(research_ids))
        .order_by(NewsItem.collected_at.desc())
        .limit(_RECENT_NEWS)
    ).scalars()
    lines: list[str] = []
    for news in rows:
        body = (news.ai_summary or news.summary or "").strip()
        lines.append(f"- {news.title} — {body}" if body else f"- {news.title}")
    return lines


def _recent_disclosure_lines(db: Session, research_ids: list[int]) -> list[str]:
    rows = db.execute(
        select(Disclosure)
        .where(Disclosure.symbol_id.in_(research_ids))
        .order_by(Disclosure.collected_at.desc())
        .limit(_RECENT_DISCLOSURES)
    ).scalars()
    return [f"- {disclosure.report_name}" for disclosure in rows]


def _build_symbol_context(db: Session, symbol: Symbol) -> _SymbolContext:
    prev_trade_date, prev_close, change_pct = _price_snapshot(db, symbol)
    research_ids = research_symbol_ids(db, symbol)
    news_lines = _recent_news_lines(db, research_ids)
    disclosure_lines = _recent_disclosure_lines(db, research_ids)

    if prev_close is None:
        price_section = "최근 거래일 종가 데이터가 없습니다."
    else:
        change_text = (
            f"{change_pct:+.2f}%" if change_pct is not None else "전일 대비 정보 없음"
        )
        price_section = (
            f"직전 거래일({prev_trade_date}) 종가 {prev_close:,.0f}원, "
            f"전일 대비 {change_text}"
        )

    prompt = (
        f"종목: {symbol.name}({symbol.code})\n"
        f"시장: {symbol.market}\n\n"
        f"[직전 거래일 시장]\n{price_section}\n\n"
        f"[최근 뉴스]\n{chr(10).join(news_lines) if news_lines else '(최근 뉴스 없음)'}\n\n"
        f"[최근 공시]\n"
        f"{chr(10).join(disclosure_lines) if disclosure_lines else '(최근 공시 없음)'}\n\n"
        "위 정보를 바탕으로 오늘 아침 투자자를 위한 데일리 리포트를 작성하세요."
    )
    return _SymbolContext(prompt, prev_trade_date, prev_close, change_pct)


# --- response parsing ----------------------------------------------------


def _match_recommendation(value: str) -> str:
    text = value.lower()
    if "buy" in text or "매수" in text:
        return "buy"
    if "sell" in text or "매도" in text:
        return "sell"
    return "hold"


def parse_report_response(raw: str | None) -> tuple[str, str, str | None]:
    """Parse a model reply into ``(recommendation, summary, rationale)``.

    Never raises. A missing/empty reply or a reply with no ``OPINION:`` line
    falls back to a ``hold`` opinion; if the model ignores the line format the
    whole reply becomes the summary.
    """
    if not raw or not raw.strip():
        return "hold", "", None
    recommendation = "hold"
    rationale: str | None = None
    summary_lines: list[str] = []
    for line in raw.strip().splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("OPINION:"):
            recommendation = _match_recommendation(stripped.split(":", 1)[1])
            continue
        if upper.startswith("RATIONALE:"):
            rationale = stripped.split(":", 1)[1].strip() or None
            continue
        if stripped:
            summary_lines.append(stripped)
    summary = "\n".join(summary_lines).strip() or raw.strip()
    return recommendation, summary, rationale


# --- orchestration -------------------------------------------------------


def kst_today() -> str:
    """Today's date on the KST calendar as an ISO ``YYYY-MM-DD`` string."""
    return datetime.now(_KST).date().isoformat()


def should_generate_today(db: Session, *, now_kst: datetime) -> bool:
    """True when a weekday report batch is due and none exists yet today.

    Weekends are skipped; public holidays are not (by design — the report then
    falls back to the last trading day's cached prices). ``now_kst`` is injected
    so the guard is deterministic in tests.
    """
    if now_kst.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    if now_kst.time() < _REPORT_AFTER:
        return False
    today = now_kst.date().isoformat()
    already = db.execute(
        select(DailyReport.id).where(DailyReport.report_date == today).limit(1)
    ).scalar_one_or_none()
    return already is None


def _store_report(
    db: Session,
    *,
    existing: DailyReport | None,
    symbol: Symbol,
    report_date: str,
    recommendation: str,
    summary: str,
    rationale: str | None,
    ctx: _SymbolContext,
    model_name: str,
) -> None:
    target = existing or DailyReport(symbol_id=symbol.id, report_date=report_date)
    target.recommendation = recommendation
    target.summary = summary
    target.rationale = rationale
    target.prev_trade_date = ctx.prev_trade_date
    target.prev_close = ctx.prev_close
    target.change_pct = ctx.change_pct
    target.model_name = model_name
    if existing is None:
        db.add(target)


def generate_daily_reports(
    db: Session,
    *,
    report_date: str,
    generator: ReportGenerator | None = None,
    symbol_ids: list[int] | None = None,
    overwrite: bool = False,
) -> tuple[int, int, list[str]]:
    """Generate one report per symbol for ``report_date``.

    Returns ``(generated, skipped, failures)``. A symbol already reported for
    ``report_date`` is skipped unless ``overwrite``; a generator that returns
    ``None`` (CLI down, timeout) skips that symbol; any per-symbol exception is
    isolated so the batch keeps going. Each symbol is committed on its own so a
    long run is durable mid-flight.
    """
    active = generator or get_report_generator()
    query = select(Symbol)
    if symbol_ids is not None:
        if not symbol_ids:
            return 0, 0, []
        query = query.where(Symbol.id.in_(symbol_ids))
    symbols = list(
        db.execute(query.order_by(Symbol.market.asc(), Symbol.code.asc())).scalars()
    )

    generated = 0
    skipped = 0
    failures: list[str] = []
    for symbol in symbols:
        existing = db.execute(
            select(DailyReport)
            .where(DailyReport.symbol_id == symbol.id)
            .where(DailyReport.report_date == report_date)
        ).scalar_one_or_none()
        if existing is not None and not overwrite:
            skipped += 1
            continue
        try:
            ctx = _build_symbol_context(db, symbol)
            raw = active.generate(ctx.prompt)
            if raw is None:
                skipped += 1
                continue
            recommendation, summary, rationale = parse_report_response(raw)
            _store_report(
                db,
                existing=existing,
                symbol=symbol,
                report_date=report_date,
                recommendation=recommendation,
                summary=summary,
                rationale=rationale,
                ctx=ctx,
                model_name=active.model_name,
            )
            db.commit()
            generated += 1
        except Exception as exc:  # broad: one symbol must not abort the batch
            db.rollback()
            logger.warning(
                "daily report failed for %s(%s): %s",
                symbol.name,
                symbol.code,
                exc,
                exc_info=True,
            )
            failures.append(f"{symbol.name}({symbol.code}): {exc}")
    return generated, skipped, failures
