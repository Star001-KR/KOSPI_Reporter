from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from fastapi import APIRouter, Depends

from app.database import get_db
from app.models import AnalysisResult, Disclosure, NewsItem, Symbol
from app.routers.symbols import research_symbol_id
from app.schemas import BriefItem, BriefPosition, PortfolioBrief, SymbolRead

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _latest_analysis(
    db: Session, target_type: str, target_id: int
) -> AnalysisResult | None:
    return db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.target_type == target_type)
        .where(AnalysisResult.target_id == target_id)
        .order_by(AnalysisResult.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


@router.get("/brief", response_model=PortfolioBrief)
def get_portfolio_brief(db: Session = Depends(get_db)) -> PortfolioBrief:
    symbols = list(
        db.execute(
            select(Symbol)
            .options(joinedload(Symbol.holding))
            .order_by(Symbol.market.asc(), Symbol.code.asc())
        ).scalars()
    )

    total_market_value = sum(
        float(symbol.holding.market_value or 0)
        for symbol in symbols
        if symbol.holding is not None
    )
    positions: list[BriefPosition] = []
    latest_collected_at = None

    for symbol in symbols:
        research_id = research_symbol_id(db, symbol)
        news_count = db.execute(
            select(func.count()).select_from(NewsItem).where(NewsItem.symbol_id == research_id)
        ).scalar_one()
        disclosure_count = db.execute(
            select(func.count())
            .select_from(Disclosure)
            .where(Disclosure.symbol_id == research_id)
        ).scalar_one()
        latest_news_at = db.execute(
            select(func.max(NewsItem.collected_at)).where(NewsItem.symbol_id == research_id)
        ).scalar_one()
        latest_disclosure_at = db.execute(
            select(func.max(Disclosure.collected_at)).where(Disclosure.symbol_id == research_id)
        ).scalar_one()
        symbol_latest = max(
            [value for value in [latest_news_at, latest_disclosure_at] if value is not None],
            default=None,
        )
        if symbol_latest is not None:
            latest_collected_at = max(
                [value for value in [latest_collected_at, symbol_latest] if value is not None]
            )
        positions.append(
            BriefPosition(
                symbol=SymbolRead.model_validate(symbol),
                news_count=news_count,
                disclosure_count=disclosure_count,
                latest_collected_at=symbol_latest,
            )
        )

    news_items = list(
        db.execute(
            select(NewsItem, Symbol)
            .join(Symbol, Symbol.id == NewsItem.symbol_id)
            .order_by(NewsItem.collected_at.desc())
            .limit(8)
        ).all()
    )
    disclosure_items = list(
        db.execute(
            select(Disclosure, Symbol)
            .join(Symbol, Symbol.id == Disclosure.symbol_id)
            .order_by(Disclosure.collected_at.desc())
            .limit(8)
        ).all()
    )

    latest_items: list[BriefItem] = []
    for item, symbol in news_items:
        analysis = _latest_analysis(db, "news", item.id)
        latest_items.append(
            BriefItem(
                kind="news",
                symbol_id=symbol.id,
                symbol_name=symbol.name,
                title=item.title,
                source=item.source,
                original_url=item.original_url,
                occurred_at=item.published_at or item.collected_at,
                sentiment=analysis.sentiment if analysis else None,
                importance=analysis.importance if analysis else None,
            )
        )
    for item, symbol in disclosure_items:
        analysis = _latest_analysis(db, "disclosure", item.id)
        latest_items.append(
            BriefItem(
                kind="disclosure",
                symbol_id=symbol.id,
                symbol_name=symbol.name,
                title=item.report_name,
                source="DART",
                original_url=item.original_url,
                occurred_at=item.submitted_at or item.collected_at,
                sentiment=analysis.sentiment if analysis else None,
                importance=analysis.importance if analysis else None,
            )
        )

    latest_items.sort(
        key=lambda item: item.occurred_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    return PortfolioBrief(
        total_symbols=len(symbols),
        total_market_value=total_market_value,
        latest_collected_at=latest_collected_at,
        positions=positions,
        latest_items=latest_items[:10],
    )
