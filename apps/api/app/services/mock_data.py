from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from kospi_core import AnalysisSubject, RuleBasedAnalyzer

from app.models import (
    AnalysisResult,
    CollectionRun,
    Disclosure,
    NewsItem,
    Symbol,
    utcnow,
)

_analyzer = RuleBasedAnalyzer()


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


def _store_analysis(
    db: Session, target_type: str, target_id: int, subject: AnalysisSubject
) -> None:
    if _analysis_exists(db, target_type, target_id):
        return
    draft = _analyzer.analyze(subject)
    db.add(
        AnalysisResult(
            target_type=target_type,
            target_id=target_id,
            summary=draft.summary,
            sentiment=draft.sentiment,
            importance=draft.importance,
            portfolio_impact=draft.portfolio_impact,
            rationale=draft.rationale,
            model_name=draft.model_name,
            model_version=draft.model_version,
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
        },
        {
            "title": f"{symbol.name} 관련 원가 부담 우려 재점검",
            "summary": "시장에서는 비용 상승과 마진 방어력이 주요 변수로 거론됐습니다.",
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

        _store_analysis(
            db,
            "news",
            item.id,
            AnalysisSubject(
                kind="news",
                symbol_name=symbol.name,
                title=template["title"],
                body=template["summary"],
            ),
        )

    disclosure_templates = [
        {
            "report_name": f"{symbol.name} 단일판매ㆍ공급계약 체결",
            "summary": "공급 계약 체결 공시로 매출 가시성에 영향을 줄 수 있습니다.",
        },
        {
            "report_name": f"{symbol.name} 임원ㆍ주요주주 특정증권등 소유상황보고서",
            "summary": "경영진ㆍ주요주주의 지분 변동 여부를 확인하는 공시입니다.",
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

        _store_analysis(
            db,
            "disclosure",
            item.id,
            AnalysisSubject(
                kind="disclosure",
                symbol_name=symbol.name,
                title=template["report_name"],
                body=template["summary"],
            ),
        )

    run.status = "success"
    run.finished_at = utcnow()
    run.news_inserted = news_inserted
    run.disclosures_inserted = disclosures_inserted
    return news_inserted, disclosures_inserted
