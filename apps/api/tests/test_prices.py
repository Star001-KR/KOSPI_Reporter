import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DailyPrice, Symbol
from app.services.prices import (
    PriceBar,
    PriceFetchError,
    collect_prices_for_symbols,
    get_symbol_prices,
    parse_price_rows,
)


class ParsePriceRowsTests(unittest.TestCase):
    def test_parses_payload_and_skips_header(self) -> None:
        raw = (
            "[['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율'],\n"
            "['20240102', 78500, 79000, 76500, 79000, 17004111, 54.39],\n"
            "['20240103', 78200, 78500, 76500, 76600, 21753644, 54.18]]"
        )
        self.assertEqual(
            parse_price_rows(raw),
            [
                PriceBar(trade_date="2024-01-02", close=79000.0),
                PriceBar(trade_date="2024-01-03", close=76600.0),
            ],
        )

    def test_sorts_rows_by_date(self) -> None:
        raw = (
            "[['20240105', 1, 1, 1, 300, 1, 1],"
            "['20240103', 1, 1, 1, 100, 1, 1]]"
        )
        self.assertEqual(
            [bar.trade_date for bar in parse_price_rows(raw)],
            ["2024-01-03", "2024-01-05"],
        )

    def test_skips_malformed_and_nonpositive_rows(self) -> None:
        raw = (
            "[['20240105', 1, 1, 1, 0, 1, 1],"  # zero close -> skipped
            "['bad', 1, 1, 1, 100, 1, 1],"  # non-date -> skipped
            "['20240106', 1, 1, 1, 250, 1, 1]]"
        )
        self.assertEqual(
            parse_price_rows(raw),
            [PriceBar(trade_date="2024-01-06", close=250.0)],
        )

    def test_empty_payload_returns_empty(self) -> None:
        self.assertEqual(parse_price_rows("   "), [])

    def test_invalid_payload_raises(self) -> None:
        with self.assertRaises(PriceFetchError):
            parse_price_rows("not-json-at-all{")


class CollectPricesForSymbolsTests(unittest.TestCase):
    """The scheduler's price step writes through to the cache; the
    user-facing read path never reaches outside."""

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)()
        self.symbol_a = Symbol(market="KOSPI", code="005930", name="삼성전자")
        self.symbol_b = Symbol(market="KOSPI", code="000660", name="SK하이닉스")
        self.db.add_all([self.symbol_a, self.symbol_b])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_fetches_and_stores_per_symbol(self) -> None:
        bars_by_code = {
            "005930": [
                PriceBar(trade_date="2026-05-19", close=82000.0),
                PriceBar(trade_date="2026-05-20", close=82500.0),
            ],
            "000660": [PriceBar(trade_date="2026-05-20", close=210000.0)],
        }

        def fake_fetcher(code: str, *, days: int) -> list[PriceBar]:
            return bars_by_code.get(code, [])

        processed, inserted, skipped, failures = collect_prices_for_symbols(
            self.db, [self.symbol_a, self.symbol_b], fetcher=fake_fetcher
        )
        self.db.commit()

        self.assertEqual(processed, 2)
        self.assertEqual(inserted, 3)
        self.assertEqual(skipped, 0)
        self.assertEqual(failures, [])

        stored = self.db.execute(select(DailyPrice)).scalars().all()
        self.assertEqual(len(stored), 3)

    def test_per_symbol_fetch_error_does_not_abort_the_run(self) -> None:
        def fake_fetcher(code: str, *, days: int) -> list[PriceBar]:
            if code == "005930":
                raise PriceFetchError("네이버 응답 실패")
            return [PriceBar(trade_date="2026-05-20", close=210000.0)]

        processed, inserted, skipped, failures = collect_prices_for_symbols(
            self.db, [self.symbol_a, self.symbol_b], fetcher=fake_fetcher
        )
        self.db.commit()

        self.assertEqual(processed, 1)
        self.assertEqual(inserted, 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(len(failures), 1)
        self.assertIn("삼성전자", failures[0])

    def test_get_symbol_prices_never_calls_external(self) -> None:
        """Read path is DB-only; an empty cache stays empty, no fetcher runs."""
        prices = get_symbol_prices(self.db, self.symbol_a)
        self.assertEqual(prices, [])

        # After the scheduler runs, the read path surfaces what was stored.
        bars = [PriceBar(trade_date="2026-05-20", close=82500.0)]
        collect_prices_for_symbols(
            self.db, [self.symbol_a], fetcher=lambda *_, **__: bars
        )
        self.db.commit()
        prices = get_symbol_prices(self.db, self.symbol_a)
        self.assertEqual([p.close for p in prices], [82500.0])

    def test_skips_symbol_refreshed_earlier_today(self) -> None:
        """A symbol whose cache was touched today (KST) is not re-fetched."""
        calls: list[str] = []

        def fake_fetcher(code: str, *, days: int) -> list[PriceBar]:
            calls.append(code)
            return [PriceBar(trade_date="2026-05-20", close=82500.0)]

        # First run populates the cache with collected_at = now (today, KST).
        collect_prices_for_symbols(
            self.db, [self.symbol_a], fetcher=fake_fetcher
        )
        self.db.commit()

        # A second run on the same day must skip the fetcher entirely.
        processed, inserted, skipped, failures = collect_prices_for_symbols(
            self.db, [self.symbol_a], fetcher=fake_fetcher
        )
        self.assertEqual(calls, ["005930"])  # fetched once, not twice
        self.assertEqual(processed, 0)
        self.assertEqual(inserted, 0)
        self.assertEqual(skipped, 1)
        self.assertEqual(failures, [])

    def test_refetches_when_cache_is_from_an_earlier_day(self) -> None:
        """A cache collected on a previous day is refreshed, not skipped."""
        self.db.add(
            DailyPrice(
                symbol_id=self.symbol_a.id,
                trade_date="2026-05-19",
                close=80000.0,
                collected_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            )
        )
        self.db.commit()

        calls: list[str] = []

        def fake_fetcher(code: str, *, days: int) -> list[PriceBar]:
            calls.append(code)
            return [PriceBar(trade_date="2026-05-20", close=82500.0)]

        processed, inserted, skipped, failures = collect_prices_for_symbols(
            self.db, [self.symbol_a], fetcher=fake_fetcher
        )
        self.assertEqual(calls, ["005930"])  # stale cache -> fetched
        self.assertEqual(processed, 1)
        self.assertEqual(skipped, 0)


if __name__ == "__main__":
    unittest.main()
