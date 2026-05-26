"""News AI-summary persistence layer.

Bridges :mod:`app.services.ai_summarizer` and the ``news_items`` table:

* :func:`summarize_recent_for_symbols` — eager batch run, used after a
  collection. Picks the latest ``N`` items per symbol that still have no
  ``ai_summary`` and fills them in.
* :func:`ensure_ai_summary` — lazy single-item run, used by the on-demand API
  when a user opens a reading pane for an article that was never eagerly
  summarized.

Both paths share :func:`_generate_and_store` so eager and lazy summaries are
indistinguishable in the database.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NewsItem, Symbol, utcnow
from app.services.ai_summarizer import Summarizer, get_summarizer

logger = logging.getLogger(__name__)


def _generate_and_store(
    db: Session, news: NewsItem, summarizer: Summarizer
) -> bool:
    """Run the summarizer for one item and persist on success.

    Returns ``True`` when a summary was generated and written. The caller is
    responsible for committing — leaving the commit to the caller lets a batch
    flush all rows in one transaction.
    """
    symbol = db.get(Symbol, news.symbol_id)
    summary = summarizer.summarize(
        symbol_name=symbol.name if symbol else "",
        title=news.title,
        body=news.summary,
    )
    if not summary:
        return False
    news.ai_summary = summary
    news.ai_summary_model = summarizer.model_name
    news.ai_summary_at = utcnow()
    return True


def summarize_recent_for_symbols(
    db: Session,
    symbol_ids: list[int],
    *,
    per_symbol: int,
    summarizer: Summarizer | None = None,
) -> int:
    """Eagerly summarize the latest ``per_symbol`` items per symbol.

    Only items without an ``ai_summary`` are touched, so re-running after a
    collection that brought in five new articles only spends tokens on those
    five. Returns the number of items newly summarized.
    """
    if not symbol_ids or per_symbol <= 0:
        return 0
    active = summarizer or get_summarizer()

    written = 0
    for symbol_id in symbol_ids:
        candidates = list(
            db.execute(
                select(NewsItem)
                .where(NewsItem.symbol_id == symbol_id)
                .where(NewsItem.ai_summary.is_(None))
                .order_by(NewsItem.collected_at.desc())
                .limit(per_symbol)
            ).scalars()
        )
        for news in candidates:
            if _generate_and_store(db, news, active):
                written += 1
    if written:
        db.commit()
    return written


def ensure_ai_summary(
    db: Session,
    news: NewsItem,
    *,
    summarizer: Summarizer | None = None,
) -> NewsItem:
    """Make sure ``news`` has an AI summary, generating it on demand.

    Returns the same ``news`` row — already-summarized items are returned
    untouched, freshly summarized items have the new fields populated and
    committed. Failure to generate (no API key, network error, etc.) leaves
    the row unchanged and lets the caller fall back to the rule-based summary.
    """
    if news.ai_summary:
        return news
    active = summarizer or get_summarizer()
    if _generate_and_store(db, news, active):
        db.commit()
    return news
