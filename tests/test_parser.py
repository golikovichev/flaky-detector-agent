"""Parser tests against the bundled sample history."""

from pathlib import Path

from flaky_detector.parser import TestRun, parse_directory, parse_junit_xml

SAMPLE_DIR = Path(__file__).parent.parent / "data" / "sample_history"


def test_parse_single_file():
    files = sorted(SAMPLE_DIR.glob("*.xml"))
    runs = parse_junit_xml(files[0])
    assert len(runs) == 9
    assert all(isinstance(r, TestRun) for r in runs)


def test_parse_directory_yields_all_runs():
    runs = list(parse_directory(SAMPLE_DIR))
    # 5 CI runs * 9 tests = 45 records
    assert len(runs) == 45


def test_outcomes_classified_correctly():
    files = sorted(SAMPLE_DIR.glob("*.xml"))
    runs = parse_junit_xml(files[0])
    by_id = {r.test_id: r for r in runs}

    # Stable always-passing tests
    assert by_id["tests.test_users::test_create_user"].outcome == "passed"
    assert by_id["tests.test_health::test_status_endpoint"].outcome == "passed"

    # Always-failing legacy test
    legacy = by_id["tests.test_legacy::test_old_api_xml_format"]
    assert legacy.outcome == "failed"
    assert "Deprecation" in legacy.failure_message

    # First flake start state (P)
    assert by_id["tests.test_login::test_login_concurrent_session"].outcome == "passed"


def test_run_id_extracted():
    files = sorted(SAMPLE_DIR.glob("*.xml"))
    runs = parse_junit_xml(files[0])
    assert runs[0].run_id == "ci-build-1001"


def test_is_failure_property():
    fake_pass = TestRun("a::b", "s", "passed", 0.0, _now(), "r1")
    fake_fail = TestRun("a::b", "s", "failed", 0.0, _now(), "r1")
    fake_err = TestRun("a::b", "s", "error", 0.0, _now(), "r1")
    fake_skip = TestRun("a::b", "s", "skipped", 0.0, _now(), "r1")
    assert not fake_pass.is_failure
    assert fake_fail.is_failure
    assert fake_err.is_failure
    assert not fake_skip.is_failure


def _now():
    from datetime import datetime

    return datetime(2026, 5, 7)
