"""Shared helpers for finishing a :class:`CollectionRun`.

The news (``naver_news``) and disclosure/corp-code (``opendart``) collectors
close out a run the same two ways: mark it failed on error, or build a
per-symbol partial-success summary message. Keeping that logic here avoids the
two collectors drifting apart.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import CollectionRun, utcnow


def mark_run_failed(db: Session, run: CollectionRun, message: str) -> None:
    """Record ``run`` as failed with ``message`` and commit."""
    run.status = "failed"
    run.finished_at = utcnow()
    run.message = message
    db.commit()


def run_summary(
    label: str, total: int, processed: int, inserted: int, failures: list[str]
) -> str:
    """Build a per-symbol collection summary message."""
    summary = f"{label}: 종목 {processed}/{total} 처리, 신규 {inserted}건."
    if failures:
        summary += f" 실패 {len(failures)}건 — " + "; ".join(failures)
    return summary
