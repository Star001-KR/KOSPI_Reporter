"""Tests for the AI-summary persistence layer and lazy endpoint.

These cover the boundary between the Claude-CLI-backed summarizer and the
collection/read paths. Subprocess invocation is stubbed in the CLI-adapter
tests, and the persistence layer uses a fake Summarizer so everything runs
offline and deterministically.
"""

from __future__ import annotations

import subprocess
import unittest
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi import HTTPException

from app.database import Base
from app.models import NewsItem, Symbol
from app.routers.news import generate_ai_summary
from app.services.ai_summarizer import (
    ClaudeCodeSummarizer,
    _NullSummarizer,
    get_summarizer,
)
from app.services.collections import CollectionOptions, run_collection
from app.services.news_summary import (
    ensure_ai_summary,
    summarize_recent_for_symbols,
)

SAMPLE_NEWS = [
    {
        "title": "삼성전자 수주 확대",
        "originallink": "https://news.example/a",
        "link": "https://news.example/a",
        "description": "수주 확대 소식",
        "pubDate": "Mon, 13 May 2024 09:30:00 +0900",
    },
    {
        "title": "삼성전자 신제품 공개",
        "originallink": "https://news.example/b",
        "link": "https://news.example/b",
        "description": "신제품을 공개했다",
        "pubDate": "Mon, 13 May 2024 10:30:00 +0900",
    },
    {
        "title": "삼성전자 실적 전망",
        "originallink": "https://news.example/c",
        "link": "https://news.example/c",
        "description": "분기 실적 전망",
        "pubDate": "Mon, 13 May 2024 11:30:00 +0900",
    },
]


@dataclass
class _FakeSummarizer:
    """Deterministic stand-in for an Anthropic-backed summarizer."""

    model_name: str = "fake-model"
    calls: list[tuple[str, str, str | None]] = field(default_factory=list)
    return_value: str | None = "AI 요약: 핵심만 정리한 결과."

    def summarize(
        self, *, symbol_name: str, title: str, body: str | None
    ) -> str | None:
        self.calls.append((symbol_name, title, body))
        return self.return_value


class _DbTestCase(unittest.TestCase):
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

    def _seed_symbol(self) -> Symbol:
        symbol = Symbol(market="KOSPI", code="005930", name="삼성전자")
        self.db.add(symbol)
        self.db.commit()
        return symbol

    def _seed_news(self, symbol: Symbol, suffix: str, *, ai_summary: str | None = None) -> NewsItem:
        news = NewsItem(
            symbol_id=symbol.id,
            title=f"제목 {suffix}",
            summary=f"원문 요약 {suffix}",
            source="news.example",
            original_url=f"https://news.example/{suffix}",
            canonical_url=f"https://news.example/{suffix}",
            ai_summary=ai_summary,
        )
        self.db.add(news)
        self.db.commit()
        return news


class NullSummarizerTests(unittest.TestCase):
    def test_null_summarizer_returns_none(self) -> None:
        # When the claude CLI is not on PATH, get_summarizer hands back a
        # no-op adapter; calling it must never raise and must produce no
        # summary.
        result = _NullSummarizer().summarize(
            symbol_name="삼성전자", title="x", body=None
        )
        self.assertIsNone(result)


class ClaudeCodeSummarizerTests(unittest.TestCase):
    """Subprocess wrapping around ``claude --print`` is mocked here.

    The real CLI is never invoked in the test suite — we just verify the
    adapter assembles the right command, returns stdout on success, and
    swallows every documented failure mode (non-zero exit, timeout, CLI not
    installed) into a None result.
    """

    def _summarizer(self) -> ClaudeCodeSummarizer:
        return ClaudeCodeSummarizer(
            model="claude-haiku-4-5-20251001",
            cli_path="claude",
            timeout_seconds=5.0,
        )

    def test_passes_prompt_and_returns_stdout(self) -> None:
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return SimpleNamespace(returncode=0, stdout="요약 결과\n", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result = self._summarizer().summarize(
                symbol_name="삼성전자",
                title="실적 발표",
                body="3분기 영업이익 증가",
            )

        self.assertEqual(result, "요약 결과")
        cmd = captured["cmd"]
        # Sanity-check the flags we depend on: print mode, model, no tools,
        # explicit system prompt, no on-disk session.
        self.assertEqual(cmd[0], "claude")
        self.assertIn("--print", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("claude-haiku-4-5-20251001", cmd)
        self.assertIn("--tools", cmd)
        self.assertIn("--no-session-persistence", cmd)
        # The assembled user prompt must travel on stdin, not argv: argv is
        # world-readable via ps//proc, and the prompt carries the article body.
        stdin_text = captured["kwargs"]["input"]
        self.assertIn("삼성전자", stdin_text)
        self.assertIn("실적 발표", stdin_text)
        self.assertNotIn("실적 발표", " ".join(cmd))

    def test_non_zero_exit_returns_none(self) -> None:
        with patch(
            "subprocess.run",
            return_value=SimpleNamespace(
                returncode=1, stdout="", stderr="auth required"
            ),
        ):
            result = self._summarizer().summarize(
                symbol_name="삼성전자", title="x", body=None
            )
        self.assertIsNone(result)

    def test_timeout_returns_none(self) -> None:
        def raise_timeout(*_a, **_kw):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=5.0)

        with patch("subprocess.run", side_effect=raise_timeout):
            result = self._summarizer().summarize(
                symbol_name="삼성전자", title="x", body=None
            )
        self.assertIsNone(result)

    def test_missing_cli_returns_none(self) -> None:
        def raise_missing(*_a, **_kw):
            raise FileNotFoundError(2, "No such file", "claude")

        with patch("subprocess.run", side_effect=raise_missing):
            result = self._summarizer().summarize(
                symbol_name="삼성전자", title="x", body=None
            )
        self.assertIsNone(result)

    def test_empty_stdout_returns_none(self) -> None:
        # Whitespace-only response is treated as no summary so the UI falls
        # back to the rule-based description instead of rendering a blank.
        with patch(
            "subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="   \n", stderr=""),
        ):
            result = self._summarizer().summarize(
                symbol_name="삼성전자", title="x", body=None
            )
        self.assertIsNone(result)


class GetSummarizerTests(unittest.TestCase):
    def test_returns_null_when_cli_missing(self) -> None:
        with patch("app.services.ai_summarizer.shutil.which", return_value=None):
            summarizer = get_summarizer()
        self.assertIsInstance(summarizer, _NullSummarizer)

    def test_returns_claude_summarizer_when_cli_present(self) -> None:
        with patch(
            "app.services.ai_summarizer.shutil.which",
            return_value="/usr/local/bin/claude",
        ):
            summarizer = get_summarizer()
        self.assertIsInstance(summarizer, ClaudeCodeSummarizer)
        self.assertEqual(summarizer._cli_path, "/usr/local/bin/claude")


class EnsureAiSummaryTests(_DbTestCase):
    def test_generates_and_persists_when_missing(self) -> None:
        symbol = self._seed_symbol()
        news = self._seed_news(symbol, "a")

        fake = _FakeSummarizer()
        ensure_ai_summary(self.db, news, summarizer=fake)

        refreshed = self.db.get(NewsItem, news.id)
        self.assertEqual(refreshed.ai_summary, fake.return_value)
        self.assertEqual(refreshed.ai_summary_model, fake.model_name)
        self.assertIsNotNone(refreshed.ai_summary_at)
        self.assertEqual(len(fake.calls), 1)

    def test_no_op_when_already_summarized(self) -> None:
        symbol = self._seed_symbol()
        news = self._seed_news(symbol, "a", ai_summary="이미 있음")

        fake = _FakeSummarizer()
        ensure_ai_summary(self.db, news, summarizer=fake)

        # A cached row must not spend tokens — the fake is never called.
        self.assertEqual(fake.calls, [])
        refreshed = self.db.get(NewsItem, news.id)
        self.assertEqual(refreshed.ai_summary, "이미 있음")

    def test_swallows_failure_and_leaves_row_untouched(self) -> None:
        symbol = self._seed_symbol()
        news = self._seed_news(symbol, "a")

        fake = _FakeSummarizer(return_value=None)  # simulates an LLM failure
        ensure_ai_summary(self.db, news, summarizer=fake)

        refreshed = self.db.get(NewsItem, news.id)
        self.assertIsNone(refreshed.ai_summary)
        self.assertIsNone(refreshed.ai_summary_model)


class SummarizeRecentTests(_DbTestCase):
    def test_only_touches_latest_per_symbol(self) -> None:
        symbol = self._seed_symbol()
        # Three news items; per_symbol=2 should only touch the latest two.
        first = self._seed_news(symbol, "a")
        second = self._seed_news(symbol, "b")
        third = self._seed_news(symbol, "c")

        fake = _FakeSummarizer()
        written = summarize_recent_for_symbols(
            self.db, [symbol.id], per_symbol=2, summarizer=fake
        )

        self.assertEqual(written, 2)
        # The oldest (first inserted) keeps no AI summary because its
        # collected_at predates the other two.
        self.assertEqual(len(fake.calls), 2)
        self.db.refresh(first)
        self.db.refresh(second)
        self.db.refresh(third)
        # collected_at is monotonically increasing in insertion order, so the
        # latest two are second and third — those should be summarized.
        self.assertIsNotNone(third.ai_summary)
        self.assertIsNotNone(second.ai_summary)
        self.assertIsNone(first.ai_summary)

    def test_skips_already_summarized(self) -> None:
        symbol = self._seed_symbol()
        self._seed_news(symbol, "a", ai_summary="이미")
        self._seed_news(symbol, "b")

        fake = _FakeSummarizer()
        written = summarize_recent_for_symbols(
            self.db, [symbol.id], per_symbol=5, summarizer=fake
        )

        self.assertEqual(written, 1)
        # Only the unsummarized row was sent to the summarizer.
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][1], "제목 b")

    def test_no_op_when_per_symbol_zero(self) -> None:
        symbol = self._seed_symbol()
        self._seed_news(symbol, "a")

        fake = _FakeSummarizer()
        written = summarize_recent_for_symbols(
            self.db, [symbol.id], per_symbol=0, summarizer=fake
        )

        self.assertEqual(written, 0)
        self.assertEqual(fake.calls, [])


class LazyEndpointTests(_DbTestCase):
    def test_returns_existing_summary_without_calling_llm(self) -> None:
        symbol = self._seed_symbol()
        news = self._seed_news(symbol, "a", ai_summary="이미 있음")

        # generate_ai_summary uses the configured summarizer via
        # ensure_ai_summary's default lookup — but a cached row must short
        # circuit before that ever runs, so this still works without a key.
        result = generate_ai_summary(news.id, db=self.db)
        self.assertEqual(result.ai_summary, "이미 있음")

    def test_missing_news_returns_404(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            generate_ai_summary(99999, db=self.db)
        self.assertEqual(ctx.exception.status_code, 404)


class CollectionEagerSummaryTests(_DbTestCase):
    def test_collection_runs_eager_summary_after_news(self) -> None:
        self.db.add(Symbol(market="KOSPI", code="005930", name="삼성전자"))
        self.db.commit()

        fake = _FakeSummarizer()
        run = run_collection(
            self.db,
            CollectionOptions(
                include_disclosures=False, include_prices=False, analyze=False
            ),
            naver_client_id="i",
            naver_client_secret="s",
            news_fetcher=lambda _q: SAMPLE_NEWS,
            ai_summarizer=fake,
        )

        self.assertEqual(run.status, "success")
        stored = self.db.execute(select(NewsItem)).scalars().all()
        self.assertEqual(len(stored), len(SAMPLE_NEWS))
        # Default eager_per_symbol = 3 (configurable via env), so all three
        # newly stored articles should have an AI summary attached.
        self.assertTrue(all(item.ai_summary == fake.return_value for item in stored))
        self.assertIn("AI 요약", run.message or "")

    def test_collection_with_null_summarizer_skips_silently(self) -> None:
        self.db.add(Symbol(market="KOSPI", code="005930", name="삼성전자"))
        self.db.commit()

        run = run_collection(
            self.db,
            CollectionOptions(
                include_disclosures=False, include_prices=False, analyze=False
            ),
            naver_client_id="i",
            naver_client_secret="s",
            news_fetcher=lambda _q: SAMPLE_NEWS,
            ai_summarizer=_NullSummarizer(),
        )

        self.assertEqual(run.status, "success")
        stored = self.db.execute(select(NewsItem)).scalars().all()
        # No key → no AI summary, but the run still succeeds and stores news.
        self.assertEqual(len(stored), len(SAMPLE_NEWS))
        self.assertTrue(all(item.ai_summary is None for item in stored))
        self.assertNotIn("AI 요약", run.message or "")


if __name__ == "__main__":
    unittest.main()
