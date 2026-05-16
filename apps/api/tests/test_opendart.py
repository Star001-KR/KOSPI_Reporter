"""Unit tests for the OpenDART corp code import service (MVP-01)."""

from __future__ import annotations

import io
import unittest
import zipfile

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import CollectionRun, DartCorpCode
from app.services.opendart import (
    OpenDartError,
    extract_corp_code_xml,
    parse_corp_code_xml,
    run_corp_code_import,
    upsert_corp_codes,
)

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


if __name__ == "__main__":
    unittest.main()
