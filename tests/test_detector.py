"""Detector tests on bundled sample data."""

from pathlib import Path

from flaky_detector.detector import detect_flaky
from flaky_detector.parser import parse_directory

SAMPLE_DIR = Path(__file__).parent.parent / "data" / "sample_history"


def test_detector_finds_three_seeded_flakes():
    runs = list(parse_directory(SAMPLE_DIR))
    verdicts = detect_flaky(runs)

    flagged_ids = {v.test_id for v in verdicts}
    expected = {
        "tests.test_login::test_login_concurrent_session",
        "tests.test_checkout::test_checkout_timeout",
        "tests.test_search::test_search_index_warmup",
    }
    assert expected.issubset(flagged_ids), (
        f"expected {expected} subset of {flagged_ids}"
    )


def test_detector_ignores_stable_tests():
    runs = list(parse_directory(SAMPLE_DIR))
    verdicts = detect_flaky(runs)
    flagged_ids = {v.test_id for v in verdicts}

    stable = {
        "tests.test_login::test_login_basic",
        "tests.test_users::test_create_user",
        "tests.test_health::test_status_endpoint",
    }
    assert not (stable & flagged_ids)


def test_detector_ignores_always_failing_tests():
    runs = list(parse_directory(SAMPLE_DIR))
    verdicts = detect_flaky(runs)
    flagged_ids = {v.test_id for v in verdicts}

    # Legacy test fails every run, no flips, should not be flagged
    assert "tests.test_legacy::test_old_api_xml_format" not in flagged_ids


def test_detector_ignores_single_blip():
    runs = list(parse_directory(SAMPLE_DIR))
    verdicts = detect_flaky(runs)
    flagged_ids = {v.test_id for v in verdicts}

    # Billing test has only 1 flip (P P F P P), below 3-flip threshold
    assert "tests.test_billing::test_invoice_generation" not in flagged_ids


def test_verdict_carries_evidence():
    runs = list(parse_directory(SAMPLE_DIR))
    verdicts = detect_flaky(runs)
    assert len(verdicts) >= 1
    v = verdicts[0]
    assert v.flip_count >= 3
    assert v.runs_considered >= 4
    assert len(v.evidence) >= 4
    assert "flips" in v.reason


def test_threshold_configurable():
    runs = list(parse_directory(SAMPLE_DIR))

    strict = detect_flaky(runs, min_flips=5)
    lenient = detect_flaky(runs, min_flips=2)
    assert len(strict) <= len(lenient)
