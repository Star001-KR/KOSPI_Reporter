"""A keyless, rule-based Analyzer implementation.

It classifies collected news and disclosures with Korean keyword heuristics,
so the pipeline can produce analysis results without any external LLM or API
key. Swap in an LLM-backed Analyzer later by implementing the Analyzer
protocol from `kospi_core.contracts`.
"""

from __future__ import annotations

from .contracts import AnalysisDraft, AnalysisSubject, Sentiment

MODEL_NAME = "rule-based-analyzer"
MODEL_VERSION = "0.1"

_POSITIVE_KEYWORDS: tuple[str, ...] = (
    "수주", "공급계약", "계약 체결", "계약체결", "신규", "확대", "흑자",
    "성장", "개선", "인수", "수출", "증가", "상향", "배당", "자사주",
    "신제품", "수혜", "돌파", "기대", "호실적", "사상 최대",
)
_NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "적자", "손실", "하락", "우려", "부담", "감소", "소송", "리콜",
    "결함", "횡령", "배임", "제재", "조사", "부진", "악화", "하향",
    "지연", "철회", "감산", "파업", "급락", "리스크",
)
_DISCLOSURE_HIGH: tuple[str, ...] = (
    "공급계약", "단일판매", "유상증자", "무상증자", "합병", "분할",
    "감자", "영업정지", "회생절차", "상장폐지", "최대주주", "전환사채",
    "신주인수권", "자기주식",
)
_DISCLOSURE_MEDIUM: tuple[str, ...] = (
    "실적", "잠정", "주요사항보고", "투자판단", "조회공시",
)
_NEWS_STRONG: tuple[str, ...] = (
    "수주", "공급계약", "실적", "인수", "합병", "신제품", "리콜", "소송",
)


def _matched(keywords: tuple[str, ...], text: str) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


def _portfolio_impact(sentiment: Sentiment, importance: int) -> str:
    if importance >= 4:
        if sentiment == "positive":
            return "보유 비중이 높다면 단기 모멘텀과 추가 대응 여부를 점검할 만합니다."
        if sentiment == "negative":
            return "보유 비중이 높다면 리스크 노출과 비중 조절 필요성을 점검해야 합니다."
        return "실적·수급에 영향이 큰 사안이라 원문 확인이 우선 필요합니다."
    if importance == 3:
        return "중기 실적 추정 변화 가능성을 추적하는 정도가 적절합니다."
    return "당장 영향은 제한적이며 참고 수준으로 모니터링하면 됩니다."


def _rationale(kind: str, positives: list[str], negatives: list[str]) -> str:
    kind_label = "공시" if kind == "disclosure" else "뉴스"
    matched = positives + negatives
    detected = (
        f" 감지 키워드: {', '.join(matched)}."
        if matched
        else " 뚜렷한 신호 키워드는 없습니다."
    )
    return (
        f"긍정 키워드 {len(positives)}건, 부정 키워드 {len(negatives)}건을 감지했습니다."
        f"{detected}"
        f" 중요도는 {kind_label} 유형과 키워드 강도를 기준으로 산정했습니다."
    )


class RuleBasedAnalyzer:
    """Analyzer protocol implementation using Korean keyword heuristics."""

    model_name: str = MODEL_NAME
    model_version: str = MODEL_VERSION

    def analyze(self, subject: AnalysisSubject) -> AnalysisDraft:
        text = f"{subject.title} {subject.body or ''}"
        positives = _matched(_POSITIVE_KEYWORDS, text)
        negatives = _matched(_NEGATIVE_KEYWORDS, text)

        sentiment = self._sentiment(positives, negatives)
        importance = self._importance(subject.kind, text, positives, negatives)
        body = (subject.body or "").strip()
        summary = body if body else subject.title

        return AnalysisDraft(
            summary=summary,
            sentiment=sentiment,
            importance=importance,
            portfolio_impact=_portfolio_impact(sentiment, importance),
            rationale=_rationale(subject.kind, positives, negatives),
            model_name=self.model_name,
            model_version=self.model_version,
        )

    @staticmethod
    def _sentiment(positives: list[str], negatives: list[str]) -> Sentiment:
        if len(positives) > len(negatives):
            return "positive"
        if len(negatives) > len(positives):
            return "negative"
        return "neutral"

    @staticmethod
    def _importance(
        kind: str, text: str, positives: list[str], negatives: list[str]
    ) -> int:
        if kind == "disclosure":
            if _matched(_DISCLOSURE_HIGH, text):
                return 5
            if _matched(_DISCLOSURE_MEDIUM, text):
                return 4
            return 2
        if _matched(_NEWS_STRONG, text):
            return 4
        if positives or negatives:
            return 3
        return 2
