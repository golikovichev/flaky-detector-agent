"""Tests for FixProposer (LLM live path) using mock chat_call."""

from datetime import datetime
from pathlib import Path

import pytest

from flaky_detector.agent import (
    FixProposal,
    FixProposer,
    is_valid_python,
)
from flaky_detector.detector import detect_flaky
from flaky_detector.parser import TestRun, parse_directory

SAMPLE_DIR = Path(__file__).parent.parent / "data" / "sample_history"


def _first_verdict():
    runs = list(parse_directory(SAMPLE_DIR))
    verdicts = detect_flaky(runs)
    assert verdicts, "sample data must produce at least one flaky verdict"
    return verdicts[0]


# ---------------------------------------------------------------------------
# is_valid_python
# ---------------------------------------------------------------------------

def test_is_valid_python_accepts_clean_snippet():
    assert is_valid_python("# fix: pin random seed before generating test data")


def test_is_valid_python_strips_markdown_fences():
    fenced = "```python\n# fix: rerun under serial workers\n```"
    assert is_valid_python(fenced)


def test_is_valid_python_rejects_syntax_error():
    assert not is_valid_python("def broken( :")


def test_is_valid_python_rejects_empty():
    assert not is_valid_python("")
    assert not is_valid_python("   \n\n  ")


# ---------------------------------------------------------------------------
# Stub path (no API key, no use_llm)
# ---------------------------------------------------------------------------

def test_stub_path_when_use_llm_false():
    verdict = _first_verdict()
    proposer = FixProposer(api_key="dummy", use_llm=False)
    proposal = proposer.propose(verdict)
    assert isinstance(proposal, FixProposal)
    assert proposal.llm_used is False
    assert proposal.tokens_used == 0
    assert "Quarantine first" in proposal.rationale


def test_stub_path_when_no_api_key():
    verdict = _first_verdict()
    proposer = FixProposer(api_key=None, use_llm=True)
    proposal = proposer.propose(verdict)
    assert proposal.llm_used is False


# ---------------------------------------------------------------------------
# Mocked LLM happy path
# ---------------------------------------------------------------------------

def _good_chat_response(*, prompt: str, model: str) -> dict:
    return {
        "text": (
            "The test relies on shared state between runs.\n\n"
            "```python\n# fix: reset session table fixture before each parametrise\n```"
        ),
        "rationale": "The test relies on shared state between runs.",
        "tokens_used": 142,
    }


def test_live_path_returns_proposal_with_valid_code():
    verdict = _first_verdict()
    proposer = FixProposer(
        api_key="test-key",
        use_llm=True,
        chat_call=_good_chat_response,
    )
    proposal = proposer.propose(verdict)
    assert proposal.llm_used is True
    assert proposal.tokens_used == 142
    assert "fix:" in proposal.suggested_code_change
    assert "shared state" in proposal.rationale


# ---------------------------------------------------------------------------
# Mocked LLM retry path
# ---------------------------------------------------------------------------

class _RetryHarness:
    """Returns invalid output until reach_after attempts then a valid one."""

    def __init__(self, reach_after: int):
        self.reach_after = reach_after
        self.calls = 0

    def __call__(self, *, prompt: str, model: str):
        self.calls += 1
        if self.calls <= self.reach_after:
            return {
                "text": "garbage that is not python\n# nothing here",
                "rationale": "garbage that is not python",
                "tokens_used": 50,
            }
        return _good_chat_response(prompt=prompt, model=model)


def test_retry_recovers_after_invalid_output():
    verdict = _first_verdict()
    harness = _RetryHarness(reach_after=2)
    proposer = FixProposer(
        api_key="test-key",
        use_llm=True,
        chat_call=harness,
        max_retries=2,
    )
    proposal = proposer.propose(verdict)
    assert proposal.llm_used is True
    assert harness.calls == 3  # 2 invalid + 1 valid


def test_retry_falls_back_to_stub_when_exhausted():
    verdict = _first_verdict()
    harness = _RetryHarness(reach_after=10)  # never produces valid output
    proposer = FixProposer(
        api_key="test-key",
        use_llm=True,
        chat_call=harness,
        max_retries=2,
    )
    proposal = proposer.propose(verdict)
    assert proposal.llm_used is False
    assert "Quarantine first" in proposal.rationale
    assert harness.calls == 3  # initial + 2 retries


# ---------------------------------------------------------------------------
# Mocked LLM exception path
# ---------------------------------------------------------------------------

def test_exception_in_chat_call_falls_back_to_stub():
    def boom(**kwargs):
        raise RuntimeError("network hiccup")

    verdict = _first_verdict()
    proposer = FixProposer(
        api_key="test-key",
        use_llm=True,
        chat_call=boom,
        max_retries=1,
    )
    proposal = proposer.propose(verdict)
    assert proposal.llm_used is False
