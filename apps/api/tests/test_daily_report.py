"""Tests for the daily report service, weekday/time guard, and router."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DailyPrice, DailyReport, Symbol, User
from app.routers.reports import list_daily_reports
from app.services import daily_report as dr

_KST = timezone(timedelta(hours=9))


class _FakeGenerator:
    """Report generator stub returning a fixed reply (or ``None``)."""

    model_name = "fake-report"

    def __init__(self, response: str | None) -> None:
        self._response = response
        self.calls = 0

    def generate(self, prompt: str) -> str | None:
        self.calls += 1
        return self._response


class ParseReportResponseTests(unittest.TestCase):
    def test_empty_or_none_falls_back_to_hold(self) -> None:
        self.assertEqual(dr.parse_report_response(None), ("hold", "", None))
        self.assertEqual(dr.parse_report_response("   "), ("hold", "", None))

    def test_full_format_is_parsed(self) -> None:
        rec, summary, rationale = dr.parse_report_response(
            "OPINION: SELL\n\n실적이 부진하다.\n전망도 약하다.\nRATIONALE: 적자 전환"
        )
        self.assertEqual(rec, "sell")
        self.assertIn("실적이 부진", summary)
        self.assertIn("전망도 약", summary)
        self.assertEqual(rationale, "적자 전환")

    def test_missing_opinion_keeps_text_as_summary(self) -> None:
        rec, summary, rationale = dr.parse_report_response("그냥 줄글 리포트")
        self.assertEqual(rec, "hold")
        self.assertEqual(summary, "그냥 줄글 리포트")
        self.assertIsNone(rationale)

    def test_korean_opinion_words_map(self) -> None:
        self.assertEqual(dr.parse_report_response("OPINION: 매수\n\nx")[0], "buy")
        self.assertEqual(dr.parse_report_response("OPINION: 매도\n\nx")[0], "sell")


class _DbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _add_symbol(
        self,
        *,
        code: str = "005930",
        name: str = "삼성전자",
        owner_user_id: int | None = None,
    ) -> Symbol:
        symbol = Symbol(
            market="KOSPI", code=code, name=name, owner_user_id=owner_user_id
        )
        self.db.add(symbol)
        self.db.commit()
        return symbol

    def _add_user(self, *, email: str = "owner@example.com") -> User:
        user = User(email=email)
        self.db.add(user)
        self.db.commit()
        return user

    def _add_price(self, symbol_id: int, trade_date: str, close: float) -> None:
        self.db.add(
            DailyPrice(symbol_id=symbol_id, trade_date=trade_date, close=close)
        )
        self.db.commit()


class GenerateDailyReportsTests(_DbTestCase):
    def test_generates_and_computes_change(self) -> None:
        symbol = self._add_symbol()
        self._add_price(symbol.id, "2026-06-04", 100)
        self._add_price(symbol.id, "2026-06-05", 110)
        gen = _FakeGenerator("OPINION: BUY\n\n상승세.\nRATIONALE: 모멘텀")

        generated, skipped, failures = dr.generate_daily_reports(
            self.db, report_date="2026-06-08", generator=gen
        )

        self.assertEqual((generated, skipped, failures), (1, 0, []))
        report = self.db.execute(select(DailyReport)).scalar_one()
        self.assertEqual(report.recommendation, "buy")
        self.assertEqual(report.prev_trade_date, "2026-06-05")
        self.assertAlmostEqual(float(report.prev_close), 110.0)
        self.assertAlmostEqual(float(report.change_pct), 10.0)  # (110-100)/100
        self.assertEqual(report.model_name, "fake-report")

    def test_none_response_is_not_stored(self) -> None:
        self._add_symbol()
        gen = _FakeGenerator(None)
        generated, skipped, _ = dr.generate_daily_reports(
            self.db, report_date="2026-06-08", generator=gen
        )
        self.assertEqual((generated, skipped), (0, 1))
        self.assertEqual(self.db.execute(select(DailyReport)).scalars().all(), [])

    def test_duplicate_is_skipped_then_overwritten(self) -> None:
        self._add_symbol()
        dr.generate_daily_reports(
            self.db,
            report_date="2026-06-08",
            generator=_FakeGenerator("OPINION: HOLD\n\n중립."),
        )
        g2, s2, _ = dr.generate_daily_reports(
            self.db,
            report_date="2026-06-08",
            generator=_FakeGenerator("OPINION: BUY\n\n바뀜."),
        )
        self.assertEqual((g2, s2), (0, 1))  # already exists → skipped

        g3, _, _ = dr.generate_daily_reports(
            self.db,
            report_date="2026-06-08",
            generator=_FakeGenerator("OPINION: SELL\n\n갱신."),
            overwrite=True,
        )
        self.assertEqual(g3, 1)
        report = self.db.execute(select(DailyReport)).scalar_one()
        self.assertEqual(report.recommendation, "sell")

    def test_no_symbols_calls_nothing(self) -> None:
        gen = _FakeGenerator("OPINION: BUY\n\nx")
        self.assertEqual(
            dr.generate_daily_reports(self.db, report_date="2026-06-08", generator=gen),
            (0, 0, []),
        )
        self.assertEqual(gen.calls, 0)

    def test_empty_symbol_ids_is_noop(self) -> None:
        self._add_symbol()
        gen = _FakeGenerator("OPINION: BUY\n\nx")
        self.assertEqual(
            dr.generate_daily_reports(
                self.db, report_date="2026-06-08", generator=gen, symbol_ids=[]
            ),
            (0, 0, []),
        )
        self.assertEqual(gen.calls, 0)

    def test_cold_cache_still_reports_without_prices(self) -> None:
        self._add_symbol()
        gen = _FakeGenerator("OPINION: HOLD\n\n데이터 부족.")
        generated, _, _ = dr.generate_daily_reports(
            self.db, report_date="2026-06-08", generator=gen
        )
        self.assertEqual(generated, 1)
        report = self.db.execute(select(DailyReport)).scalar_one()
        self.assertIsNone(report.prev_close)
        self.assertIsNone(report.change_pct)
        self.assertIsNone(report.prev_trade_date)

    def test_one_symbol_failure_does_not_abort_batch(self) -> None:
        self._add_symbol(code="005930", name="삼성전자")
        healthy = self._add_symbol(code="000660", name="SK하이닉스")

        class _Selective:
            model_name = "selective"

            def generate(self, prompt: str) -> str | None:
                if "삼성전자" in prompt:
                    raise RuntimeError("boom")
                return "OPINION: BUY\n\n좋음."

        generated, _, failures = dr.generate_daily_reports(
            self.db, report_date="2026-06-08", generator=_Selective()
        )
        self.assertEqual(generated, 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("삼성전자", failures[0])
        # The healthy symbol's report is still saved.
        report = self.db.execute(select(DailyReport)).scalar_one()
        self.assertEqual(report.symbol_id, healthy.id)


class ShouldGenerateTodayTests(_DbTestCase):
    def _now(self, *, day: int, hour: int, minute: int) -> datetime:
        return datetime(2026, 6, day, hour, minute, tzinfo=_KST)

    def test_weekend_is_false(self) -> None:
        # 2026-06-06 is a Saturday.
        self.assertFalse(
            dr.should_generate_today(self.db, now_kst=self._now(day=6, hour=9, minute=0))
        )

    def test_before_0830_is_false(self) -> None:
        # 2026-06-05 is a Friday.
        self.assertFalse(
            dr.should_generate_today(
                self.db, now_kst=self._now(day=5, hour=8, minute=29)
            )
        )

    def test_weekday_at_0830_is_true(self) -> None:
        self.assertTrue(
            dr.should_generate_today(
                self.db, now_kst=self._now(day=5, hour=8, minute=30)
            )
        )

    def test_already_generated_today_is_false(self) -> None:
        symbol = self._add_symbol()
        self.db.add(
            DailyReport(
                symbol_id=symbol.id,
                report_date="2026-06-05",
                recommendation="hold",
                summary="x",
                model_name="m",
            )
        )
        self.db.commit()
        self.assertFalse(
            dr.should_generate_today(self.db, now_kst=self._now(day=5, hour=9, minute=0))
        )


class ListDailyReportsRouterTests(_DbTestCase):
    def test_latest_date_with_flattened_symbol_fields(self) -> None:
        user = self._add_user()
        symbol = self._add_symbol(owner_user_id=user.id)
        self.db.add_all(
            [
                DailyReport(
                    symbol_id=symbol.id,
                    report_date="2026-06-04",
                    recommendation="hold",
                    summary="old",
                    model_name="m",
                ),
                DailyReport(
                    symbol_id=symbol.id,
                    report_date="2026-06-05",
                    recommendation="buy",
                    summary="new",
                    model_name="m",
                ),
            ]
        )
        self.db.commit()

        result = list_daily_reports(date=None, db=self.db, user=user)
        self.assertEqual(result.report_date, "2026-06-05")
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.recommendation, "buy")
        self.assertEqual(item.summary, "new")
        self.assertEqual(item.symbol_name, "삼성전자")
        self.assertEqual(item.symbol_code, "005930")

    def test_empty_when_no_reports(self) -> None:
        user = self._add_user()
        result = list_daily_reports(date=None, db=self.db, user=user)
        self.assertIsNone(result.report_date)
        self.assertEqual(result.items, [])

    def test_only_reports_for_symbols_the_user_registered(self) -> None:
        user = self._add_user(email="me@example.com")
        other = self._add_user(email="other@example.com")
        mine = self._add_symbol(code="005930", name="삼성전자", owner_user_id=user.id)
        theirs = self._add_symbol(
            code="000660", name="SK하이닉스", owner_user_id=other.id
        )
        seeded = self._add_symbol(code="035720", name="카카오", owner_user_id=None)
        for sym in (mine, theirs, seeded):
            self.db.add(
                DailyReport(
                    symbol_id=sym.id,
                    report_date="2026-06-05",
                    recommendation="buy",
                    summary="s",
                    model_name="m",
                )
            )
        self.db.commit()

        result = list_daily_reports(date=None, db=self.db, user=user)
        self.assertEqual(result.report_date, "2026-06-05")
        self.assertEqual([item.symbol_code for item in result.items], ["005930"])

    def test_latest_date_ignores_other_users_newer_reports(self) -> None:
        user = self._add_user(email="me@example.com")
        other = self._add_user(email="other@example.com")
        mine = self._add_symbol(code="005930", name="삼성전자", owner_user_id=user.id)
        theirs = self._add_symbol(
            code="000660", name="SK하이닉스", owner_user_id=other.id
        )
        self.db.add_all(
            [
                DailyReport(
                    symbol_id=mine.id,
                    report_date="2026-06-04",
                    recommendation="buy",
                    summary="mine",
                    model_name="m",
                ),
                DailyReport(
                    symbol_id=theirs.id,
                    report_date="2026-06-05",
                    recommendation="buy",
                    summary="theirs",
                    model_name="m",
                ),
            ]
        )
        self.db.commit()

        result = list_daily_reports(date=None, db=self.db, user=user)
        self.assertEqual(result.report_date, "2026-06-04")
        self.assertEqual([item.symbol_code for item in result.items], ["005930"])


class CascadeTests(_DbTestCase):
    def test_deleting_symbol_removes_its_reports(self) -> None:
        symbol = self._add_symbol()
        self.db.add(
            DailyReport(
                symbol_id=symbol.id,
                report_date="2026-06-05",
                recommendation="hold",
                summary="x",
                model_name="m",
            )
        )
        self.db.commit()

        self.db.delete(symbol)
        self.db.commit()

        self.assertEqual(self.db.execute(select(DailyReport)).scalars().all(), [])


if __name__ == "__main__":
    unittest.main()
