from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_db
from app.models import AnalysisResult, Disclosure, Holding, NewsItem, Symbol
from app.schemas import (
    AnalysisResultRead,
    AnalyzedDisclosure,
    AnalyzedNewsItem,
    DisclosureRead,
    HoldingInput,
    MockActivityResult,
    NewsItemRead,
    SymbolCreate,
    SymbolDetail,
    SymbolLookupRead,
    SymbolPatch,
    SymbolRead,
)
from app.services.mock_data import ensure_mock_activity
from app.services.symbol_catalog import ListedSymbol, lookup_symbols, resolve_single_symbol

router = APIRouter(prefix="/api/symbols", tags=["symbols"])


def _get_symbol_or_404(db: Session, symbol_id: int) -> Symbol:
    symbol = db.execute(
        select(Symbol)
        .options(joinedload(Symbol.holding))
        .where(Symbol.id == symbol_id)
    ).scalar_one_or_none()
    if symbol is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")
    return symbol


def _apply_holding(symbol: Symbol, holding_data: HoldingInput | None, db: Session) -> None:
    if holding_data is None:
        if symbol.holding is not None:
            db.delete(symbol.holding)
            symbol.holding = None
        return

    if symbol.holding is None:
        symbol.holding = Holding()

    payload = holding_data.model_dump()
    for key, value in payload.items():
        setattr(symbol.holding, key, value)


def _commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A symbol with this market and code already exists.",
        ) from exc


def _format_matches(matches: list[ListedSymbol]) -> str:
    return ", ".join(f"{item.name}({item.market}:{item.code})" for item in matches[:5])


def _resolve_create_identity(payload: SymbolCreate) -> ListedSymbol:
    resolved, matches = resolve_single_symbol(
        market=payload.market,
        code=payload.code,
        name=payload.name,
    )
    if resolved is not None:
        return resolved

    if not payload.code and not payload.name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="종목코드나 종목명 중 하나는 입력해야 합니다.",
        )

    if matches:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "검색 결과가 여러 개입니다. 종목코드를 입력해 주세요: "
                f"{_format_matches(matches)}"
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            "종목을 찾지 못했습니다. 종목코드와 종목명을 모두 입력하면 "
            "수동 등록할 수 있습니다."
        ),
    )


def _analysis_map(
    db: Session, target_type: str, target_ids: list[int]
) -> dict[int, AnalysisResult]:
    if not target_ids:
        return {}
    rows = db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.target_type == target_type)
        .where(AnalysisResult.target_id.in_(target_ids))
        .order_by(AnalysisResult.created_at.desc())
    ).scalars()
    mapped: dict[int, AnalysisResult] = {}
    for row in rows:
        mapped.setdefault(row.target_id, row)
    return mapped


def _symbol_detail(db: Session, symbol: Symbol) -> SymbolDetail:
    news_items = list(
        db.execute(
            select(NewsItem)
            .where(NewsItem.symbol_id == symbol.id)
            .order_by(NewsItem.collected_at.desc())
            .limit(30)
        ).scalars()
    )
    disclosures = list(
        db.execute(
            select(Disclosure)
            .where(Disclosure.symbol_id == symbol.id)
            .order_by(Disclosure.collected_at.desc())
            .limit(30)
        ).scalars()
    )

    news_analysis = _analysis_map(db, "news", [item.id for item in news_items])
    disclosure_analysis = _analysis_map(
        db, "disclosure", [item.id for item in disclosures]
    )
    base = SymbolRead.model_validate(symbol).model_dump()
    return SymbolDetail(
        **base,
        news_items=[
            AnalyzedNewsItem(
                item=NewsItemRead.model_validate(item),
                analysis=(
                    AnalysisResultRead.model_validate(news_analysis[item.id])
                    if item.id in news_analysis
                    else None
                ),
            )
            for item in news_items
        ],
        disclosures=[
            AnalyzedDisclosure(
                item=DisclosureRead.model_validate(item),
                analysis=(
                    AnalysisResultRead.model_validate(disclosure_analysis[item.id])
                    if item.id in disclosure_analysis
                    else None
                ),
            )
            for item in disclosures
        ],
    )


@router.get("", response_model=list[SymbolRead])
def list_symbols(db: Session = Depends(get_db)) -> list[SymbolRead]:
    symbols = db.execute(
        select(Symbol)
        .options(joinedload(Symbol.holding))
        .order_by(Symbol.market.asc(), Symbol.code.asc())
    ).scalars()
    return [SymbolRead.model_validate(symbol) for symbol in symbols]


@router.get("/lookup", response_model=list[SymbolLookupRead])
def lookup_listed_symbols(
    q: str = Query(min_length=1),
    market: str | None = None,
    limit: int = Query(default=8, ge=1, le=20),
) -> list[SymbolLookupRead]:
    return [
        SymbolLookupRead(market=item.market, code=item.code, name=item.name)
        for item in lookup_symbols(q, market=market, limit=limit)
    ]


@router.post("", response_model=SymbolRead, status_code=status.HTTP_201_CREATED)
def create_symbol(payload: SymbolCreate, db: Session = Depends(get_db)) -> SymbolRead:
    identity = _resolve_create_identity(payload)
    symbol = Symbol(
        market=identity.market,
        code=identity.code,
        name=identity.name,
        memo=payload.memo,
    )
    db.add(symbol)
    if payload.holding is not None:
        _apply_holding(symbol, payload.holding, db)
    _commit_or_conflict(db)
    return SymbolRead.model_validate(_get_symbol_or_404(db, symbol.id))


@router.get("/{symbol_id}", response_model=SymbolDetail)
def get_symbol(symbol_id: int, db: Session = Depends(get_db)) -> SymbolDetail:
    return _symbol_detail(db, _get_symbol_or_404(db, symbol_id))


@router.patch("/{symbol_id}", response_model=SymbolRead)
def update_symbol(
    symbol_id: int, payload: SymbolPatch, db: Session = Depends(get_db)
) -> SymbolRead:
    symbol = _get_symbol_or_404(db, symbol_id)
    data = payload.model_dump(exclude_unset=True)
    holding_was_set = "holding" in data
    holding_data = data.pop("holding", None)

    for key, value in data.items():
        setattr(symbol, key, value)
    if holding_was_set:
        _apply_holding(
            symbol,
            HoldingInput.model_validate(holding_data) if holding_data is not None else None,
            db,
        )

    _commit_or_conflict(db)
    return SymbolRead.model_validate(_get_symbol_or_404(db, symbol_id))


@router.delete("/{symbol_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_symbol(symbol_id: int, db: Session = Depends(get_db)) -> None:
    symbol = _get_symbol_or_404(db, symbol_id)
    db.delete(symbol)
    db.commit()


@router.post("/{symbol_id}/mock-activity", response_model=MockActivityResult)
def create_mock_activity(
    symbol_id: int, db: Session = Depends(get_db)
) -> MockActivityResult:
    symbol = _get_symbol_or_404(db, symbol_id)
    news_inserted, disclosures_inserted = ensure_mock_activity(db, symbol)
    db.commit()
    return MockActivityResult(
        symbol_id=symbol_id,
        news_inserted=news_inserted,
        disclosures_inserted=disclosures_inserted,
    )
