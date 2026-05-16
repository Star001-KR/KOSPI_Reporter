"""Unit tests for the Naver News Search collector (MVP-03)."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import NewsItem, Symbol
from app.services.naver_news import (
    NaverNewsError,
    clean_naver_text,
    collect_news,
    parse_news,
    store_news,
)

SAMPLE_NEWS_ITEMS = [
    {
        "title": "<b>삼성전자</b>, 2분기 실적 &quot;호조&quot; 전망",
        "originallink": "https://www.example-news.co.kr/article/1",
        "link": "https://n.news.naver.com/article/001/0001",
        "description": "<b>삼성전자</b>가 반도체 업황 개선에 힘입어 호실적을 낼 전망이다.",
        "pubDate": "Mon, 13 May 2024 09:30:00 +0900",
    },
    {
        "title": "삼성전자 신제품 공개",
        "originallink": "https://example-biz.com/n/2",
        "link": "https://example-biz.com/n/2",
        "description": "신제품 설명",
        "pubDate": "Sun, 12 May 2024 18:00:00 +0900",
    },
]


class NaverTextCleanupTests(unittest.TestCase):
    def test_clean_strips_tags_and_entities(self) -> None:
        cleaned = clean_naver_text('<b>삼성전자</b>, 실적 &quot;호조&quot; &amp; 전망')
        self.assertEqual(cleaned, '삼성전자, 실적 "호조" & 전망')

    def test_clean_collapses_whitespace(self) -> None:
        self.assertEqual(clean_naver_text("줄1\n  줄2   줄3"), "줄1 줄2 줄3")


class NewsParsingTests(unittest.TestCase):
    def test_parse_news(self) -> None:
        drafts = parse_news(SAMPLE_NEWS_ITEMS)
        self.assertEqual(len(drafts), 2)

        first = drafts[0]
        self.assertEqual(first.title, '삼성전자, 2분기 실적 "호조" 전망')
        self.assertEqual(
            first.canonical_url, "https://www.example-news.co.kr/article/1"
        )
        self.assertEqual(
            first.original_url, "https://n.news.naver.com/article/001/0001"
        )
        self.assertEqual(first.source, "example-news.co.kr")
        self.assertIsNotNone(first.published_at)
        self.assertEqual(first.published_at.year, 2024)  # type: ignore[union-attr]
        self.assertNotIn("<b>", first.summary or "")

    def test_parse_skips_rows_without_url_or_title(self) -> None:
        rows = [
            {"title": "제목만", "originallink": "", "link": ""},
            {"title": "", "link": "https://x.example/1"},
            {"title": "정상 기사", "link": "https://x.example/2"},
        ]
        drafts = parse_news(rows)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].canonical_url, "https://x.example/2")


class NewsCollectionTests(unittest.TestCase):
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

    def _seed_symbol(self, *, code: str = "005930", name: str = "삼성전자") -> Symbol:
        symbol = Symbol(market="KOSPI", code=code, name=name)
        self.db.add(symbol)
        self.db.commit()
        return symbol

    def test_store_news_dedupes(self) -> None:
        symbol = self._seed_symbol()
        drafts = parse_news(SAMPLE_NEWS_ITEMS)
        self.assertEqual(store_news(self.db, symbol.id, drafts), 2)
        self.db.commit()

        # re-collecting the same articles inserts nothing new
        self.assertEqual(store_news(self.db, symbol.id, drafts), 0)
        self.db.commit()

        rows = self.db.execute(select(NewsItem)).scalars().all()
        self.assertEqual(len(rows), 2)

    def test_collect_news_success(self) -> None:
        symbol = self._seed_symbol()
        captured: dict[str, str] = {}

        def fake_fetcher(query: str) -> list[dict]:
            captured["query"] = query
            return SAMPLE_NEWS_ITEMS

        run = collect_news(
            self.db, client_id="id", client_secret="secret", fetcher=fake_fetcher
        )
        self.assertEqual(run.status, "success")
        self.assertEqual(run.symbols_processed, 1)
        self.assertEqual(run.news_inserted, 2)
        self.assertEqual(captured["query"], "삼성전자")

        stored = (
            self.db.execute(
                select(NewsItem).where(NewsItem.symbol_id == symbol.id)
            )
            .scalars()
            .all()
        )
        self.assertEqual(len(stored), 2)

    def test_collect_news_is_idempotent(self) -> None:
        self._seed_symbol()

        def fetcher(_query: str) -> list[dict]:
            return SAMPLE_NEWS_ITEMS

        first = collect_news(self.db, client_id="i", client_secret="s", fetcher=fetcher)
        second = collect_news(
            self.db, client_id="i", client_secret="s", fetcher=fetcher
        )
        self.assertEqual(first.news_inserted, 2)
        self.assertEqual(second.news_inserted, 0)
        self.assertEqual(second.status, "success")

    def test_collect_news_request_failure_recorded(self) -> None:
        self._seed_symbol()

        def failing_fetcher(_query: str) -> list[dict]:
            raise NaverNewsError("Naver API 호출 실패 (테스트)")

        run = collect_news(
            self.db, client_id="i", client_secret="s", fetcher=failing_fetcher
        )
        self.assertEqual(run.status, "failed")
        self.assertIn("호출 실패", run.message or "")

    def test_collect_news_without_keys_fails(self) -> None:
        self._seed_symbol()
        run = collect_news(self.db, client_id="", client_secret="")
        self.assertEqual(run.status, "failed")
        self.assertIn("NAVER_CLIENT", run.message or "")


if __name__ == "__main__":
    unittest.main()
