from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_db
from app.models import CollectionRun
from app.routers.auth import current_user
from app.schemas import CollectionRunRead, CollectionRunRequest
from app.services.analyzer import analyze_pending
from app.services.collections import (
    CollectionInProgressError,
    CollectionOptions,
    run_collection,
)
from app.services.naver_news import collect_news
from app.services.opendart import collect_disclosures, run_corp_code_import

router = APIRouter(
    prefix="/api/collections",
    tags=["collections"],
    dependencies=[Depends(current_user)],
)


@router.post(
    "/run",
    response_model=CollectionRunRead,
)
def trigger_collection_run(
    payload: CollectionRunRequest | None = None,
    db: Session = Depends(get_db),
) -> CollectionRunRead:
    """Run corp code import, disclosure/news collection, and analysis as one run.

    The request body is optional; an empty body collects disclosures and news
    for every registered symbol and analyzes the result. A missing API key or
    a failed step is reported as a run with ``status = "failed"`` rather than
    an HTTP error. A collection already in progress is rejected with HTTP 409.
    """
    request = payload or CollectionRunRequest()
    options = CollectionOptions(
        symbol_ids=request.symbol_ids,
        import_corp_codes=request.import_corp_codes,
        include_disclosures=request.include_disclosures,
        include_news=request.include_news,
        include_prices=request.include_prices,
        analyze=request.analyze,
    )
    try:
        run = run_collection(db, options)
    except CollectionInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return CollectionRunRead.model_validate(run)


@router.get("/runs", response_model=list[CollectionRunRead])
def list_collection_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[CollectionRunRead]:
    """List recent collection runs, newest first."""
    runs = db.execute(
        select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(limit)
    ).scalars()
    return [CollectionRunRead.model_validate(run) for run in runs]


@router.get("/runs/{run_id}", response_model=CollectionRunRead)
def get_collection_run(
    run_id: int, db: Session = Depends(get_db)
) -> CollectionRunRead:
    """Return a single collection run by id."""
    run = db.get(CollectionRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collection run not found"
        )
    return CollectionRunRead.model_validate(run)


@router.post(
    "/corp-codes/import",
    response_model=CollectionRunRead,
)
def import_corp_codes(db: Session = Depends(get_db)) -> CollectionRunRead:
    """Download the OpenDART corp code archive and upsert ``dart_corp_codes``.

    The response is always a :class:`CollectionRunRead`. A missing API key or a
    download failure is reported as a run with ``status = "failed"`` and an
    explanatory ``message`` rather than as an HTTP error.
    """
    return CollectionRunRead.model_validate(run_corp_code_import(db))


@router.post(
    "/disclosures",
    response_model=CollectionRunRead,
)
def collect_disclosure_run(db: Session = Depends(get_db)) -> CollectionRunRead:
    """Collect recent OpenDART disclosures for every registered symbol."""
    return CollectionRunRead.model_validate(collect_disclosures(db))


@router.post(
    "/news",
    response_model=CollectionRunRead,
)
def collect_news_run(db: Session = Depends(get_db)) -> CollectionRunRead:
    """Collect recent Naver news for every registered symbol."""
    return CollectionRunRead.model_validate(collect_news(db))


@router.post(
    "/analyze",
    response_model=CollectionRunRead,
)
def analyze_run(db: Session = Depends(get_db)) -> CollectionRunRead:
    """Analyze collected news and disclosures that have no analysis result yet."""
    return CollectionRunRead.model_validate(analyze_pending(db))
