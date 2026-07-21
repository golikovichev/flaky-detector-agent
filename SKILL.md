---
name: flaky-detector
description: Detect flaky tests from CI history and propose LLM-validated fixes via quarantine pull requests. Use to find flaky tests, analyze CI test stability, identify tests that flip pass/fail without code changes, or set up automated quarantine workflows. Supports any test framework that emits JUnit XML (pytest, unittest, JUnit, TestNG, Vitest, Jest with junit reporter). Trigger when users mention "flaky tests", "intermittent failures", "tests that randomly fail", "quarantine flaky tests", "CI flakiness", or ask to "find unreliable tests", "analyze CI history", "mark tests as flaky".
---

# flaky-detector

Identify tests that flip pass/fail in CI without code changes, then quarantine them automatically with `@pytest.mark.flaky` markers and optional LLM-suggested fixes.

## Installation

```bash
pip install flaky-detector-agent          # or: pip install -e . from a clone
gh auth login                             # once per machine, lets the agent open PRs
export OPENAI_API_KEY=sk-...              # optional, enables fix suggestions
```

Verify:

```bash
flaky-detector --help
flaky-detector data/sample_history        # bundled sample with 3 known flakies
```

## Quick Start

Work through the steps in order, checking the output of each before moving on.

1. **Locate the CI history.** Point the detector at a directory of JUnit XML files (one per CI run) or a single file; most CI systems publish these as build artifacts. The path must exist and hold at least one valid JUnit XML file.
2. **Preview detection.** `flaky-detector data/junit-history --min-flips 3 --window-days 14` prints the flagged tests and their flip patterns. Confirm they match the team's intuition before going further; false positives waste reviewer time.
3. **Dry-run the PR.** `flaky-detector data/junit-history --open-pr --dry-run-pr` shows the markers and PR body without touching git or `gh`. The body should list each test with its pattern, the marker location, and (if `OPENAI_API_KEY` is set) the validated fix snippet.
4. **Open the PR.** `flaky-detector data/junit-history --open-pr` creates branch `flaky-quarantine-<timestamp>`, applies markers, commits, and opens a draft PR via `gh`. Open it in the browser, confirm the markers sit on the right tests, then take it out of draft when ready.
5. **Optional fix snippets.** With `OPENAI_API_KEY` set, the agent asks an LLM (gpt-4o-mini by default) for a candidate fix per flagged test and runs it through Python `ast.parse()` before attaching. Treat the snippet as a hint to adapt, not final code.

## How detection works

A test is flagged when it shows **3 or more outcome flips inside any 14-day sliding window** (both thresholds configurable via `--min-flips` and `--window-days`). A flip is a transition between pass and fail. Always-failing tests (broken, not flaky) and always-passing tests are ignored, as are single blips under the threshold.

The detector surfaces candidates by counting flips; it does not classify root causes. See `references/flaky-patterns.md` for why flip count beats failure rate and the root-cause taxonomy, and `references/quarantine-workflow.md` for end-to-end CI integration with checkpoints.

## Inputs

| Argument | Meaning | Default |
|---|---|---|
| `input` | Path to a JUnit XML file or directory of them | required |
| `--min-flips N` | Minimum outcome flips inside the window to flag a test | 3 |
| `--window-days N` | Sliding window size in days | 14 |
| `--open-pr` | Apply `@pytest.mark.flaky` markers and open a quarantine PR via `gh` | off |
| `--dry-run-pr` | With `--open-pr`: preview only, no git or gh calls | off |
| `--tests-root PATH` | Root directory where pytest test files live | `tests` |
| `--repo-root PATH` | Repo root passed to git and gh | current dir |

## Outputs

Console listing for every flagged test:

```
Scanned 45 test executions across 5 CI runs.

Detected 3 flaky test(s):

  - tests.test_login::test_login_concurrent_session
      4 outcome flips across 5 runs within a 14-day window
      pattern: P F P F P
```

Plus, when `--open-pr` is set, a quarantine pull request: one entry per flaky test (flip pattern, applied marker, optional validated fix snippet), on branch `flaky-quarantine-<timestamp>` so the team reviews the diff before merging.

## Limits and requirements

- **Input:** JUnit XML only. Frameworks without it need a junit reporter plugin first.
- **History:** the 14-day window assumes near-daily CI runs; repos that run CI only on tagged releases need a longer window.
- **Scope:** use it when tests flip without code changes. Failures that track code changes are real bugs, not flakies; suites run only once per change have no history to analyze.
- **Fix snippets:** need `OPENAI_API_KEY`; AST validation covers Python today. Without the key, detection and quarantine still work, just without snippets.
- **Runtime:** Python 3.10+, `pytest` with `pytest-rerunfailures`, an authenticated `gh` CLI, and the OpenAI SDK if snippets are wanted.

## Source

https://github.com/golikovichev/flaky-detector-agent - MIT licensed. Issues and pull requests welcome.
