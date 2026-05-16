import unittest

from app.services.prices import PriceBar, PriceFetchError, parse_price_rows


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


if __name__ == "__main__":
    unittest.main()
