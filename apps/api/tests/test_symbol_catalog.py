"""Tests for the KRX-backed symbol catalog."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.services.symbol_catalog import (
    ListedSymbol,
    listed_symbols,
    lookup_symbols,
    parse_krx_stock_finder,
)


KRX_FINDER_SAMPLE = json.dumps(
    {
        "block1": [
            {"short_code": "005930", "codeName": "삼성전자", "marketCode": "STK"},
            {"short_code": "005935", "codeName": "삼성전자우", "marketCode": "STK"},
            {"short_code": "060310", "codeName": "3S", "marketCode": "KSQ"},
            {"short_code": "111111", "codeName": "코넥스테스트", "marketCode": "KNX"},
            {"short_code": "12345", "codeName": "형식오류", "marketCode": "STK"},
        ]
    }
).encode()


class SymbolCatalogTests(unittest.TestCase):
    def test_parse_krx_stock_finder_includes_preferred_stocks(self) -> None:
        parsed = parse_krx_stock_finder(KRX_FINDER_SAMPLE)
        # Preferred stock (005935) kept; KONEX row and malformed code dropped.
        self.assertEqual(
            parsed,
            [
                ListedSymbol("KOSPI", "005930", "삼성전자"),
                ListedSymbol("KOSPI", "005935", "삼성전자우"),
                ListedSymbol("KOSDAQ", "060310", "3S"),
            ],
        )

    def test_parse_krx_stock_finder_tolerates_bad_payload(self) -> None:
        self.assertEqual(parse_krx_stock_finder(b"not json"), [])

    def test_listed_symbols_falls_back_to_static_catalog(self) -> None:
        symbols = listed_symbols(loader=lambda: (_ for _ in ()).throw(RuntimeError()))
        codes = {symbol.code for symbol in symbols}
        self.assertIn("005930", codes)
        self.assertIn("005935", codes)  # 삼성전자우, a preferred stock

    def test_lookup_uses_runtime_catalog(self) -> None:
        runtime = (ListedSymbol("KOSPI", "096770", "SK이노베이션"),)
        with patch("app.services.symbol_catalog.listed_symbols", return_value=runtime):
            self.assertEqual(lookup_symbols("096770", market="KOSPI"), list(runtime))
            self.assertEqual(lookup_symbols("SK이노", market="KOSPI"), list(runtime))

    def test_lookup_finds_preferred_stock(self) -> None:
        runtime = (
            ListedSymbol("KOSPI", "005930", "삼성전자"),
            ListedSymbol("KOSPI", "005935", "삼성전자우"),
        )
        with patch("app.services.symbol_catalog.listed_symbols", return_value=runtime):
            # The preferred stock is searchable by its own name.
            self.assertEqual(
                lookup_symbols("삼성전자우", market="KOSPI"),
                [ListedSymbol("KOSPI", "005935", "삼성전자우")],
            )
            # A common-stock query surfaces the preferred share too.
            codes = [item.code for item in lookup_symbols("삼성전자", market="KOSPI")]
            self.assertEqual(codes, ["005930", "005935"])


if __name__ == "__main__":
    unittest.main()
