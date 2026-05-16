"""Daily price collector — real KR market data.

Fetches daily close prices for a symbol from Naver Finance's ``siseJson``
endpoint and caches them in the ``daily_prices`` table. Like the news
collector, this keeps no dependency beyond the standard library (``urllib``).

The endpoint returns rows of ``[date, open, high, low, close, volume, ...]``
as a single-quoted pseudo-JSON array whose first row is a Korean header; only
the date and close price are kept.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyPrice, Symbol, utcnow

_NAVER_SISE_URL = "https://api.finance.naver.com/siseJson.naver"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_REQUEST_TIMEOUT_SECONDS = 12.0
_KST = timezone(timedelta(hours=9))

# Number of recent daily closes shown on the dashboard sparkline.
DEFAULT_PRICE_DAYS = 30
# Re-fetch a symbol's prices at most this often; cached rows are served between.
_PRICE_TTL = timedelta(hours=6)


class PriceFetchError(RuntimeError):
    """Raised when daily prices cannot be fetched from the data source."""


@dataclass(frozen=True)
class PriceBar:
    """A single trading day's close, with an ISO ``YYYY-MM-DD`` date."""

    trade_date: str
    close: float


def parse_price_rows(raw_text: str) -> list[PriceBar]:
    """Parse Naver's ``siseJson`` payload into date-sorted :class:`PriceBar` rows.

    The payload is a single-quoted pseudo-JSON array whose first row is a
    Korean header; the header and any malformed rows are skipped.
    """
    text = raw_text.strip()
    if not text:
        return []
    try:
        rows = json.loads(text.replace("'", '"'))
    except ValueError as exc:
        raise PriceFetchError("시세 응답을 해석할 수 없습니다.") from exc
    if not isinstance(rows, list):
        return []
    bars: list[PriceBar] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 5:
            continue
        raw_date = str(row[0]).strip()
        if len(raw_date) != 8 or not raw_date.isdigit():
            continue  # header row ('날짜') and anything malformed
        try:
            close = float(row[4])
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        trade_date = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        bars.append(PriceBar(trade_date=trade_date, close=close))
    bars.sort(key=lambda bar: bar.trade_date)
    return bars


def fetch_daily_closes(code: str, *, days: int = DEFAULT_PRICE_DAYS) -> list[PriceBar]:
    """Fetch recent daily closes for ``code`` from Naver Finance."""
    today = datetime.now(_KST).date()
    # Pull a wide enough calendar window to cover ``days`` trading days.
    start = today - timedelta(days=days * 2 + 15)
    params = {
        "symbol": code,
        "requestType": "1",
        "startTime": start.strftime("%Y%m%d"),
        "endTime": today.strftime("%Y%m%d"),
        "timeframe": "day",
    }
    request = Request(
        f"{_NAVER_SISE_URL}?{urlencode(params)}",
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except HTTPError as exc:
        raise PriceFetchError(f"네이버 시세 API 오류 (HTTP {exc.code})") from exc
    except OSError as exc:
        raise PriceFetchError(f"네이버 시세 API 요청에 실패했습니다: {exc}") from exc
    return parse_price_rows(payload.decode("utf-8", errors="replace"))


def store_daily_prices(db: Session, symbol_id: int, bars: list[PriceBar]) -> int:
    """Upsert daily closes for a symbol, keyed by ``trade_date``.

    Returns the number of newly inserted rows; an existing day is updated so a
    re-fetch keeps the latest close. Rows are flushed but not committed.
    """
    existing = {
        row.trade_date: row
        for row in db.execute(
            select(DailyPrice).where(DailyPrice.symbol_id == symbol_id)
        ).scalars()
    }
    now = utcnow()
    inserted = 0
    for bar in bars:
        row = existing.get(bar.trade_date)
        if row is None:
            db.add(
                DailyPrice(
                    symbol_id=symbol_id,
                    trade_date=bar.trade_date,
                    close=bar.close,
                    collected_at=now,
                )
            )
            inserted += 1
        else:
            row.close = bar.close
            row.collected_at = now
    db.flush()
    return inserted


def _stored_prices(db: Session, symbol_id: int) -> list[DailyPrice]:
    return list(
        db.execute(
            select(DailyPrice)
            .where(DailyPrice.symbol_id == symbol_id)
            .order_by(DailyPrice.trade_date.asc())
        ).scalars()
    )


def _is_fresh(prices: list[DailyPrice]) -> bool:
    """True when cached prices are recent enough to skip a refetch."""
    if not prices:
        return False
    latest = max(price.collected_at for price in prices)
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return (utcnow() - latest) < _PRICE_TTL


def get_symbol_prices(
    db: Session,
    symbol: Symbol,
    *,
    days: int = DEFAULT_PRICE_DAYS,
    fetcher: Callable[..., list[PriceBar]] | None = None,
) -> list[DailyPrice]:
    """Return a symbol's recent daily closes, refreshing the cache when stale.

    A fetch failure is swallowed so any previously cached rows are still
    served; only a cold cache with no data returns an empty list.
    """
    stored = _stored_prices(db, symbol.id)
    if not _is_fresh(stored):
        active = fetcher or fetch_daily_closes
        try:
            bars = active(symbol.code, days=days)
        except PriceFetchError:
            bars = []
        if bars:
            store_daily_prices(db, symbol.id, bars)
            db.commit()
            stored = _stored_prices(db, symbol.id)
    return stored[-days:]
