"""LLM agent for proposing fixes. Stubbed for hackathon-day integration."""

from __future__ import annotations

from dataclasses import dataclass

from flaky_detector.detector import FlakyVerdict


@dataclass(frozen=True)
class FixProposal:
    """A suggested fix for one flaky test."""

    test_id: str
    rationale: str
    suggested_marker: str
    suggested_code_change: str
    confidence: float


def propose_fix(verdict: FlakyVerdict) -> FixProposal:
    """Stub fix proposer. Hackathon day swaps this for a real LLM call.

    The default returns a quarantine-only proposal: mark the test
    with `@pytest.mark.flaky(reruns=2)` and add a TODO comment that
    references the failure pattern. No code change is suggested.

    Real LLM integration on event day will replace the body with
    a Codex call that reads the test source plus failure messages
    and returns a concrete patch suggestion.
    """
    pattern = " ".join(
        "F" if r.is_failure else "P" for r in verdict.evidence
    )
    rationale = (
        f"This test flipped {verdict.flip_count} times across "
        f"{verdict.runs_considered} runs in {verdict.window_days} days "
        f"(pattern: {pattern}). Quarantine first, investigate when stable."
    )
    marker = "@pytest.mark.flaky(reruns=2)"
    todo = (
        "# TODO(flaky-detector): test flagged on "
        f"{verdict.evidence[-1].timestamp:%Y-%m-%d}. "
        "Owner please review failure history."
    )
    return FixProposal(
        test_id=verdict.test_id,
        rationale=rationale,
        suggested_marker=marker,
        suggested_code_change=todo,
        confidence=0.6,
    )
