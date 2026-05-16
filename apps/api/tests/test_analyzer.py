"""Unit tests for the analysis service (MVP-04)."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AnalysisResult, Disclosure, NewsItem, Symbol
from app.services.analyzer import analyze_pending


class AnalyzePendingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, autocommit=False
        )
        self.db = self.session_factory()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _seed(self) -> Symbol:
        symbol = Symbol(market="KOSPI", code="005930", name="삼성전자")
        self.db.add(symbol)
        self.db.flush()
        self.db.add(
            NewsItem(
                symbol_id=symbol.id,
                title="삼성전자, 신규 수주 확대로 호실적 기대",
                summary="공급 계약 확대 소식이 전해졌다.",
                original_url="https://x.example/n1",
                canonical_url="https://x.example/n1",
            )
        )
        self.db.add(
            Disclosure(
                symbol_id=symbol.id,
                rcept_no="20240515000001",
                report_name="단일판매ㆍ공급계약 체결",
                original_url="https://dart.example/1",
            )
        )
        self.db.commit()
        return symbol

    def test_analyze_creates_results_in_range(self) -> None:
        self._seed()
        run = analyze_pending(self.db)
        self.assertEqual(run.status, "success")

        results = self.db.execute(select(AnalysisResult)).scalars().all()
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertIn(result.sentiment, {"positive", "negative", "neutral"})
            self.assertGreaterEqual(result.importance, 1)
            self.assertLessEqual(result.importance, 5)
            self.assertTrue(result.summary)
            self.assertTrue(result.portfolio_impact)
            self.assertEqual(result.model_name, "rule-based-analyzer")

    def test_analyze_is_idempotent(self) -> None:
        self._seed()
        analyze_pending(self.db)
        second = analyze_pending(self.db)

        results = self.db.execute(select(AnalysisResult)).scalars().all()
        self.assertEqual(len(results), 2)  # not duplicated to 4
        self.assertEqual(second.status, "success")
        self.assertIn("뉴스 0건", second.message or "")

    def test_analyze_targets_match_source_rows(self) -> None:
        self._seed()
        analyze_pending(self.db)

        news = self.db.execute(select(NewsItem)).scalars().one()
        news_analysis = self.db.execute(
            select(AnalysisResult)
            .where(AnalysisResult.target_type == "news")
            .where(AnalysisResult.target_id == news.id)
        ).scalars().one()
        self.assertEqual(news_analysis.target_id, news.id)

        disclosure = self.db.execute(select(Disclosure)).scalars().one()
        disclosure_analysis = self.db.execute(
            select(AnalysisResult)
            .where(AnalysisResult.target_type == "disclosure")
            .where(AnalysisResult.target_id == disclosure.id)
        ).scalars().one()
        self.assertEqual(disclosure_analysis.target_id, disclosure.id)

    def test_analyze_with_no_data_succeeds(self) -> None:
        run = analyze_pending(self.db)
        self.assertEqual(run.status, "success")
        results = self.db.execute(select(AnalysisResult)).scalars().all()
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
