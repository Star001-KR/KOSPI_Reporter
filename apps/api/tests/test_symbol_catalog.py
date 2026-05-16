"""Tests for the KRX/KIND backed symbol catalog."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.symbol_catalog import (
    ListedSymbol,
    listed_symbols,
    lookup_symbols,
    parse_kind_corp_list,
)


KIND_SAMPLE = """
<html><body>
  <table>
    <tr><th>회사명</th><th>시장구분</th><th>종목코드</th><th>업종</th></tr>
    <tr><td>SK이노베이션</td><td>유가</td><td>096770</td><td>석유 정제품 제조업</td></tr>
    <tr><td>테스트스팩</td><td>코스닥</td><td>12345</td><td>형식 오류</td></tr>
  </table>
</body></html>
""".encode("euc-kr")


class SymbolCatalogTests(unittest.TestCase):
    def test_parse_kind_corp_list(self) -> None:
        parsed = parse_kind_corp_list(KIND_SAMPLE, "KOSPI")
        self.assertEqual(parsed, [ListedSymbol("KOSPI", "096770", "SK이노베이션")])

    def test_listed_symbols_falls_back_to_static_catalog(self) -> None:
        symbols = listed_symbols(loader=lambda: (_ for _ in ()).throw(RuntimeError()))
        self.assertTrue(any(symbol.code == "005930" for symbol in symbols))

    def test_lookup_uses_runtime_catalog(self) -> None:
        runtime = (ListedSymbol("KOSPI", "096770", "SK이노베이션"),)
        with patch("app.services.symbol_catalog.listed_symbols", return_value=runtime):
            self.assertEqual(lookup_symbols("096770", market="KOSPI"), list(runtime))
            self.assertEqual(lookup_symbols("SK이노", market="KOSPI"), list(runtime))


if __name__ == "__main__":
    unittest.main()
