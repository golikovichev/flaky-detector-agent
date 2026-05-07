"""Agent stub tests."""

from datetime import datetime
from pathlib import Path

from flaky_detector.agent import FixProposal, propose_fix
from flaky_detector.detector import detect_flaky
from flaky_detector.parser import parse_directory

SAMPLE_DIR = Path(__file__).parent.parent / "data" / "sample_history"


def test_stub_returns_quarantine_proposal():
    runs = list(parse_directory(SAMPLE_DIR))
    verdicts = detect_flaky(runs)
    assert verdicts

    proposal = propose_fix(verdicts[0])
    assert isinstance(proposal, FixProposal)
    assert proposal.test_id == verdicts[0].test_id
    assert "pytest.mark.flaky" in proposal.suggested_marker
    assert "TODO" in proposal.suggested_code_change
    assert 0.0 <= proposal.confidence <= 1.0


def test_proposal_carries_pattern_in_rationale():
    runs = list(parse_directory(SAMPLE_DIR))
    verdicts = detect_flaky(runs)
    proposal = propose_fix(verdicts[0])
    assert "pattern" in proposal.rationale.lower()
    # Pattern uses F and P tokens
    assert "P" in proposal.rationale or "F" in proposal.rationale
