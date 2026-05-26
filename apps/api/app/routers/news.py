"""News read endpoints, currently scoped to AI-summary generation.

The eager path runs at collection time (see
:func:`app.services.collections.run_collection`). This router covers the lazy
path: when a user opens an article that was not summarized eagerly — older
items, or items collected while the API key was missing — the client calls
``POST /api/news/{id}/ai-summary`` to fill it in on demand and cache the
result for the next read.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import NewsItem
from app.schemas import NewsItemRead
from app.services.news_summary import ensure_ai_summary

router = APIRouter(prefix="/api/news", tags=["news"])


@router.post("/{news_id}/ai-summary", response_model=NewsItemRead)
def generate_ai_summary(
    news_id: int, db: Session = Depends(get_db)
) -> NewsItemRead:
    """Return the news row, generating its AI summary if not yet cached.

    A cached summary is returned unchanged so repeat reads cost nothing. When
    generation fails (no API key, network error) the row is still returned
    without an AI summary — the client renders the rule-based fallback.
    """
    news = db.get(NewsItem, news_id)
    if news is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="News item not found"
        )
    ensure_ai_summary(db, news)
    return NewsItemRead.model_validate(news)
