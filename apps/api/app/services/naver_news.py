"""Naver News Search collector (MVP-03).

Collects recent news for each registered symbol from the Naver News Search
API and stores it in the ``news_items`` table.

Naver returns article titles and descriptions with ``<b>`` highlight tags and
HTML entities; both are stripped with the pure-Python ``html.parser`` so the
collector keeps no dependency on the expat C extension.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from kospi_core import NewsDraft

from app.config import get_settings
from app.models import CollectionRun, NewsItem, Symbol, utcnow
from app.services.symbol_catalog import collection_identity

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
NEWS_RUN_TYPE = "news_collection"

_REQUEST_TIMEOUT_SECONDS = 30.0
_NEWS_DISPLAY = 20


class NaverNewsError(RuntimeError):
    """Raised when a Naver News Search request cannot be completed."""


class _TextExtractor(HTMLParser):
    """Collects plain text, dropping tags and decoding HTML entities."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    @property
    def text(self) -> str:
        return "".join(self._chunks)


def clean_naver_text(raw: str) -> str:
    """Strip ``<b>`` highlight tags and decode HTML entities from Naver text."""
    extractor = _TextExtractor()
    extractor.feed(raw)
    extractor.close()
    return " ".join(extractor.text.split())


def _parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _source_from_url(url: str) -> str | None:
    host = urlparse(url).netloc
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


def parse_news(raw_items: Iterable[dict]) -> list[NewsDraft]:
    """Convert raw Naver news rows into cleaned NewsDraft records."""
    drafts: list[NewsDraft] = []
    for raw in raw_items:
        title = clean_naver_text(str(raw.get("title", "")))
        link = str(raw.get("link", "")).strip()
        original_link = str(raw.get("originallink", "")).strip()
        canonical_url = original_link or link
        if not title or not canonical_url:
            continue
        summary = clean_naver_text(str(raw.get("description", "")))
        drafts.append(
            NewsDraft(
                title=title[:300],
                original_url=link or original_link,
                canonical_url=canonical_url,
                summary=summary or None,
                source=_source_from_url(original_link or link),
                published_at=_parse_pub_date(raw.get("pubDate")),
                raw_payload=raw,
            )
        )
    return drafts


def _naver_error_detail(exc: HTTPError) -> str:
    try:
        data = json.loads(exc.read().decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            return str(data.get("errorMessage") or data.get("errorCode") or data)
        return str(data)
    except Exception:  # diagnostics only — the error formatter must never raise
        return exc.reason or "알 수 없는 오류"


def fetch_news(
    client_id: str, client_secret: str, query: str, *, display: int = _NEWS_DISPLAY
) -> list[dict]:
    """Fetch the latest news items for a query from the Naver News Search API."""
    params = {"query": query, "display": str(display), "sort": "date"}
    request = Request(
        f"{NAVER_NEWS_URL}?{urlencode(params)}",
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        },
    )
    try:
        with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except HTTPError as exc:
        raise NaverNewsError(
            f"Naver 뉴스 API 오류 (HTTP {exc.code}): {_naver_error_detail(exc)}"
        ) from exc
    except OSError as exc:
        raise NaverNewsError(f"Naver 뉴스 API 요청에 실패했습니다: {exc}") from exc
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise NaverNewsError(
            f"Naver 응답을 JSON으로 해석할 수 없습니다: {exc}"
        ) from exc
    items = decoded.get("items", []) if isinstance(decoded, dict) else []
    return [item for item in items if isinstance(item, dict)]


def store_news(db: Session, symbol_id: int, drafts: Iterable[NewsDraft]) -> int:
    """Insert news drafts, skipping any ``canonical_url`` already stored.

    Returns the number of newly inserted rows. ``canonical_url`` is globally
    unique, so re-collecting the same articles never creates duplicate rows.
    """
    inserted = 0
    seen: set[str] = set()
    for draft in drafts:
        if draft.canonical_url in seen:
            continue
        seen.add(draft.canonical_url)
        already_stored = db.execute(
            select(NewsItem.id).where(NewsItem.canonical_url == draft.canonical_url)
        ).first()
        if already_stored is not None:
            continue
        db.add(
            NewsItem(
                symbol_id=symbol_id,
                title=draft.title,
                summary=draft.summary,
                source=draft.source,
                original_url=draft.original_url,
                canonical_url=draft.canonical_url,
                published_at=draft.published_at,
                raw_payload=draft.raw_payload,
            )
        )
        inserted += 1
    db.flush()
    return inserted


def _mark_run_failed(db: Session, run: CollectionRun, message: str) -> None:
    run.status = "failed"
    run.finished_at = utcnow()
    run.message = message
    db.commit()


def _run_summary(
    label: str, total: int, processed: int, inserted: int, failures: list[str]
) -> str:
    summary = f"{label}: 종목 {processed}/{total} 처리, 신규 {inserted}건."
    if failures:
        summary += f" 실패 {len(failures)}건 — " + "; ".join(failures)
    return summary


def _default_news_fetcher(
    client_id: str, client_secret: str
) -> Callable[[str], list[dict]]:
    def fetch(query: str) -> list[dict]:
        return fetch_news(client_id, client_secret, query)

    return fetch


def collect_news_for_symbols(
    db: Session,
    symbols: list[Symbol],
    *,
    client_id: str,
    client_secret: str,
    fetcher: Callable[[str], list[dict]] | None = None,
) -> tuple[int, int, list[str]]:
    """Collect recent news for the given symbols.

    Returns ``(processed, inserted, failures)``. Raises :class:`NaverNewsError`
    only when collection cannot start (missing keys); per-symbol problems are
    returned in ``failures``. Rows are added to the session without committing.
    """
    if not client_id or not client_secret:
        raise NaverNewsError(
            "NAVER_CLIENT_ID/NAVER_CLIENT_SECRET가 설정되지 않아 "
            "뉴스 수집을 실행할 수 없습니다."
        )
    active_fetcher = fetcher or _default_news_fetcher(client_id, client_secret)

    processed = 0
    inserted = 0
    failures: list[str] = []
    for symbol in symbols:
        try:
            # Preferred stocks have no news of their own — search the common
            # stock's name instead (삼성전자우 → 삼성전자).
            _, query = collection_identity(symbol.code, symbol.name)
            raw = active_fetcher(query)
            inserted += store_news(db, symbol.id, parse_news(raw))
            processed += 1
        except NaverNewsError as exc:
            failures.append(f"{symbol.name}({symbol.code}): {exc}")
    return processed, inserted, failures


def collect_news(
    db: Session,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    fetcher: Callable[[str], list[dict]] | None = None,
) -> CollectionRun:
    """Collect recent Naver news for every registered symbol.

    The result is recorded as a :class:`CollectionRun`. A symbol whose request
    fails is reported in ``message`` while news that did succeed is still
    stored (partial success).
    """
    if client_id is None:
        client_id = get_settings().naver_client_id
    if client_secret is None:
        client_secret = get_settings().naver_client_secret

    run = CollectionRun(run_type=NEWS_RUN_TYPE, status="running")
    db.add(run)
    db.commit()

    try:
        symbols = list(db.execute(select(Symbol)).scalars())
        processed, inserted, failures = collect_news_for_symbols(
            db,
            symbols,
            client_id=client_id or "",
            client_secret=client_secret or "",
            fetcher=fetcher,
        )
        run.symbols_processed = processed
        run.news_inserted = inserted
        run.finished_at = utcnow()
        run.status = "failed" if symbols and processed == 0 else "success"
        run.message = _run_summary(
            "뉴스 수집", len(symbols), processed, inserted, failures
        )
        db.commit()
    except NaverNewsError as exc:
        db.rollback()
        _mark_run_failed(db, run, str(exc))
    except Exception as exc:  # broad: any failure must still be recorded
        db.rollback()
        _mark_run_failed(db, run, f"뉴스 수집 중 예상치 못한 오류: {exc}")
    return run
