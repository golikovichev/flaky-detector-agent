"""Tests for the quarantine PR workflow.

All shell calls are dependency-injected so this test module never touches
git, gh, or the network. The mock runner records every command and lets
the test decide what each call returns.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest

from flaky_detector.detector import FlakyVerdict
from flaky_detector.parser import TestRun
from flaky_detector.quarantine import (
    MARKER_LINE,
    PYTEST_IMPORT_LINE,
    MarkerEdit,
    apply_quarantine_marker,
    build_branch_name,
    create_quarantine_pr,
    format_pr_body,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verdict(test_id: str, pattern: str = "FPFPF") -> FlakyVerdict:
    """Build a FlakyVerdict with a synthetic evidence stream from a P/F pattern."""
    evidence = [
        TestRun(
            test_id=test_id,
            suite="demo",
            outcome="failed" if ch == "F" else "passed",
            duration=0.1,
            timestamp=datetime(2026, 5, 1 + i, 12, 0, 0),
            run_id=f"run-{i}",
            failure_message="boom" if ch == "F" else "",
        )
        for i, ch in enumerate(pattern)
    ]
    return FlakyVerdict(
        test_id=test_id,
        flip_count=4,
        window_days=14,
        runs_considered=len(evidence),
        evidence=evidence,
    )


@dataclass
class RecordedCall:
    args: list[str]
    cwd: Path


@dataclass
class RecordingRunner:
    calls: list[RecordedCall] = field(default_factory=list)
    pr_url: str = "https://github.com/example/repo/pull/42"

    def __call__(self, args, cwd):  # type: ignore[no-untyped-def]
        self.calls.append(RecordedCall(args=list(args), cwd=Path(cwd)))
        stdout = self.pr_url if args and args[0] == "gh" else ""
        return subprocess.CompletedProcess(
            args=list(args), returncode=0, stdout=stdout, stderr=""
        )


# ---------------------------------------------------------------------------
# Branch naming
# ---------------------------------------------------------------------------


def test_branch_name_includes_timestamp():
    fixed = datetime(2026, 5, 11, 3, 45, 1)
    assert build_branch_name(fixed) == "flaky-quarantine-20260511T034501"


def test_branch_name_default_uses_now():
    name = build_branch_name()
    assert name.startswith("flaky-quarantine-")
    assert len(name.split("-")[-1]) == 15  # YYYYMMDDTHHMMSS


# ---------------------------------------------------------------------------
# Marker application
# ---------------------------------------------------------------------------


def _write_test_file(tests_root: Path, module: str, body: str) -> Path:
    tests_root.mkdir(parents=True, exist_ok=True)
    path = tests_root / f"{module}.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_apply_marker_inserts_decorator(tmp_path):
    tests_root = tmp_path / "tests"
    _write_test_file(
        tests_root,
        "test_login",
        "def test_login_concurrent_session():\n    assert True\n",
    )
    result = apply_quarantine_marker(
        "tests.test_login::test_login_concurrent_session", tests_root
    )
    assert result.status == "applied"
    written = (tests_root / "test_login.py").read_text(encoding="utf-8")
    assert MARKER_LINE in written
    assert PYTEST_IMPORT_LINE in written
    # Marker sits directly above the function
    lines = written.splitlines()
    def_index = next(i for i, ln in enumerate(lines) if ln.startswith("def test_login"))
    assert lines[def_index - 1] == MARKER_LINE


def test_apply_marker_idempotent(tmp_path):
    tests_root = tmp_path / "tests"
    body = (
        "import pytest\n\n"
        "@pytest.mark.flaky(reruns=2)\n"
        "def test_already_marked():\n    assert True\n"
    )
    _write_test_file(tests_root, "test_x", body)
    result = apply_quarantine_marker("tests.test_x::test_already_marked", tests_root)
    assert result.status == "already-marked"
    # File unchanged
    assert (tests_root / "test_x.py").read_text(encoding="utf-8") == body


def test_apply_marker_file_missing(tmp_path):
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    result = apply_quarantine_marker("tests.test_missing::test_x", tests_root)
    assert result.status == "file-missing"
    assert result.file_path is None


def test_apply_marker_function_missing(tmp_path):
    tests_root = tmp_path / "tests"
    _write_test_file(tests_root, "test_y", "def test_other():\n    pass\n")
    result = apply_quarantine_marker("tests.test_y::test_not_there", tests_root)
    assert result.status == "function-missing"
    assert result.file_path is not None


def test_apply_marker_skips_test_root_prefix(tmp_path):
    # When tests_root is named 'tests' and the test_id is 'tests.test_x::...',
    # we should not look for tests/tests/test_x.py
    tests_root = tmp_path / "tests"
    _write_test_file(tests_root, "test_z", "def test_a():\n    pass\n")
    result = apply_quarantine_marker("tests.test_z::test_a", tests_root)
    assert result.status == "applied"


def test_apply_marker_preserves_existing_imports(tmp_path):
    tests_root = tmp_path / "tests"
    body = "import os\nimport sys\n\ndef test_one():\n    assert True\n"
    _write_test_file(tests_root, "test_imp", body)
    apply_quarantine_marker("tests.test_imp::test_one", tests_root)
    written = (tests_root / "test_imp.py").read_text(encoding="utf-8")
    # pytest import added after existing imports, not duplicated
    assert written.count(PYTEST_IMPORT_LINE) == 1
    assert "import os" in written
    assert "import sys" in written


# ---------------------------------------------------------------------------
# PR body rendering
# ---------------------------------------------------------------------------


def test_pr_body_lists_each_verdict():
    verdicts = [
        _verdict("tests.test_a::test_one"),
        _verdict("tests.test_b::test_two", "PFPFP"),
    ]
    edits = [
        MarkerEdit(
            test_id="tests.test_a::test_one",
            file_path=Path("tests/test_a.py"),
            status="applied",
        ),
        MarkerEdit(
            test_id="tests.test_b::test_two",
            file_path=Path("tests/test_b.py"),
            status="already-marked",
        ),
    ]
    body = format_pr_body(verdicts, edits)
    assert "Detected 2 flaky test(s)" in body
    assert "`tests.test_a::test_one`" in body
    assert "`tests.test_b::test_two`" in body
    assert "F P F P F" in body
    assert "marker: applied" in body
    assert "already present" in body


def test_pr_body_handles_missing_edit_outcomes():
    verdicts = [_verdict("tests.test_c::test_x")]
    edits = [
        MarkerEdit(
            test_id="tests.test_c::test_x", file_path=None, status="file-missing"
        ),
    ]
    body = format_pr_body(verdicts, edits)
    assert "file not found" in body


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def test_create_pr_dry_run_skips_shell(tmp_path):
    tests_root = tmp_path / "tests"
    _write_test_file(tests_root, "test_d", "def test_demo():\n    assert True\n")
    runner = RecordingRunner()
    result = create_quarantine_pr(
        [_verdict("tests.test_d::test_demo")],
        repo_root=tmp_path,
        tests_root=tests_root,
        dry_run=True,
        gh_runner=runner,
        now=datetime(2026, 5, 11, 3, 45, 1),
    )
    assert result.dry_run is True
    assert result.pr_url is None
    assert result.branch_name == "flaky-quarantine-20260511T034501"
    assert runner.calls == [], "Dry run must not invoke any shell commands"
    # Marker still applied to disk so caller can review the diff
    written = (tests_root / "test_d.py").read_text(encoding="utf-8")
    assert MARKER_LINE in written


def test_create_pr_invokes_git_and_gh(tmp_path):
    tests_root = tmp_path / "tests"
    _write_test_file(tests_root, "test_e", "def test_demo():\n    assert True\n")
    runner = RecordingRunner(
        pr_url="https://github.com/golikovichev/flaky-detector-agent/pull/7"
    )
    result = create_quarantine_pr(
        [_verdict("tests.test_e::test_demo")],
        repo_root=tmp_path,
        tests_root=tests_root,
        dry_run=False,
        gh_runner=runner,
        now=datetime(2026, 5, 11, 3, 45, 1),
    )
    sequence = [c.args[:2] for c in runner.calls]
    assert sequence == [
        ["git", "checkout"],
        ["git", "add"],
        ["git", "commit"],
        ["git", "push"],
        ["gh", "pr"],
    ]
    assert (
        result.pr_url == "https://github.com/golikovichev/flaky-detector-agent/pull/7"
    )
    assert result.branch_name == "flaky-quarantine-20260511T034501"


def test_create_pr_raises_when_no_verdicts(tmp_path):
    with pytest.raises(ValueError, match="no verdicts"):
        create_quarantine_pr(
            [],
            repo_root=tmp_path,
            tests_root=tmp_path / "tests",
            dry_run=True,
        )
