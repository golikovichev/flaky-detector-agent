"""Quarantine workflow: apply pytest.mark.flaky to detected tests, open a PR.

Glue layer between detector verdicts and a GitHub Pull Request. Three pieces:

  1. apply_quarantine_marker - rewrites the test source so the target function
     gets a @pytest.mark.flaky(reruns=2) decorator. Idempotent. Skips files it
     cannot find or cannot edit safely.
  2. format_pr_body - renders a markdown summary that pastes cleanly into the
     PR description.
  3. create_quarantine_pr - orchestrates branch creation, marker application,
     commit, push and `gh pr create`. The shell layer is dependency-injected
     so tests can swap in an in-memory recorder.

Everything except the optional `subprocess.run` call is pure Python, so unit
tests cover the full happy path without touching git or GitHub.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Sequence

from flaky_detector.detector import FlakyVerdict


MARKER_LINE = "@pytest.mark.flaky(reruns=2)"
PYTEST_IMPORT_LINE = "import pytest"


# ---------------------------------------------------------------------------
# Branch naming
# ---------------------------------------------------------------------------


def build_branch_name(now: Optional[datetime] = None) -> str:
    """Return a deterministic branch name like flaky-quarantine-20260511T034501.

    The timestamp is UTC down to the second so concurrent runs do not collide.
    Format avoids underscores so it reads cleanly in `git branch` output.
    """
    from datetime import timezone
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return f"flaky-quarantine-{stamp}"


# ---------------------------------------------------------------------------
# Marker application
# ---------------------------------------------------------------------------


@dataclass
class MarkerEdit:
    """Outcome of trying to apply a marker to one test."""

    test_id: str
    file_path: Optional[Path]
    status: str  # "applied", "already-marked", "file-missing", "function-missing"


def _test_id_to_file_path(test_id: str, tests_root: Path) -> Optional[Path]:
    """Translate tests.test_login::test_x to tests_root/test_login.py.

    Accepts both dot-separated module paths (tests.subdir.test_x) and direct
    file paths (tests/test_x.py). Returns None if the candidate path does not
    exist on disk.
    """
    if "::" not in test_id:
        return None
    module_part = test_id.split("::", 1)[0]
    # Strip a leading 'tests.' prefix if it duplicates tests_root.
    parts = module_part.split(".")
    if parts and parts[0] == tests_root.name:
        parts = parts[1:]
    candidate = tests_root.joinpath(*parts).with_suffix(".py")
    return candidate if candidate.is_file() else None


def _function_name(test_id: str) -> str:
    if "::" not in test_id:
        return test_id
    return test_id.split("::", 1)[1].split("::")[-1]


def _ensure_pytest_import(lines: list[str]) -> list[str]:
    """Make sure `import pytest` shows up near the top of the file."""
    for line in lines:
        if line.strip() == PYTEST_IMPORT_LINE:
            return lines
    # Insert after the last import line, or at the top if none found.
    insert_at = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_at = idx + 1
    new_lines = list(lines)
    new_lines.insert(insert_at, PYTEST_IMPORT_LINE)
    return new_lines


def apply_quarantine_marker(test_id: str, tests_root: Path) -> MarkerEdit:
    """Insert @pytest.mark.flaky(reruns=2) above the target function.

    Idempotent: if the marker already sits directly above the function, the
    call returns status='already-marked' and does not rewrite the file.
    """
    file_path = _test_id_to_file_path(test_id, tests_root)
    if file_path is None:
        return MarkerEdit(test_id=test_id, file_path=None, status="file-missing")

    func_name = _function_name(test_id)
    source = file_path.read_text(encoding="utf-8")
    lines = source.splitlines()

    # Find the `def func_name(` line. Match indentation 0 (module-level).
    def_pattern = re.compile(rf"^def\s+{re.escape(func_name)}\s*\(")
    target_index = next(
        (i for i, line in enumerate(lines) if def_pattern.match(line)), None
    )
    if target_index is None:
        return MarkerEdit(
            test_id=test_id, file_path=file_path, status="function-missing"
        )

    # Already-marked check: the line directly above target is the marker.
    if target_index > 0 and lines[target_index - 1].strip() == MARKER_LINE:
        return MarkerEdit(
            test_id=test_id, file_path=file_path, status="already-marked"
        )

    new_lines = list(lines)
    new_lines.insert(target_index, MARKER_LINE)
    new_lines = _ensure_pytest_import(new_lines)

    # Preserve trailing newline if the original had one.
    trailing = "\n" if source.endswith("\n") else ""
    file_path.write_text("\n".join(new_lines) + trailing, encoding="utf-8")
    return MarkerEdit(test_id=test_id, file_path=file_path, status="applied")


# ---------------------------------------------------------------------------
# PR body
# ---------------------------------------------------------------------------


def format_pr_body(
    verdicts: Sequence[FlakyVerdict],
    edits: Sequence[MarkerEdit],
) -> str:
    """Render a markdown body listing each verdict and the edit outcome."""
    lines: list[str] = []
    lines.append("Automated quarantine of flaky tests detected by flaky-detector-agent.")
    lines.append("")
    lines.append(f"Detected {len(verdicts)} flaky test(s). "
                 "Each entry below carries the flip pattern from CI history.")
    lines.append("")
    by_id = {e.test_id: e for e in edits}
    for v in verdicts:
        edit = by_id.get(v.test_id)
        pattern = " ".join("F" if r.is_failure else "P" for r in v.evidence)
        lines.append(f"### `{v.test_id}`")
        lines.append("")
        lines.append(f"- {v.reason}")
        lines.append(f"- pattern: `{pattern}`")
        if edit is None:
            lines.append("- marker: (not evaluated)")
        elif edit.status == "applied":
            lines.append(f"- marker: applied in `{edit.file_path}`")
        elif edit.status == "already-marked":
            lines.append(f"- marker: already present in `{edit.file_path}`")
        elif edit.status == "file-missing":
            lines.append("- marker: file not found on disk, please apply manually")
        elif edit.status == "function-missing":
            lines.append(
                f"- marker: function not found in `{edit.file_path}`, please apply manually"
            )
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "Review the diff, run the suite, and merge when comfortable. "
        "Markers default to `reruns=2`; tighten or drop them once the underlying issue is fixed."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PR creation orchestration
# ---------------------------------------------------------------------------


GhRunner = Callable[[Sequence[str], Path], "subprocess.CompletedProcess[str]"]


def _default_gh_runner(args: Sequence[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
    """Real subprocess invocation. Replaced by injected runner in tests."""
    return subprocess.run(  # noqa: S603
        list(args), cwd=cwd, check=True, capture_output=True, text=True
    )


@dataclass
class PrResult:
    """What create_quarantine_pr returns. Useful for CLI output and tests."""

    branch_name: str
    edits: list[MarkerEdit] = field(default_factory=list)
    pr_url: Optional[str] = None
    dry_run: bool = False
    pr_body: str = ""


def create_quarantine_pr(
    verdicts: Sequence[FlakyVerdict],
    *,
    repo_root: Path,
    tests_root: Path,
    dry_run: bool = False,
    gh_runner: GhRunner = _default_gh_runner,
    now: Optional[datetime] = None,
) -> PrResult:
    """Apply markers, commit, push and open a PR via `gh pr create`.

    When dry_run is True the function still applies markers to disk so the
    caller can inspect the diff, but no git or gh commands run. Returns a
    PrResult so callers can inspect outcomes.
    """
    if not verdicts:
        raise ValueError("create_quarantine_pr called with no verdicts")

    branch = build_branch_name(now)
    edits = [apply_quarantine_marker(v.test_id, tests_root) for v in verdicts]
    body = format_pr_body(verdicts, edits)

    result = PrResult(
        branch_name=branch,
        edits=edits,
        dry_run=dry_run,
        pr_body=body,
    )

    if dry_run:
        return result

    if shutil.which("gh") is None and gh_runner is _default_gh_runner:
        raise RuntimeError(
            "gh CLI not found on PATH. Install GitHub CLI or pass a custom gh_runner."
        )

    title = f"chore(flaky): quarantine {len(verdicts)} flaky test(s)"

    # Steps run sequentially; if any fails the runner raises and we surface it.
    _run_git(repo_root, ["git", "checkout", "-b", branch], gh_runner)
    _run_git(repo_root, ["git", "add", "-A"], gh_runner)
    _run_git(repo_root, ["git", "commit", "-m", title], gh_runner)
    _run_git(repo_root, ["git", "push", "-u", "origin", branch], gh_runner)
    completed = gh_runner(
        ["gh", "pr", "create", "--title", title, "--body", body],
        repo_root,
    )
    result.pr_url = (completed.stdout or "").strip().splitlines()[-1] if completed.stdout else None
    return result


def _run_git(repo_root: Path, cmd: Sequence[str], runner: GhRunner) -> None:
    runner(cmd, repo_root)
