from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisResult,
    CollectionRun,
    Disclosure,
    NewsItem,
    Symbol,
    utcnow,
)


def _analysis_exists(db: Session, target_type: str, target_id: int) -> bool:
    return (
        db.execute(
            select(AnalysisResult.id)
            .where(AnalysisResult.target_type == target_type)
            .where(AnalysisResult.target_id == target_id)
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _add_analysis(
    db: Session,
    *,
    target_type: str,
    target_id: int,
    summary: str,
    sentiment: str,
    importance: int,
    portfolio_impact: str,
    rationale: str,
) -> None:
    if _analysis_exists(db, target_type, target_id):
        return
    db.add(
        AnalysisResult(
            target_type=target_type,
            target_id=target_id,
            summary=summary,
            sentiment=sentiment,
            importance=importance,
            portfolio_impact=portfolio_impact,
            rationale=rationale,
            model_name="mock-analyzer",
            model_version="0.1",
        )
    )


def ensure_mock_activity(db: Session, symbol: Symbol) -> tuple[int, int]:
    now = utcnow()
    run = CollectionRun(
        run_type="mock",
        status="running",
        started_at=now,
        symbols_processed=1,
        message="Generated local sample activity for UI verification.",
    )
    db.add(run)

    news_templates = [
        {
            "title": f"{symbol.name}, 신규 수주 기대감에 투자자 관심 확대",
            "summary": "최근 사업 업데이트와 업황 개선 기대가 함께 언급됐습니다.",
            "sentiment": "positive",
            "importance": 4,
            "impact": "보유 비중이 높다면 단기 변동성 확대 여부를 확인할 필요가 있습니다.",
            "rationale": "실적 기대와 수급 이슈가 동시에 언급된 항목입니다.",
        },
        {
            "title": f"{symbol.name} 관련 원가 부담 우려 재점검",
            "summary": "시장에서는 비용 상승과 마진 방어력이 주요 변수로 거론됐습니다.",
            "sentiment": "neutral",
            "importance": 3,
            "impact": "중기 실적 추정 변화 가능성을 추적하는 정도가 적절합니다.",
            "rationale": "방향성은 불확실하지만 반복 관찰할 만한 이슈입니다.",
        },
    ]

    news_inserted = 0
    for index, template in enumerate(news_templates, start=1):
        url = f"mock://news/{symbol.market}/{symbol.code}/{index}"
        original_url = (
            f"https://example.com/mock/news/{symbol.market}/{symbol.code}/{index}"
        )
        existing = db.execute(
            select(NewsItem).where(NewsItem.canonical_url == url)
        ).scalar_one_or_none()
        if existing is None:
            item = NewsItem(
                symbol_id=symbol.id,
                title=template["title"],
                summary=template["summary"],
                source="Local Mock News",
                original_url=original_url,
                canonical_url=url,
                published_at=now - timedelta(hours=index * 3),
                collected_at=now - timedelta(minutes=index * 7),
                raw_payload={"mock": True, "template": index},
            )
            db.add(item)
            db.flush()
            news_inserted += 1
        else:
            item = existing

        _add_analysis(
            db,
            target_type="news",
            target_id=item.id,
            summary=template["summary"],
            sentiment=template["sentiment"],
            importance=template["importance"],
            portfolio_impact=template["impact"],
            rationale=template["rationale"],
        )

    disclosure_templates = [
        {
            "report_name": f"{symbol.name} 단일판매ㆍ공급계약 체결",
            "sentiment": "positive",
            "importance": 5,
            "impact": "매출 가시성에 영향을 줄 수 있어 원문 계약 규모 확인이 필요합니다.",
        },
        {
            "report_name": f"{symbol.name} 임원ㆍ주요주주 특정증권등 소유상황보고서",
            "sentiment": "neutral",
            "importance": 2,
            "impact": "경영진 지분 변동 여부를 확인하는 참고 항목입니다.",
        },
    ]

    disclosures_inserted = 0
    for index, template in enumerate(disclosure_templates, start=1):
        rcept_no = f"MOCK{symbol.market}{symbol.code}{index:02d}"
        existing = db.execute(
            select(Disclosure).where(Disclosure.rcept_no == rcept_no)
        ).scalar_one_or_none()
        if existing is None:
            item = Disclosure(
                symbol_id=symbol.id,
                rcept_no=rcept_no,
                report_name=template["report_name"],
                corp_code=None,
                corp_name=symbol.name,
                submitted_at=now - timedelta(days=index),
                original_url=(
                    f"https://example.com/mock/disclosure/"
                    f"{symbol.market}/{symbol.code}/{index}"
                ),
                collected_at=now - timedelta(minutes=index * 11),
                raw_payload={"mock": True, "template": index},
            )
            db.add(item)
            db.flush()
            disclosures_inserted += 1
        else:
            item = existing

        _add_analysis(
            db,
            target_type="disclosure",
            target_id=item.id,
            summary=f"{template['report_name']} 항목이 수집되었습니다.",
            sentiment=template["sentiment"],
            importance=template["importance"],
            portfolio_impact=template["impact"],
            rationale="공시 유형과 보유 종목 관련성을 기준으로 임시 평가했습니다.",
        )

    run.status = "success"
    run.finished_at = utcnow()
    run.news_inserted = news_inserted
    run.disclosures_inserted = disclosures_inserted
    return news_inserted, disclosures_inserted
