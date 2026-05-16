"""Unit tests for the OpenDART corp code import service (MVP-01)."""

from __future__ import annotations

import io
import unittest
import zipfile
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import CollectionRun, DartCorpCode, Disclosure, Symbol
from app.services.opendart import (
    OpenDartError,
    _disclosure_list_from_response,
    collect_disclosures,
    extract_corp_code_xml,
    parse_corp_code_xml,
    parse_disclosures,
    resolve_corp_code,
    run_corp_code_import,
    store_disclosures,
    upsert_corp_codes,
)
from app.services.symbol_catalog import ListedSymbol

SAMPLE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<result>"
    "<list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>"
    "<stock_code>005930</stock_code><modify_date>20240105</modify_date></list>"
    "<list><corp_code>00164779</corp_code><corp_name>SK하이닉스</corp_name>"
    "<stock_code>000660</stock_code><modify_date>20240220</modify_date></list>"
    "<list><corp_code>00434003</corp_code>"
    "<corp_name>비상장 샘플&amp;파트너스</corp_name>"
    "<stock_code> </stock_code><modify_date>20170630</modify_date></list>"
    "</result>"
).encode("utf-8")


def _make_zip(xml_bytes: bytes, name: str = "CORPCODE.xml") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, xml_bytes)
    return buffer.getvalue()


class CorpCodeParsingTests(unittest.TestCase):
    def test_extract_and_parse(self) -> None:
        xml_bytes = extract_corp_code_xml(_make_zip(SAMPLE_XML))
        entries = parse_corp_code_xml(xml_bytes)
        self.assertEqual(len(entries), 3)

        by_code = {entry.corp_code: entry for entry in entries}
        samsung = by_code["00126380"]
        self.assertEqual(samsung.corp_name, "삼성전자")
        self.assertEqual(samsung.stock_code, "005930")
        self.assertIsNotNone(samsung.modified_at)
        self.assertEqual(samsung.modified_at.year, 2024)  # type: ignore[union-attr]

        # blank stock_code -> None, and the &amp; entity is decoded
        unlisted = by_code["00434003"]
        self.assertIsNone(unlisted.stock_code)
        self.assertEqual(unlisted.corp_name, "비상장 샘플&파트너스")

    def test_extract_rejects_non_zip_error_body(self) -> None:
        error_body = (
            "<result><status>010</status>"
            "<message>등록되지 않은 키입니다.</message></result>"
        ).encode("utf-8")
        with self.assertRaises(OpenDartError) as ctx:
            extract_corp_code_xml(error_body)
        self.assertIn("010", str(ctx.exception))


class CorpCodeUpsertTests(unittest.TestCase):
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

    def test_upsert_is_idempotent(self) -> None:
        entries = parse_corp_code_xml(SAMPLE_XML)
        self.assertEqual(upsert_corp_codes(self.db, entries), (3, 0))
        self.db.commit()

        # re-importing identical data must not create duplicate rows
        self.assertEqual(upsert_corp_codes(self.db, entries), (0, 3))
        self.db.commit()

        rows = self.db.execute(select(DartCorpCode)).scalars().all()
        self.assertEqual(len(rows), 3)

    def test_lookup_by_stock_code(self) -> None:
        upsert_corp_codes(self.db, parse_corp_code_xml(SAMPLE_XML))
        self.db.commit()
        row = self.db.execute(
            select(DartCorpCode).where(DartCorpCode.stock_code == "005930")
        ).scalar_one()
        self.assertEqual(row.corp_code, "00126380")
        self.assertEqual(row.corp_name, "삼성전자")

    def test_run_import_success(self) -> None:
        run = run_corp_code_import(
            self.db,
            api_key="test-key",
            downloader=lambda _key: _make_zip(SAMPLE_XML),
        )
        self.assertEqual(run.status, "success")
        self.assertEqual(run.symbols_processed, 3)
        self.assertIsNotNone(run.finished_at)
        rows = self.db.execute(select(DartCorpCode)).scalars().all()
        self.assertEqual(len(rows), 3)

    def test_run_import_without_key_fails_gracefully(self) -> None:
        run = run_corp_code_import(self.db, api_key="")
        self.assertEqual(run.status, "failed")
        self.assertIn("OPENDART_API_KEY", run.message or "")
        runs = self.db.execute(select(CollectionRun)).scalars().all()
        self.assertEqual(len(runs), 1)

    def test_run_import_download_failure_recorded(self) -> None:
        def failing_downloader(_key: str) -> bytes:
            raise OpenDartError("다운로드 실패 (테스트)")

        run = run_corp_code_import(
            self.db, api_key="test-key", downloader=failing_downloader
        )
        self.assertEqual(run.status, "failed")
        self.assertIn("다운로드 실패", run.message or "")


SAMPLE_DISCLOSURES = [
    {
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "stock_code": "005930",
        "corp_cls": "Y",
        "report_nm": "주요사항보고서(자기주식취득결정)",
        "rcept_no": "20240515000123",
        "flr_nm": "삼성전자",
        "rcept_dt": "20240515",
        "rm": "",
    },
    {
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "stock_code": "005930",
        "corp_cls": "Y",
        "report_nm": "분기보고서 (2024.03)",
        "rcept_no": "20240514000456",
        "flr_nm": "삼성전자",
        "rcept_dt": "20240514",
        "rm": "",
    },
]


class DisclosureParsingTests(unittest.TestCase):
    def test_parse_disclosures(self) -> None:
        drafts = parse_disclosures(SAMPLE_DISCLOSURES)
        self.assertEqual(len(drafts), 2)

        first = drafts[0]
        self.assertEqual(first.rcept_no, "20240515000123")
        self.assertIn("자기주식취득", first.report_name)
        self.assertIn("rcpNo=20240515000123", first.original_url)
        self.assertEqual(first.corp_code, "00126380")
        self.assertIsNotNone(first.submitted_at)
        self.assertEqual(first.raw_payload, SAMPLE_DISCLOSURES[0])

    def test_parse_skips_incomplete_rows(self) -> None:
        rows = [
            {"rcept_no": "", "report_nm": "제목만 있음"},
            {"rcept_no": "20240101000001"},  # report_nm 없음
            {"rcept_no": "20240101000002", "report_nm": "정상 공시"},
        ]
        drafts = parse_disclosures(rows)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].rcept_no, "20240101000002")

    def test_status_013_is_empty_not_error(self) -> None:
        self.assertEqual(_disclosure_list_from_response({"status": "013"}), [])

    def test_status_error_raises(self) -> None:
        with self.assertRaises(OpenDartError):
            _disclosure_list_from_response(
                {"status": "020", "message": "요청 제한 초과"}
            )

    def test_status_000_returns_list(self) -> None:
        items = _disclosure_list_from_response(
            {"status": "000", "list": SAMPLE_DISCLOSURES}
        )
        self.assertEqual(len(items), 2)


class DisclosureCollectionTests(unittest.TestCase):
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

    def test_resolve_corp_code(self) -> None:
        self._seed_symbol()
        self.assertEqual(resolve_corp_code(self.db, "005930"), "00126380")
        self.assertIsNone(resolve_corp_code(self.db, "000000"))

    def test_store_disclosures_dedupes(self) -> None:
        symbol = self._seed_symbol()
        drafts = parse_disclosures(SAMPLE_DISCLOSURES)
        self.assertEqual(store_disclosures(self.db, symbol.id, drafts), 2)
        self.db.commit()

        # re-collecting the same disclosures inserts nothing new
        self.assertEqual(store_disclosures(self.db, symbol.id, drafts), 0)
        self.db.commit()

        rows = self.db.execute(select(Disclosure)).scalars().all()
        self.assertEqual(len(rows), 2)

    def test_collect_disclosures_success(self) -> None:
        symbol = self._seed_symbol()
        captured: dict[str, str] = {}

        def fake_fetcher(corp_code: str, bgn_de: str, end_de: str) -> list[dict]:
            captured["corp_code"] = corp_code
            return SAMPLE_DISCLOSURES

        run = collect_disclosures(self.db, api_key="test-key", fetcher=fake_fetcher)
        self.assertEqual(run.status, "success")
        self.assertEqual(run.symbols_processed, 1)
        self.assertEqual(run.disclosures_inserted, 2)
        self.assertEqual(captured["corp_code"], "00126380")

        stored = (
            self.db.execute(
                select(Disclosure).where(Disclosure.symbol_id == symbol.id)
            )
            .scalars()
            .all()
        )
        self.assertEqual(len(stored), 2)

    def test_collect_disclosures_redirects_preferred_to_common(self) -> None:
        # Register 삼성전자우; map the corp_code under the common stock code only.
        self.db.add(Symbol(market="KOSPI", code="005935", name="삼성전자우"))
        self.db.add(
            DartCorpCode(
                corp_code="00126380", stock_code="005930", corp_name="삼성전자"
            )
        )
        self.db.commit()
        captured: dict[str, str] = {}

        def fake_fetcher(corp_code: str, bgn_de: str, end_de: str) -> list[dict]:
            captured["corp_code"] = corp_code
            return SAMPLE_DISCLOSURES

        runtime = (
            ListedSymbol("KOSPI", "005930", "삼성전자"),
            ListedSymbol("KOSPI", "005935", "삼성전자우"),
        )
        with patch(
            "app.services.symbol_catalog.listed_symbols", return_value=runtime
        ):
            run = collect_disclosures(self.db, api_key="k", fetcher=fake_fetcher)
        self.assertEqual(run.status, "success")
        self.assertEqual(captured["corp_code"], "00126380")

    def test_collect_disclosures_is_idempotent(self) -> None:
        self._seed_symbol()

        def fetcher(*_args: str) -> list[dict]:
            return SAMPLE_DISCLOSURES

        first = collect_disclosures(self.db, api_key="k", fetcher=fetcher)
        second = collect_disclosures(self.db, api_key="k", fetcher=fetcher)
        self.assertEqual(first.disclosures_inserted, 2)
        self.assertEqual(second.disclosures_inserted, 0)
        self.assertEqual(second.status, "success")

    def test_collect_disclosures_missing_corp_code_fails(self) -> None:
        self._seed_symbol(code="999990", name="미매핑종목", corp_code=None)
        run = collect_disclosures(
            self.db, api_key="k", fetcher=lambda *_args: SAMPLE_DISCLOSURES
        )
        self.assertEqual(run.status, "failed")
        self.assertIn("미매핑", run.message or "")

    def test_collect_disclosures_partial_success(self) -> None:
        self._seed_symbol(code="005930", name="삼성전자", corp_code="00126380")
        self._seed_symbol(code="999990", name="미매핑종목", corp_code=None)
        run = collect_disclosures(
            self.db, api_key="k", fetcher=lambda *_args: SAMPLE_DISCLOSURES
        )
        # one symbol succeeded -> overall success, the failure noted in message
        self.assertEqual(run.status, "success")
        self.assertEqual(run.symbols_processed, 1)
        self.assertEqual(run.disclosures_inserted, 2)
        self.assertIn("미매핑", run.message or "")

    def test_collect_disclosures_without_key_fails(self) -> None:
        self._seed_symbol()
        run = collect_disclosures(self.db, api_key="")
        self.assertEqual(run.status, "failed")
        self.assertIn("OPENDART_API_KEY", run.message or "")


if __name__ == "__main__":
    unittest.main()
