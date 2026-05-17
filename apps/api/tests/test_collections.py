"""Tests for the unified collection run service and API (MVP-05)."""

from __future__ import annotations

from datetime import timedelta
import io
import unittest
import zipfile

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi import HTTPException

from app.database import Base
from app.models import (
    AnalysisResult,
    CollectionRun,
    DartCorpCode,
    Disclosure,
    NewsItem,
    Symbol,
    utcnow,
)
from app.routers.collections import (
    get_collection_run,
    list_collection_runs,
    trigger_collection_run,
)
from app.schemas import CollectionRunRequest
from app.services.collections import (
    CollectionInProgressError,
    CollectionOptions,
    run_collection,
    run_scheduled_collection,
)

_CORP_XML = (
    "<result><list><corp_code>00126380</corp_code>"
    "<corp_name>삼성전자</corp_name><stock_code>005930</stock_code>"
    "<modify_date>20240101</modify_date></list></result>"
).encode("utf-8")


def _corp_code_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", _CORP_XML)
    return buffer.getvalue()


SAMPLE_DISCLOSURES = [
    {
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "report_nm": "단일판매ㆍ공급계약 체결",
        "rcept_no": "20240515000123",
        "rcept_dt": "20240515",
    },
    {
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "report_nm": "분기보고서",
        "rcept_no": "20240514000456",
        "rcept_dt": "20240514",
    },
]

SAMPLE_NEWS = [
    {
        "title": "삼성전자 수주 확대",
        "originallink": "https://news.example/a",
        "link": "https://news.example/a",
        "description": "수주 확대 소식",
        "pubDate": "Mon, 13 May 2024 09:30:00 +0900",
    },
]


class _DbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, autocommit=False
        )
        self.db = self.session_factory()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _seed_symbol(
        self,
        *,
        code: str = "005930",
        name: str = "삼성전자",
        corp_code: str | None = "00126380",
    ) -> Symbol:
        symbol = Symbol(market="KOSPI", code=code, name=name)
        self.db.add(symbol)
        if corp_code is not None:
            self.db.add(
                DartCorpCode(corp_code=corp_code, stock_code=code, corp_name=name)
            )
        self.db.commit()
        return symbol


class RunCollectionTests(_DbTestCase):
    def test_full_pipeline_single_run(self) -> None:
        self._seed_symbol()
        run = run_collection(
            self.db,
            CollectionOptions(),
            opendart_api_key="k",
            naver_client_id="i",
            naver_client_secret="s",
            disclosure_fetcher=lambda *_a: SAMPLE_DISCLOSURES,
            news_fetcher=lambda _q: SAMPLE_NEWS,
        )
        self.assertEqual(run.run_type, "collection")
        self.assertEqual(run.status, "success")
        self.assertEqual(run.disclosures_inserted, 2)
        self.assertEqual(run.news_inserted, 1)
        self.assertIsNotNone(run.finished_at)

        # exactly one run row — sub-collectors do not create their own runs
        runs = self.db.execute(select(CollectionRun)).scalars().all()
        self.assertEqual(len(runs), 1)

        self.assertEqual(
            len(self.db.execute(select(Disclosure)).scalars().all()), 2
        )
        self.assertEqual(len(self.db.execute(select(NewsItem)).scalars().all()), 1)
        # every collected item analyzed (2 disclosures + 1 news)
        self.assertEqual(
            len(self.db.execute(select(AnalysisResult)).scalars().all()), 3
        )

    def test_import_corp_codes_step_feeds_disclosures(self) -> None:
        # symbol present but no corp code mapping yet
        self.db.add(Symbol(market="KOSPI", code="005930", name="삼성전자"))
        self.db.commit()
        run = run_collection(
            self.db,
            CollectionOptions(
                import_corp_codes=True, include_news=False, analyze=False
            ),
            opendart_api_key="k",
            corp_code_downloader=lambda _k: _corp_code_zip(),
            disclosure_fetcher=lambda *_a: SAMPLE_DISCLOSURES,
        )
        self.assertEqual(run.status, "success")
        # the corp code step let the disclosure step resolve corp_code
        self.assertEqual(run.disclosures_inserted, 2)
        self.assertEqual(
            len(self.db.execute(select(DartCorpCode)).scalars().all()), 1
        )

    def test_missing_keys_marks_run_failed(self) -> None:
        self._seed_symbol()
        run = run_collection(
            self.db,
            CollectionOptions(analyze=False),
            opendart_api_key="",
            naver_client_id="",
            naver_client_secret="",
        )
        self.assertEqual(run.status, "failed")
        self.assertIn("실패", run.message or "")

    def test_partial_failure_keeps_succeeded_data(self) -> None:
        self._seed_symbol()
        # no OpenDART key (disclosure step fails) but news succeeds
        run = run_collection(
            self.db,
            CollectionOptions(),
            opendart_api_key="",
            naver_client_id="i",
            naver_client_secret="s",
            news_fetcher=lambda _q: SAMPLE_NEWS,
        )
        self.assertEqual(run.status, "failed")  # a step failed
        self.assertEqual(run.news_inserted, 1)  # news still stored
        self.assertEqual(len(self.db.execute(select(NewsItem)).scalars().all()), 1)

    def test_symbol_subset(self) -> None:
        keep = self._seed_symbol(code="005930", name="삼성전자")
        self._seed_symbol(code="000660", name="SK하이닉스", corp_code="00164779")
        run = run_collection(
            self.db,
            CollectionOptions(
                symbol_ids=[keep.id], include_news=False, analyze=False
            ),
            opendart_api_key="k",
            disclosure_fetcher=lambda *_a: SAMPLE_DISCLOSURES,
        )
        self.assertEqual(run.status, "success")
        self.assertEqual(run.symbols_processed, 1)
        disclosures = self.db.execute(select(Disclosure)).scalars().all()
        self.assertTrue(all(d.symbol_id == keep.id for d in disclosures))

    def test_cross_symbol_shared_article_dedupes(self) -> None:
        self._seed_symbol(code="005930", name="삼성전자")
        self._seed_symbol(code="000660", name="SK하이닉스", corp_code="00164779")
        # both symbols' news search returns the same article
        run = run_collection(
            self.db,
            CollectionOptions(include_disclosures=False, analyze=False),
            naver_client_id="i",
            naver_client_secret="s",
            news_fetcher=lambda _q: SAMPLE_NEWS,
        )
        self.assertEqual(run.status, "success")
        self.assertEqual(run.news_inserted, 1)  # shared article stored once
        self.assertEqual(len(self.db.execute(select(NewsItem)).scalars().all()), 1)


class CollectionRunAPITests(_DbTestCase):
    def test_trigger_creates_run(self) -> None:
        self._seed_symbol()
        # analyze-only keeps the request offline (no API keys needed)
        created = trigger_collection_run(
            payload=CollectionRunRequest(
                include_disclosures=False, include_news=False, analyze=True
            ),
            db=self.db,
        )
        self.assertEqual(created.run_type, "collection")
        self.assertEqual(created.status, "success")
        self.assertIsNotNone(created.finished_at)

    def test_list_and_get_runs(self) -> None:
        self._seed_symbol()
        created = trigger_collection_run(
            payload=CollectionRunRequest(
                include_disclosures=False, include_news=False, analyze=True
            ),
            db=self.db,
        )
        listed = list_collection_runs(limit=20, db=self.db)
        self.assertTrue(any(run.id == created.id for run in listed))

        fetched = get_collection_run(created.id, db=self.db)
        self.assertEqual(fetched.id, created.id)

    def test_get_missing_run_returns_404(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            get_collection_run(999999, db=self.db)
        self.assertEqual(ctx.exception.status_code, 404)


class ScheduledCollectionTests(_DbTestCase):
    _ANALYZE_ONLY = CollectionOptions(
        include_disclosures=False, include_news=False, analyze=True
    )

    def test_skips_when_a_collection_is_in_progress(self) -> None:
        self.db.add(CollectionRun(run_type="collection", status="running"))
        self.db.commit()
        result = run_scheduled_collection(self.db, self._ANALYZE_ONLY)
        self.assertIsNone(result)

    def test_runs_when_no_collection_in_progress(self) -> None:
        result = run_scheduled_collection(self.db, self._ANALYZE_ONLY)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.run_type, "collection")

    def test_finished_run_does_not_block_next_tick(self) -> None:
        # a previous *finished* run must not be treated as in progress
        self.db.add(CollectionRun(run_type="collection", status="success"))
        self.db.commit()
        result = run_scheduled_collection(self.db, self._ANALYZE_ONLY)
        self.assertIsNotNone(result)


class CollectionConcurrencyTests(_DbTestCase):
    _OFFLINE = CollectionOptions(
        include_disclosures=False, include_news=False, analyze=False
    )

    def _running_collection(self, *, started_at=None) -> CollectionRun:
        run = CollectionRun(run_type="collection", status="running")
        if started_at is not None:
            run.started_at = started_at
        self.db.add(run)
        self.db.commit()
        return run

    def test_run_collection_rejects_a_concurrent_run(self) -> None:
        self._running_collection()
        with self.assertRaises(CollectionInProgressError):
            run_collection(self.db, self._OFFLINE)

    def test_trigger_collection_run_conflict_returns_409(self) -> None:
        self._running_collection()
        with self.assertRaises(HTTPException) as ctx:
            trigger_collection_run(
                payload=CollectionRunRequest(
                    include_disclosures=False, include_news=False, analyze=False
                ),
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_stale_running_run_is_reclaimed(self) -> None:
        stale = self._running_collection(started_at=utcnow() - timedelta(hours=2))
        # The stale run no longer blocks a fresh collection.
        run = run_collection(self.db, self._OFFLINE)
        self.assertEqual(run.status, "success")
        self.db.refresh(stale)
        self.assertEqual(stale.status, "failed")


if __name__ == "__main__":
    unittest.main()
