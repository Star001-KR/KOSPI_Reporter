from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from fastapi import APIRouter, Depends, Query

from app.database import get_db
from app.models import DailyReport
from app.routers.auth import current_user
from app.schemas import (
    DailyReportItem,
    DailyReportList,
    DailyReportRunRequest,
    DailyReportRunResult,
)
from app.services.daily_report import generate_daily_reports, kst_today

router = APIRouter(prefix="/api/daily-reports", tags=["daily-reports"])


def _to_item(report: DailyReport) -> DailyReportItem:
    """Flatten a DailyReport + its symbol into the API item shape."""
    return DailyReportItem(
        id=report.id,
        symbol_id=report.symbol_id,
        report_date=report.report_date,
        recommendation=report.recommendation,
        summary=report.summary,
        rationale=report.rationale,
        prev_trade_date=report.prev_trade_date,
        prev_close=float(report.prev_close) if report.prev_close is not None else None,
        change_pct=float(report.change_pct) if report.change_pct is not None else None,
        model_name=report.model_name,
        created_at=report.created_at,
        symbol_name=report.symbol.name,
        symbol_code=report.symbol.code,
        symbol_market=report.symbol.market,
    )


@router.get("", response_model=DailyReportList)
def list_daily_reports(
    date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> DailyReportList:
    """Every symbol's report for a date — the latest published date if omitted.

    Read path is unauthenticated like the other GET endpoints; a date with no
    reports yields an empty list.
    """
    target_date = date or db.execute(
        select(func.max(DailyReport.report_date))
    ).scalar_one_or_none()
    if target_date is None:
        return DailyReportList(report_date=None, items=[])

    reports = list(
        db.execute(
            select(DailyReport)
            .options(joinedload(DailyReport.symbol))
            .where(DailyReport.report_date == target_date)
        ).scalars()
    )
    reports.sort(key=lambda report: (report.symbol.market, report.symbol.code))
    return DailyReportList(
        report_date=target_date,
        items=[_to_item(report) for report in reports],
    )


@router.post(
    "/run",
    response_model=DailyReportRunResult,
    dependencies=[Depends(current_user)],
)
def run_daily_reports(
    payload: DailyReportRunRequest | None = None,
    db: Session = Depends(get_db),
) -> DailyReportRunResult:
    """Generate today's reports on demand (manual/dev; no weekday/time guard).

    Idempotent: a symbol already reported today is skipped unless
    ``overwrite`` is set. The scheduler runs the same service automatically on
    weekday mornings.
    """
    request = payload or DailyReportRunRequest()
    report_date = kst_today()
    generated, skipped, failures = generate_daily_reports(
        db,
        report_date=report_date,
        symbol_ids=request.symbol_ids,
        overwrite=request.overwrite,
    )
    return DailyReportRunResult(
        report_date=report_date,
        generated=generated,
        skipped=skipped,
        failures=failures,
    )
