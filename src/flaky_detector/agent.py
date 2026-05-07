"""LLM agent for proposing fixes for flaky tests.

Two modes:
  1. STUB (default if no API key) - returns quarantine-only proposal, no LLM call.
  2. LIVE - calls OpenAI / compatible chat completion endpoint with the test
     source plus failure history, validates the response with `ast.parse`,
     retries on invalid output up to a configurable limit.

Mode is selected by OPENAI_API_KEY environment variable plus an optional
`use_llm` flag on the FixProposer. Demos and tests stay deterministic when no
API key is present.
"""

from __future__ import annotations

import ast
import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from flaky_detector.detector import FlakyVerdict


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FixProposal:
    """A suggested fix for one flaky test."""

    test_id: str
    rationale: str
    suggested_marker: str
    suggested_code_change: str
    confidence: float
    llm_used: bool = False
    tokens_used: int = 0


# ---------------------------------------------------------------------------
# Stub path (deterministic fallback, no network)
# ---------------------------------------------------------------------------

def _stub_proposal(verdict: FlakyVerdict) -> FixProposal:
    """Quarantine-only proposal. Used when no LLM is available."""
    pattern = " ".join("F" if r.is_failure else "P" for r in verdict.evidence)
    rationale = (
        f"This test flipped {verdict.flip_count} times across "
        f"{verdict.runs_considered} runs in {verdict.window_days} days "
        f"(pattern: {pattern}). Quarantine first, investigate when stable."
    )
    todo = (
        "# TODO(flaky-detector): test flagged on "
        f"{verdict.evidence[-1].timestamp:%Y-%m-%d}. "
        "Owner please review failure history."
    )
    return FixProposal(
        test_id=verdict.test_id,
        rationale=rationale,
        suggested_marker="@pytest.mark.flaky(reruns=2)",
        suggested_code_change=todo,
        confidence=0.6,
        llm_used=False,
    )


# ---------------------------------------------------------------------------
# AST validation
# ---------------------------------------------------------------------------

def is_valid_python(code: str) -> bool:
    """Return True if the snippet parses as a Python module.

    The LLM may return code wrapped in markdown fences. We strip the most
    common fence shapes before parsing.
    """
    if not code or not code.strip():
        return False
    cleaned = _strip_markdown_fences(code).strip()
    try:
        ast.parse(cleaned)
        return True
    except SyntaxError:
        return False


def _strip_markdown_fences(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    if lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live LLM path (OpenAI-compatible call with retry)
# ---------------------------------------------------------------------------

DEFAULT_PROMPT_TEMPLATE = """You are a senior QA engineer reviewing a flaky pytest test.

Test ID: {test_id}
Outcome history (oldest to newest): {pattern}
Number of unrelated outcome flips: {flip_count}
Window observed: {window_days} days
Most common failure message: {failure_message}

Task:
1. Suggest a single concrete fix direction in 1-2 sentences.
2. Then output a single Python comment line starting with "# fix:" that an
   engineer could paste above the test as a TODO. Output ONLY the comment line
   on its second non-empty line. Do not output the test code itself.
3. Wrap the comment line in triple backticks.

Be terse. No preamble. No closing remarks."""


@dataclass
class FixProposer:
    """Build FixProposals. Calls LLM if api_key + use_llm, else returns stub."""

    api_key: Optional[str] = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY"))
    model: str = "gpt-4o-mini"
    use_llm: bool = True
    max_retries: int = 2
    timeout_seconds: float = 20.0
    # Injected callable lets tests mock the network layer cleanly.
    chat_call: Optional[Callable[..., dict]] = None

    def propose(self, verdict: FlakyVerdict) -> FixProposal:
        if not (self.use_llm and self.api_key):
            logger.info("LLM disabled or no API key, returning stub proposal")
            return _stub_proposal(verdict)

        for attempt in range(self.max_retries + 1):
            try:
                response = self._call_chat(verdict)
                code = self._extract_comment_line(response["text"])
                if code and is_valid_python(code):
                    return FixProposal(
                        test_id=verdict.test_id,
                        rationale=response["rationale"],
                        suggested_marker="@pytest.mark.flaky(reruns=2)",
                        suggested_code_change=code,
                        confidence=0.75,
                        llm_used=True,
                        tokens_used=response.get("tokens_used", 0),
                    )
                logger.warning(
                    "LLM returned invalid Python on attempt %d, retrying",
                    attempt + 1,
                )
            except Exception as exc:
                logger.warning("LLM call failed on attempt %d: %s", attempt + 1, exc)

        logger.warning("LLM exhausted retries, falling back to stub")
        return _stub_proposal(verdict)

    def _call_chat(self, verdict: FlakyVerdict) -> dict:
        prompt = DEFAULT_PROMPT_TEMPLATE.format(
            test_id=verdict.test_id,
            pattern=" ".join("F" if r.is_failure else "P" for r in verdict.evidence),
            flip_count=verdict.flip_count,
            window_days=verdict.window_days,
            failure_message=_pick_failure_message(verdict) or "(none captured)",
        )
        if self.chat_call is not None:
            return self.chat_call(prompt=prompt, model=self.model)
        return _default_openai_call(
            prompt=prompt,
            api_key=self.api_key,
            model=self.model,
            timeout=self.timeout_seconds,
        )

    @staticmethod
    def _extract_comment_line(text: str) -> str:
        """Find the first line starting with '# fix:' inside the response.

        The prompt asks the model to wrap a comment line in triple backticks.
        We strip fences then look for the first '# fix:' line.
        """
        cleaned = _strip_markdown_fences(text)
        for line in cleaned.splitlines():
            stripped = line.strip()
            if stripped.startswith("# fix:"):
                return stripped
        return ""


def _pick_failure_message(verdict: FlakyVerdict) -> str:
    for run in reversed(verdict.evidence):
        if run.is_failure and run.failure_message:
            return run.failure_message
    return ""


def _default_openai_call(*, prompt: str, api_key: str, model: str, timeout: float) -> dict:
    """Real OpenAI Chat Completions call. Lazy import so the package is optional."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai package not installed. Install with `pip install openai` or pass chat_call=mock."
        ) from exc

    client = OpenAI(api_key=api_key, timeout=timeout)
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=200,
    )
    text = completion.choices[0].message.content or ""
    rationale_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    tokens = getattr(completion.usage, "total_tokens", 0) if completion.usage else 0
    return {"text": text, "rationale": rationale_line, "tokens_used": tokens}


# ---------------------------------------------------------------------------
# Convenience function (keeps backward-compatible API from skeleton commit)
# ---------------------------------------------------------------------------

def propose_fix(verdict: FlakyVerdict, *, proposer: Optional[FixProposer] = None) -> FixProposal:
    """Backward-compatible single-call helper. Stub by default."""
    if proposer is None:
        proposer = FixProposer(use_llm=False)
    return proposer.propose(verdict)
