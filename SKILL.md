---
name: flaky-detector
description: Detect flaky tests from CI history and propose LLM-validated fixes via quarantine pull requests.
---

# flaky-detector

Use when you need to identify tests that flip pass/fail in CI without code changes, and want to quarantine them automatically with @pytest.mark.flaky markers.

## When to use this skill

- You have CI history showing some tests pass-fail-pass within a short window
- Manual triage of flaky tests is eating engineering time
- You want to isolate suspect tests without disabling them outright

## What it does

1. Reads JUnit XML test results from your CI history
2. Identifies tests with 3 or more pass-fail flips inside a 14-day sliding window
3. Opens a quarantine pull request with @pytest.mark.flaky markers via the gh CLI
4. Optionally proposes LLM-suggested fixes validated through Python AST parsing so only parseable code reaches the PR

## Inputs

- Path to a directory containing JUnit XML files (one per CI run)
- Optional `--min-flips N` (default 3)
- Optional `--window-days N` (default 14)
- Optional `--tests-root <path>` (default `tests`)
- Optional `--open-pr` to actually create the PR via gh
- Optional `--dry-run-pr` to preview without git or gh calls

## Outputs

- Console list of flaky tests with flip pattern (for example: `P F P F P`)
- Quarantine pull request body with @pytest.mark.flaky markers, one entry per flaky test
- AST-validated LLM fix snippet attached to each entry when `OPENAI_API_KEY` is set

## Tools and dependencies

- Python 3.10 or newer
- pytest with `pytest-rerunfailures`
- gh CLI (for PR creation)
- OpenAI API (optional, for fix suggestions)
- Standard library only otherwise: `ast`, `json`, `pathlib`, `argparse`

## Example usage

```bash
flaky-detector data/sample_history --min-flips 3 --window-days 14
```

Sample output:

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

## Limitations

- Requires JUnit XML input (most CI systems support this out of the box)
- LLM suggestions need `OPENAI_API_KEY` env var; without it the skill still detects and quarantines, just without fix snippets
- AST validation pass only covers Python source today

## Source

https://github.com/golikovichev/flaky-detector-agent

Open-source under MIT.
