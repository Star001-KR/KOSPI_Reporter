from __future__ import annotations

from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from app.database import get_db
from app.schemas import CollectionRunRead
from app.services.analyzer import analyze_pending
from app.services.naver_news import collect_news
from app.services.opendart import collect_disclosures, run_corp_code_import

router = APIRouter(prefix="/api/collections", tags=["collections"])


@router.post("/corp-codes/import", response_model=CollectionRunRead)
def import_corp_codes(db: Session = Depends(get_db)) -> CollectionRunRead:
    """Download the OpenDART corp code archive and upsert ``dart_corp_codes``.

    The response is always a :class:`CollectionRunRead`. A missing API key or a
    download failure is reported as a run with ``status = "failed"`` and an
    explanatory ``message`` rather than as an HTTP error.
    """
    run = run_corp_code_import(db)
    return CollectionRunRead.model_validate(run)


@router.post("/disclosures", response_model=CollectionRunRead)
def collect_disclosure_run(db: Session = Depends(get_db)) -> CollectionRunRead:
    """Collect recent OpenDART disclosures for every registered symbol.

    As with the corp code import, a missing API key or a failed collection is
    reported as a run with ``status = "failed"`` rather than an HTTP error.
    """
    run = collect_disclosures(db)
    return CollectionRunRead.model_validate(run)


@router.post("/news", response_model=CollectionRunRead)
def collect_news_run(db: Session = Depends(get_db)) -> CollectionRunRead:
    """Collect recent Naver news for every registered symbol.

    A missing API key or a failed collection is reported as a run with
    ``status = "failed"`` rather than an HTTP error.
    """
    run = collect_news(db)
    return CollectionRunRead.model_validate(run)


@router.post("/analyze", response_model=CollectionRunRead)
def analyze_run(db: Session = Depends(get_db)) -> CollectionRunRead:
    """Analyze collected news and disclosures that have no analysis result yet.

    Uses the keyless rule-based analyzer, so it runs without any external key.
    """
    run = analyze_pending(db)
    return CollectionRunRead.model_validate(run)
