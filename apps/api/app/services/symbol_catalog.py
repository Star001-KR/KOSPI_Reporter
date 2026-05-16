from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ListedSymbol:
    market: str
    code: str
    name: str


SUPPORTED_MARKETS = frozenset({"KOSPI", "KOSDAQ"})

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
        if not use_market or normalized_market is None:
            return list(KR_LISTED_SYMBOLS)
        return [item for item in KR_LISTED_SYMBOLS if item.market == normalized_market]

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
