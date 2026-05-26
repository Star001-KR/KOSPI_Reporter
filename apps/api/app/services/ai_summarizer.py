"""LLM-backed news summarizer.

Generates a short Korean summary for a collected news item using Anthropic's
Claude Haiku model. Designed to be safe to call even when an API key is not
configured: every public entrypoint returns ``None`` instead of raising, so a
missing key, network blip, or rate-limit hiccup never breaks collection or the
user-facing fallback to ``NewsItem.summary``.

Persistence lives in :mod:`app.services.news_summary` — this module is purely
the prompt-to-text adapter so callers can swap in another LLM by implementing
:class:`Summarizer`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)

# Trim raw bodies before sending — Naver descriptions are short, but a defensive
# cap keeps a future longer source from blowing up token usage.
_MAX_INPUT_CHARS = 1200
_MAX_OUTPUT_TOKENS = 520

_SYSTEM_PROMPT = (
    "당신은 한국 주식 투자자를 위한 뉴스 요약가입니다. "
    "주어진 기사 제목과 본문 일부를 읽고 투자 판단에 도움이 되는 핵심을 "
    "한국어 4~5줄 분량으로 정리하세요. 핵심 사실은 모두 담되 불필요하게 "
    "길어지지 않게 하고, 추측이나 의견은 넣지 말고 원문에 적힌 사실만 "
    "정리합니다. 따옴표나 마크다운은 사용하지 않습니다."
)


class Summarizer(Protocol):
    """Pluggable LLM adapter — returns the summary text or ``None`` to skip."""

    model_name: str

    def summarize(
        self, *, symbol_name: str, title: str, body: str | None
    ) -> str | None: ...


@dataclass
class _NullSummarizer:
    """Returned when no API key is configured — every call is a no-op."""

    model_name: str = "disabled"

    def summarize(
        self, *, symbol_name: str, title: str, body: str | None
    ) -> str | None:
        return None


class AnthropicSummarizer:
    """Summarizer backed by the Anthropic Messages API.

    Errors are logged and swallowed so a failing request never propagates up
    into the collection pipeline or an API handler.
    """

    def __init__(self, *, api_key: str, model: str) -> None:
        # Imported lazily so the rest of the app still loads when the
        # ``anthropic`` package is not installed (tests, CI without the dep).
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self.model_name = model

    def summarize(
        self, *, symbol_name: str, title: str, body: str | None
    ) -> str | None:
        prompt = _build_prompt(symbol_name=symbol_name, title=title, body=body)
        try:
            response = self._client.messages.create(
                model=self.model_name,
                max_tokens=_MAX_OUTPUT_TOKENS,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception:  # broad: any LLM failure must fall back to None
            logger.warning(
                "AI summary failed for symbol=%s title=%r",
                symbol_name,
                title[:80],
                exc_info=True,
            )
            return None
        return _extract_text(response)


def _build_prompt(*, symbol_name: str, title: str, body: str | None) -> str:
    body_text = (body or "").strip()[:_MAX_INPUT_CHARS]
    return (
        f"종목: {symbol_name}\n"
        f"제목: {title}\n"
        f"본문: {body_text or '(본문 없음)'}\n\n"
        "위 기사를 한국어 4~5줄 분량으로 요약해 주세요. "
        "핵심 사실은 모두 담되 너무 길게 늘이지 마세요."
    )


def _extract_text(response: object) -> str | None:
    """Pull the first text block out of an Anthropic Messages response."""
    content = getattr(response, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def get_summarizer() -> Summarizer:
    """Build a summarizer from runtime settings.

    Returns a :class:`_NullSummarizer` when ``ANTHROPIC_API_KEY`` is unset so
    callers can stay key-agnostic — the AI-summary feature simply becomes a
    no-op and the existing rule-based fallback handles rendering.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return _NullSummarizer()
    try:
        return AnthropicSummarizer(
            api_key=settings.anthropic_api_key,
            model=settings.ai_summary_model,
        )
    except Exception:  # missing anthropic package, bad key shape, etc.
        logger.warning("Failed to initialise AnthropicSummarizer", exc_info=True)
        return _NullSummarizer()
