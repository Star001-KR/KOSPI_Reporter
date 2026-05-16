from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ListedSymbol:
    market: str
    code: str
    name: str


SUPPORTED_MARKETS = frozenset({"KOSPI", "KOSDAQ"})
KIND_CORP_LIST_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"
KIND_MARKET_TYPES = {
    "KOSPI": "stockMkt",
    "KOSDAQ": "kosdaqMkt",
}
_REQUEST_TIMEOUT_SECONDS = 20.0

KR_LISTED_SYMBOLS: tuple[ListedSymbol, ...] = (
    ListedSymbol("KOSPI", "005930", "삼성전자"),
    ListedSymbol("KOSPI", "000660", "SK하이닉스"),
    ListedSymbol("KOSPI", "035420", "NAVER"),
    ListedSymbol("KOSPI", "035720", "카카오"),
    ListedSymbol("KOSPI", "005380", "현대차"),
    ListedSymbol("KOSPI", "000270", "기아"),
    ListedSymbol("KOSPI", "068270", "셀트리온"),
    ListedSymbol("KOSPI", "207940", "삼성바이오로직스"),
    ListedSymbol("KOSPI", "373220", "LG에너지솔루션"),
    ListedSymbol("KOSPI", "005490", "POSCO홀딩스"),
    ListedSymbol("KOSPI", "051910", "LG화학"),
    ListedSymbol("KOSPI", "006400", "삼성SDI"),
    ListedSymbol("KOSPI", "105560", "KB금융"),
    ListedSymbol("KOSPI", "055550", "신한지주"),
    ListedSymbol("KOSPI", "086790", "하나금융지주"),
    ListedSymbol("KOSPI", "316140", "우리금융지주"),
    ListedSymbol("KOSPI", "012330", "현대모비스"),
    ListedSymbol("KOSPI", "003670", "포스코퓨처엠"),
    ListedSymbol("KOSPI", "066570", "LG전자"),
    ListedSymbol("KOSPI", "028260", "삼성물산"),
    ListedSymbol("KOSPI", "032830", "삼성생명"),
    ListedSymbol("KOSPI", "034020", "두산에너빌리티"),
    ListedSymbol("KOSPI", "042660", "한화오션"),
    ListedSymbol("KOSPI", "009150", "삼성전기"),
    ListedSymbol("KOSPI", "017670", "SK텔레콤"),
    ListedSymbol("KOSPI", "030200", "KT"),
    ListedSymbol("KOSPI", "033780", "KT&G"),
    ListedSymbol("KOSPI", "018260", "삼성에스디에스"),
    ListedSymbol("KOSPI", "024110", "기업은행"),
    ListedSymbol("KOSPI", "259960", "크래프톤"),
    ListedSymbol("KOSPI", "011200", "HMM"),
    ListedSymbol("KOSPI", "011070", "LG이노텍"),
    ListedSymbol("KOSPI", "009540", "HD한국조선해양"),
    ListedSymbol("KOSPI", "010130", "고려아연"),
    ListedSymbol("KOSPI", "010140", "삼성중공업"),
    ListedSymbol("KOSPI", "047050", "포스코인터내셔널"),
    ListedSymbol("KOSPI", "011170", "롯데케미칼"),
    ListedSymbol("KOSPI", "003550", "LG"),
    ListedSymbol("KOSPI", "015760", "한국전력"),
    ListedSymbol("KOSPI", "086280", "현대글로비스"),
    ListedSymbol("KOSPI", "010950", "S-Oil"),
    ListedSymbol("KOSDAQ", "247540", "에코프로비엠"),
    ListedSymbol("KOSDAQ", "086520", "에코프로"),
    ListedSymbol("KOSDAQ", "035900", "JYP Ent."),
    ListedSymbol("KOSDAQ", "041510", "에스엠"),
    ListedSymbol("KOSDAQ", "112040", "위메이드"),
    ListedSymbol("KOSDAQ", "263750", "펄어비스"),
    ListedSymbol("KOSDAQ", "293490", "카카오게임즈"),
    ListedSymbol("KOSDAQ", "145020", "휴젤"),
    ListedSymbol("KOSDAQ", "067310", "하나마이크론"),
    ListedSymbol("KOSDAQ", "078600", "대주전자재료"),
    ListedSymbol("KOSDAQ", "058470", "리노공업"),
    ListedSymbol("KOSDAQ", "240810", "원익IPS"),
    ListedSymbol("KOSDAQ", "039030", "이오테크닉스"),
    ListedSymbol("KOSDAQ", "140860", "파크시스템스"),
    ListedSymbol("KOSDAQ", "095340", "ISC"),
    ListedSymbol("KOSDAQ", "222800", "심텍"),
    ListedSymbol("KOSDAQ", "214150", "클래시스"),
    ListedSymbol("KOSDAQ", "005290", "동진쎄미켐"),
    ListedSymbol("KOSDAQ", "036930", "주성엔지니어링"),
    ListedSymbol("KOSDAQ", "196170", "알테오젠"),
    ListedSymbol("KOSDAQ", "028300", "HLB"),
    ListedSymbol("KOSDAQ", "214450", "파마리서치"),
)


class _KindTableParser(HTMLParser):
    """Extract rows from the KRX/KIND Excel-download HTML table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell_chunks: list[str] | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_chunks = []

    def handle_endtag(self, tag: str) -> None:
        if (
            tag in {"td", "th"}
            and self._row is not None
            and self._cell_chunks is not None
        ):
            self._row.append(" ".join("".join(self._cell_chunks).split()))
            self._cell_chunks = None
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell_chunks = None

    def handle_data(self, data: str) -> None:
        if self._cell_chunks is not None:
            self._cell_chunks.append(data)


def parse_kind_corp_list(payload: bytes, market: str) -> list[ListedSymbol]:
    """Parse the official KRX/KIND listed-corporation download."""
    normalized_market = normalize_market(market)
    if normalized_market is None:
        return []
    parser = _KindTableParser()
    parser.feed(payload.decode("euc-kr", errors="replace"))
    parser.close()

    symbols: list[ListedSymbol] = []
    header = next(
        (
            row
            for row in parser.rows
            if "회사명" in row and "종목코드" in row
        ),
        [],
    )
    try:
        name_index = header.index("회사명")
        code_index = header.index("종목코드")
    except ValueError:
        name_index = 0
        code_index = 1
    market_index = header.index("시장구분") if "시장구분" in header else None

    def market_from_row(row: list[str]) -> str:
        if market_index is None or market_index >= len(row):
            return normalized_market
        label = compact(row[market_index])
        if label in {"유가", "kospi"}:
            return "KOSPI"
        if label in {"코스닥", "kosdaq"}:
            return "KOSDAQ"
        return normalized_market

    for row in parser.rows:
        if len(row) <= max(name_index, code_index):
            continue
        name = normalize_text(row[name_index])
        code = normalize_code(row[code_index])
        if not name or not code or not code.isalnum() or len(code) != 6:
            continue
        symbols.append(ListedSymbol(market_from_row(row), code, name))
    return symbols


def _download_kind_corp_list(market: str) -> bytes:
    market_type = KIND_MARKET_TYPES[market]
    params = {
        "method": "download",
        "searchType": "13",
        "marketType": market_type,
    }
    url = f"{KIND_CORP_LIST_URL}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
        return response.read()


@lru_cache(maxsize=1)
def _krx_listed_symbols() -> tuple[ListedSymbol, ...]:
    symbols: list[ListedSymbol] = []
    for market in ("KOSPI", "KOSDAQ"):
        symbols.extend(parse_kind_corp_list(_download_kind_corp_list(market), market))
    if not symbols:
        raise RuntimeError("KRX/KIND listed symbol catalog is empty.")
    return tuple(symbols)


def listed_symbols(
    loader: Callable[[], tuple[ListedSymbol, ...]] = _krx_listed_symbols,
) -> tuple[ListedSymbol, ...]:
    """Return the runtime KOSPI/KOSDAQ symbol catalog.

    KRX/KIND is the source of truth. The small static list is kept as a local
    fallback so development and tests still work when the official download is
    temporarily unavailable.
    """
    try:
        current = loader()
    except Exception:
        return KR_LISTED_SYMBOLS

    merged: dict[tuple[str, str], ListedSymbol] = {}
    for item in current:
        merged.setdefault((item.market, item.code), item)
    return tuple(merged.values()) or KR_LISTED_SYMBOLS


def normalize_market(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized == "KR":
        normalized = "KOSPI"
    return normalized if normalized in SUPPORTED_MARKETS else None


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def normalize_code(value: str | None) -> str | None:
    normalized = normalize_text(value)
    return normalized.upper() if normalized else None


def compact(value: str) -> str:
    return "".join(value.casefold().split())


def lookup_symbols(
    query: str,
    *,
    market: str | None = None,
    limit: int = 8,
) -> list[ListedSymbol]:
    normalized_query = normalize_text(query)
    if not normalized_query:
        return []

    normalized_market = normalize_market(market)
    if market is not None and normalized_market is None:
        return []
    query_code = normalized_query.upper()
    query_name = compact(normalized_query)

    def candidates(use_market: bool) -> list[ListedSymbol]:
        source = listed_symbols()
        if not use_market or normalized_market is None:
            return list(source)
        return [item for item in source if item.market == normalized_market]

    def scored(items: list[ListedSymbol]) -> list[tuple[int, ListedSymbol]]:
        matches: list[tuple[int, ListedSymbol]] = []
        for item in items:
            item_name = compact(item.name)
            if item.code == query_code:
                matches.append((0, item))
            elif item_name == query_name:
                matches.append((1, item))
            elif item.code.startswith(query_code):
                matches.append((2, item))
            elif item_name.startswith(query_name):
                matches.append((3, item))
            elif query_name in item_name:
                matches.append((4, item))
        return sorted(matches, key=lambda row: (row[0], row[1].market, row[1].code))

    ranked = scored(candidates(use_market=True))
    if not ranked:
        ranked = scored(candidates(use_market=False))

    return [item for _, item in ranked[:limit]]


def resolve_single_symbol(
    *,
    market: str,
    code: str | None,
    name: str | None,
) -> tuple[ListedSymbol | None, list[ListedSymbol]]:
    normalized_code = normalize_code(code)
    normalized_name = normalize_text(name)
    normalized_market = normalize_market(market)
    if normalized_market is None:
        return None, []
    if normalized_code and normalized_name:
        return (
            ListedSymbol(
                market=normalized_market,
                code=normalized_code,
                name=normalized_name,
            ),
            [],
        )

    query = normalized_code or normalized_name
    if query is None:
        return None, []

    matches = lookup_symbols(query, market=market, limit=10)
    exact_matches = [
        item
        for item in matches
        if item.code == (normalized_code or "").upper()
        or compact(item.name) == compact(normalized_name or "")
    ]
    if len(exact_matches) == 1:
        return exact_matches[0], []
    if len(matches) == 1:
        return matches[0], []
    return None, matches
