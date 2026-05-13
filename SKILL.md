---
name: flaky-detector
description: Detect flaky tests from CI history and propose LLM-validated fixes via quarantine pull requests. Use when Claude needs to find flaky tests, analyze CI test stability, identify tests that flip pass/fail without code changes, or set up automated quarantine workflows. Supports any test framework that emits JUnit XML (pytest, unittest, JUnit, TestNG, Vitest, Jest with junit reporter). Trigger when users mention "flaky tests", "intermittent failures", "tests that randomly fail", "quarantine flaky tests", "CI flakiness", or ask to "find unreliable tests", "analyze CI history", "mark tests as flaky".
---

# flaky-detector

Identify tests that flip pass/fail in CI without code changes, then quarantine them automatically with `@pytest.mark.flaky` markers and optional LLM-suggested fixes.

## Quick Start

When a user reports flaky tests, intermittent CI failures, or asks to analyze test stability:

1. **Locate the CI history**. Ask for a directory of JUnit XML files (one per CI run) or a single XML file. Most CI systems can publish these as artifacts.
2. **Run the detector**: `flaky-detector <path> --min-flips 3 --window-days 14`. Tune flip count and window size to match the team's noise tolerance.
3. **Review the flagged tests**. Each entry shows the flip pattern (for example `P F P F P`) and how many flips fall inside the window.
4. **Open a quarantine PR**: add `--open-pr` to apply `@pytest.mark.flaky(reruns=2)` markers and open a draft pull request via the `gh` CLI.
5. **Optional LLM fix snippets**: set `OPENAI_API_KEY` to attach AST-validated fix proposals to each entry in the PR body.

## What flaky tests are and why detection matters

A flaky test passes on one run and fails on the next without source changes in between. Flaky tests slowly destroy trust in CI: developers start ignoring red builds, real regressions sneak through, and engineering time goes to manual triage rather than features.

Common root causes detected indirectly through flip patterns:

- **Timing**: race conditions, fixed sleeps, async/await mismatches, polling loops without backoff
- **Shared state**: leaked fixtures, global singletons, parallel tests writing to the same database row
- **External dependencies**: real network calls, hard-coded timestamps, third-party API rate limits
- **Resource exhaustion**: file handle leaks, memory pressure on the CI runner, browser tab limits
- **Order dependency**: tests that pass alone but fail together, or vice versa

The detector does not classify root causes itself. It surfaces candidates for human triage by counting outcome flips inside a sliding window.

## Detection methodology

### Heuristic

A test is flagged flaky when it shows **3 or more outcome flips inside any 14-day sliding window**. Both thresholds are configurable via `--min-flips` and `--window-days`.

A flip is a transition between failure states (pass to fail, or fail to pass). The heuristic deliberately ignores:

- Always-failing tests (zero flips, broken not flaky)
- Always-passing tests (zero flips, healthy)
- Single transient blips inside the window (under threshold)

### Why a flip count, not a failure rate

Failure rate alone confuses flaky tests with consistently-broken ones. A test that fails 50% of the time with pattern `F F F P P P` is broken on one side and fixed on the other, not flaky. A test with pattern `P F P F P` has the same failure rate but is the classic flaky signature.

### Why 14 days

Two-week windows match typical sprint cadence and avoid both extremes:

- Shorter windows (3-5 days) miss intermittent flakies that surface every few days
- Longer windows (30+ days) flag stale tests that were flaky last month but were fixed since

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

**Console listing** for every flagged test:

```
Scanned 45 test executions across 5 CI runs.

Detected 3 flaky test(s):

  - tests.test_login::test_login_concurrent_session
      4 outcome flips across 5 runs within a 14-day window
      pattern: P F P F P

  - tests.test_checkout::test_checkout_timeout
      4 outcome flips across 5 runs within a 14-day window
      pattern: F P F P F

  - tests.test_search::test_search_index_warmup
      3 outcome flips across 5 runs within a 14-day window
      pattern: P P F P F
```

**Quarantine pull request body** (when `--open-pr` set) with one entry per flaky test, including the flip pattern, the marker the agent applied, and an optional LLM fix snippet.

**Branch and commit** named `flaky-quarantine-<timestamp>` so the team can review the diff before merging.

## LLM fix suggestions and AST validation

When `OPENAI_API_KEY` is set, the agent asks an LLM (Codex by default) for a candidate fix snippet for each flagged test. The agent then runs the snippet through Python `ast.parse()` before attaching it to the PR body. If the snippet does not parse, it is dropped silently so only well-formed code reaches the PR.

This pattern keeps generated code honest. The reviewer always sees parseable Python, never half-broken strings.

## Example workflow

A typical CI integration looks like this:

1. Nightly job pulls the last 30 JUnit XML files from artifact storage.
2. Job runs `flaky-detector <dir> --open-pr` against the collection.
3. If any flakies are detected, a draft PR is opened on the repo with markers applied.
4. The QA team reviews the PR every Monday morning, merges if appropriate, and files real bug tickets for the underlying issues.

## When to use this skill

- A user reports tests failing randomly without code changes nearby
- A team wants to triage CI flakiness across the last sprint
- A maintainer needs to quarantine known-flaky tests before a release
- A QA engineer is setting up flakiness detection in a new repo

## When not to use this skill

- The test suite has no JUnit XML output (use a different reporter first)
- Failures correlate clearly with code changes (those are real bugs, not flakies)
- Tests run only once per change (no history to analyze)

## Limitations

- Requires JUnit XML format input. Most CI systems support this out of the box but legacy systems may need a reporter plugin.
- LLM fix suggestions need `OPENAI_API_KEY` env var. Without it the skill still detects and quarantines, just without snippets.
- AST validation covers Python source today. Other languages would need their own parser pass.
- The 14-day window assumes near-daily CI runs. Repos that run CI only on tagged releases need a longer window.

## Dependencies

- Python 3.10 or newer
- `pytest` with `pytest-rerunfailures` for the quarantine markers
- `gh` CLI authenticated against the target repo for PR creation
- `OpenAI` Python SDK if LLM fix suggestions are wanted

## Source

https://github.com/golikovichev/flaky-detector-agent

MIT licensed. Issues and pull requests welcome.
