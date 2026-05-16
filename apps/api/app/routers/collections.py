from __future__ import annotations

from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from app.database import get_db
from app.schemas import CollectionRunRead
from app.services.opendart import run_corp_code_import

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
