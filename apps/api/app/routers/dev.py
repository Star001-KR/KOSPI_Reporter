from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from app.database import get_db
from app.models import AnalysisResult, Disclosure, Holding, NewsItem, Symbol
from app.schemas import MockActivityResult
from app.services.mock_data import ensure_mock_activity

router = APIRouter(prefix="/api/dev", tags=["dev"])

DEMO_SYMBOLS = [
    {
        "symbol": Symbol(
            market="KOSPI",
            code="005930",
            name="삼성전자",
            memo="핵심 보유 후보",
        ),
        "holding": Holding(
            quantity=12,
            average_cost=72000,
            market_value=900000,
            portfolio_weight=45,
        ),
    },
    {
        "symbol": Symbol(
            market="KOSPI",
            code="000660",
            name="SK하이닉스",
            memo="반도체 사이클 확인",
        ),
        "holding": Holding(
            quantity=4,
            average_cost=185000,
            market_value=820000,
            portfolio_weight=41,
        ),
    },
    {
        "symbol": Symbol(
            market="KOSPI",
            code="035420",
            name="NAVER",
            memo="국내 플랫폼 대표 종목",
        ),
        "holding": Holding(
            quantity=1,
            average_cost=190000,
            market_value=280000,
            portfolio_weight=14,
        ),
    },
]


def _cleanup_legacy_kr_activity(db: Session, symbol_id: int, code: str) -> None:
    news_ids = list(
        db.execute(
            select(NewsItem.id)
            .where(NewsItem.symbol_id == symbol_id)
            .where(NewsItem.canonical_url.like(f"mock://news/KR/{code}/%"))
        ).scalars()
    )
    disclosure_ids = list(
        db.execute(
            select(Disclosure.id)
            .where(Disclosure.symbol_id == symbol_id)
            .where(Disclosure.rcept_no.like(f"MOCKKR{code}%"))
        ).scalars()
    )

    if news_ids:
        db.execute(
            delete(AnalysisResult)
            .where(AnalysisResult.target_type == "news")
            .where(AnalysisResult.target_id.in_(news_ids))
        )
        db.execute(delete(NewsItem).where(NewsItem.id.in_(news_ids)))

    if disclosure_ids:
        db.execute(
            delete(AnalysisResult)
            .where(AnalysisResult.target_type == "disclosure")
            .where(AnalysisResult.target_id.in_(disclosure_ids))
        )
        db.execute(delete(Disclosure).where(Disclosure.id.in_(disclosure_ids)))


@router.post("/seed", response_model=list[MockActivityResult])
def seed_dev_data(db: Session = Depends(get_db)) -> list[MockActivityResult]:
    legacy_nvda = db.execute(
        select(Symbol)
        .where(Symbol.market == "US")
        .where(Symbol.code == "NVDA")
        .where(Symbol.name == "NVIDIA")
        .where(Symbol.memo == "해외 확장용 샘플")
    ).scalar_one_or_none()
    if legacy_nvda is not None:
        db.delete(legacy_nvda)
        db.flush()

    for code in ("005930", "000660", "035420"):
        legacy_kr = db.execute(
            select(Symbol).where(Symbol.market == "KR").where(Symbol.code == code)
        ).scalar_one_or_none()
        if legacy_kr is not None:
            _cleanup_legacy_kr_activity(db, legacy_kr.id, code)
            existing_kospi = db.execute(
                select(Symbol).where(Symbol.market == "KOSPI").where(Symbol.code == code)
            ).scalar_one_or_none()
            if existing_kospi is None:
                legacy_kr.market = "KOSPI"
            else:
                db.delete(legacy_kr)
            db.flush()

    symbols: list[Symbol] = []
    for demo in DEMO_SYMBOLS:
        template_symbol = demo["symbol"]
        template_holding = demo["holding"]
        symbol = db.execute(
            select(Symbol)
            .where(Symbol.market == template_symbol.market)
            .where(Symbol.code == template_symbol.code)
        ).scalar_one_or_none()

        if symbol is None:
            symbol = Symbol(
                market=template_symbol.market,
                code=template_symbol.code,
                name=template_symbol.name,
                memo=template_symbol.memo,
            )
            db.add(symbol)
            db.flush()

        if symbol.holding is None:
            db.add(
                Holding(
                    symbol_id=symbol.id,
                    quantity=template_holding.quantity,
                    average_cost=template_holding.average_cost,
                    market_value=template_holding.market_value,
                    portfolio_weight=template_holding.portfolio_weight,
                )
            )

        _cleanup_legacy_kr_activity(db, symbol.id, template_symbol.code)
        symbols.append(symbol)

    results: list[MockActivityResult] = []
    for symbol in symbols:
        news_inserted, disclosures_inserted = ensure_mock_activity(db, symbol)
        results.append(
            MockActivityResult(
                symbol_id=symbol.id,
                news_inserted=news_inserted,
                disclosures_inserted=disclosures_inserted,
            )
        )
    db.commit()
    return results
