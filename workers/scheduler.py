"""Periodic collection worker (MVP-07).

Runs the unified collection pipeline on an interval, reusing the same service
logic the API uses (``app.services.collections``). No API server is required.

Run with ``npm run worker``. The interval is taken from the
``COLLECTION_INTERVAL_SECONDS`` environment variable (default 600 seconds).
"""

from __future__ import annotations

import logging
import os
import time

from app.database import SessionLocal, init_db
from app.services.collections import run_scheduled_collection

logger = logging.getLogger("kospi.scheduler")

_DEFAULT_INTERVAL_SECONDS = 600


def _interval_seconds() -> int:
    raw = os.getenv("COLLECTION_INTERVAL_SECONDS", str(_DEFAULT_INTERVAL_SECONDS))
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_INTERVAL_SECONDS
    return value if value > 0 else _DEFAULT_INTERVAL_SECONDS


def run_once() -> None:
    """Run a single scheduled collection tick.

    Any failure is logged without raising so the worker loop keeps running;
    collection-level failures are also recorded in ``collection_runs``.
    """
    db = SessionLocal()
    try:
        run = run_scheduled_collection(db)
        if run is None:
            logger.info("이미 진행 중인 수집이 있어 이번 주기는 건너뜁니다.")
        else:
            logger.info(
                "수집 실행 #%s 완료: status=%s, %s", run.id, run.status, run.message
            )
    except Exception:  # broad: a tick failure must not kill the worker loop
        logger.exception("스케줄 수집 중 오류가 발생했습니다.")
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    init_db()
    interval = _interval_seconds()
    logger.info("수집 스케줄러 시작 (주기 %s초)", interval)
    while True:
        run_once()
        time.sleep(interval)


if __name__ == "__main__":
    main()
