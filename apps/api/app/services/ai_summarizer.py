"""LLM-backed news summarizer.

Generates a short Korean summary for a collected news item by shelling out to
the locally installed Claude Code CLI in ``--print`` mode. Using the CLI means
the feature runs against the user's Claude subscription (OAuth) instead of a
separate Anthropic API key, with one trade-off: the API server must run on the
machine where ``claude login`` has been completed.

Every public entrypoint returns ``None`` instead of raising, so a missing CLI,
expired login, network blip, or timeout never breaks collection or the
user-facing fallback to ``NewsItem.summary``.

Persistence lives in :mod:`app.services.news_summary` — this module is purely
the prompt-to-text adapter so callers can swap in another LLM by implementing
:class:`Summarizer`.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)

# Trim raw bodies before sending — Naver descriptions are short, but a defensive
# cap keeps a future longer source from blowing up the prompt.
_MAX_INPUT_CHARS = 1200

# Default upper bound on a single CLI call. Generous enough for Haiku's first
# token + a 4-5 line response over OAuth; tightened in tests via the timeout
# constructor argument.
_DEFAULT_TIMEOUT_SECONDS = 90.0

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
    """Returned when no usable backend is found — every call is a no-op."""

    model_name: str = "disabled"

    def summarize(
        self, *, symbol_name: str, title: str, body: str | None
    ) -> str | None:
        return None


class ClaudeCodeSummarizer:
    """Summarizer that pipes prompts through the local ``claude`` CLI.

    Runs ``claude --print`` as a subprocess with tools disabled and a custom
    system prompt, so each call is a one-shot text generation against the
    user's logged-in Claude subscription. Errors and non-zero exits are
    logged and swallowed so the caller falls back to the rule-based summary.
    """

    def __init__(
        self,
        *,
        model: str,
        cli_path: str = "claude",
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.model_name = model
        self._cli_path = cli_path
        self._timeout = timeout_seconds

    def summarize(
        self, *, symbol_name: str, title: str, body: str | None
    ) -> str | None:
        prompt = _build_prompt(symbol_name=symbol_name, title=title, body=body)
        try:
            result = subprocess.run(
                [
                    self._cli_path,
                    "--print",
                    "--model", self.model_name,
                    "--tools", "",
                    "--output-format", "text",
                    "--no-session-persistence",
                    "--system-prompt", _SYSTEM_PROMPT,
                    prompt,
                ],
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            logger.warning(
                "claude CLI summary failed for symbol=%s title=%r",
                symbol_name,
                title[:80],
                exc_info=True,
            )
            return None
        if result.returncode != 0:
            logger.warning(
                "claude CLI exited %s for symbol=%s: %s",
                result.returncode,
                symbol_name,
                (result.stderr or "")[:200].strip(),
            )
            return None
        text = (result.stdout or "").strip()
        return text or None


def _build_prompt(*, symbol_name: str, title: str, body: str | None) -> str:
    body_text = (body or "").strip()[:_MAX_INPUT_CHARS]
    return (
        f"종목: {symbol_name}\n"
        f"제목: {title}\n"
        f"본문: {body_text or '(본문 없음)'}\n\n"
        "위 기사를 한국어 4~5줄 분량으로 요약해 주세요. "
        "핵심 사실은 모두 담되 너무 길게 늘이지 마세요."
    )


def get_summarizer() -> Summarizer:
    """Build a summarizer from runtime settings.

    Returns a :class:`_NullSummarizer` when the ``claude`` CLI is not on PATH,
    so the feature degrades to a no-op (rule-based fallback) on a host where
    Claude Code is not installed. The CLI itself handles authentication; an
    expired/missing login surfaces later as a non-zero exit and is logged.
    """
    settings = get_settings()
    cli_path = shutil.which(settings.claude_cli_path) or shutil.which("claude")
    if cli_path is None:
        return _NullSummarizer()
    try:
        return ClaudeCodeSummarizer(
            model=settings.ai_summary_model,
            cli_path=cli_path,
        )
    except Exception:
        logger.warning("Failed to initialise ClaudeCodeSummarizer", exc_info=True)
        return _NullSummarizer()
