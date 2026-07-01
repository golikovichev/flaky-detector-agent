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


_MIXED_TZ_XML = """<testsuites>
  <testsuite name="s" timestamp="2026-01-01T00:00:00Z" run-id="r1">
    <testcase classname="pkg.T" name="test_x" time="1"><failure message="boom"/></testcase>
  </testsuite>
  <testsuite name="s" timestamp="2026-01-02T00:00:00" run-id="r2">
    <testcase classname="pkg.T" name="test_x" time="1"/>
  </testsuite>
  <testsuite name="s" run-id="r3">
    <testcase classname="pkg.T" name="test_x" time="1"><failure message="boom"/></testcase>
  </testsuite>
</testsuites>"""


def test_parsed_timestamps_are_all_timezone_aware(tmp_path):
    """A file mixing a Z suffix, a bare (offset-less) stamp, and a missing stamp
    must yield timestamps of one consistent awareness. Otherwise sorting or
    subtracting them downstream raises 'can't compare offset-naive and
    offset-aware datetimes'."""
    xml_file = tmp_path / "mixed_tz.xml"
    xml_file.write_text(_MIXED_TZ_XML, encoding="utf-8")

    runs = parse_junit_xml(xml_file)

    assert len(runs) == 3
    assert all(r.timestamp.tzinfo is not None for r in runs)


def test_mixed_timezone_history_does_not_crash_detector(tmp_path):
    """The realistic downstream path: detect_flaky must sort mixed-source runs
    without a TypeError."""
    from flaky_detector.detector import detect_flaky

    xml_file = tmp_path / "mixed_tz.xml"
    xml_file.write_text(_MIXED_TZ_XML, encoding="utf-8")
    runs = parse_junit_xml(xml_file)

    # Just needs to run without raising; verdict content is not the point here.
    detect_flaky(runs, min_flips=1)


def _now():
    from datetime import datetime

    return datetime(2026, 5, 7)
