# Quarantine workflow with explicit checkpoints

End-to-end integration of `flaky-detector` into a real CI pipeline. The agent has multiple checkpoints so the reviewer can intervene at each step.

## Workflow stages

```
JUnit XML history  -->  flaky-detector scan  -->  Review console output (checkpoint 1)
                                                          |
                                                          v
                                              flaky-detector --dry-run-pr
                                                          |
                                                          v
                                              Review proposed PR body (checkpoint 2)
                                                          |
                                                          v
                                              flaky-detector --open-pr
                                                          |
                                                          v
                                              Review live draft PR (checkpoint 3)
                                                          |
                                                          v
                                              Take PR out of draft, merge
```

## Checkpoint 1: Console output review

The first detection run prints flagged tests with their flip patterns. The reviewer asks:

- Do these tests match my intuition about which tests are flaky?
- Are any obviously not flaky (recently fixed, or always-failing)?
- Should I tighten `--min-flips` or `--window-days` to reduce noise?

If the list looks wrong, tune thresholds and rerun before proceeding.

## Checkpoint 2: Dry-run PR body review

```bash
flaky-detector data/junit-history --open-pr --dry-run-pr
```

This prints the full PR body the agent would generate, including:

- Each flagged test name with its flip pattern
- The marker the agent will apply (`@pytest.mark.flaky(reruns=2)`)
- File path and line number where the marker will land
- Optional LLM fix snippet (when `OPENAI_API_KEY` is set)

The reviewer asks:

- Are the marker locations correct (the right test functions)?
- Does the PR body explain the situation to future readers?
- Do the LLM fix snippets look reasonable, or should they be dropped?

## Checkpoint 3: Live draft PR review

```bash
flaky-detector data/junit-history --open-pr
```

This creates the branch, commits all changes, opens a draft PR. The reviewer opens the PR in the browser and confirms:

- The diff applies markers to the right test functions, no collateral changes
- CI runs and the suite passes with markers applied
- The PR body matches the dry-run output
- The branch name is something like `flaky-quarantine-20260513T193000`

Once confirmed, take the PR out of draft and merge.

## Failure modes and recovery

### Marker landed on wrong function

`flaky-detector` uses pytest test ID parsing. If a test was renamed since the JUnit XML was generated, the marker may land on the wrong function. Recovery: edit the PR manually or close and rerun the detector against fresh JUnit XML.

### Branch already exists

The branch name includes a timestamp, so collisions are unlikely. If one happens (parallel runs), the second invocation will fail with a clear git error. Recovery: delete the duplicate branch and rerun.

### LLM fix snippet does not parse

The AST validation pass drops snippets that fail `ast.parse()`. The PR entry will then have no snippet attached. This is by design; no half-broken code reaches the reviewer.

### `gh` CLI not authenticated

`flaky-detector --open-pr` will print a clear error pointing to `gh auth login`. Run that command and retry.

## CI integration example

A nightly GitHub Actions workflow that scans the past 30 days of CI results:

```yaml
name: Flaky test quarantine

on:
  schedule:
    - cron: '0 6 * * *'  # daily at 06:00 UTC
  workflow_dispatch:

jobs:
  quarantine:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install flaky-detector
        run: pip install flaky-detector-agent
      - name: Download JUnit XML history from artifact storage
        run: |
          # repo-specific: pull last 30 days of JUnit XML files
          aws s3 sync s3://my-bucket/junit-history/ ./junit-history/
      - name: Run detection and open PR
        env:
          GH_TOKEN: ${{ secrets.GH_TOKEN }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          flaky-detector ./junit-history --open-pr
```

The workflow opens a draft PR the QA team reviews Monday morning. If no flakies are detected, no PR is opened.

## Tuning guidance

- **Low signal, high noise** (too many false positives): raise `--min-flips` to 4 or 5
- **Missing real flakies** (suite has known flakies that detector ignores): lower `--min-flips` to 2 or widen `--window-days` to 21
- **Stale flakies** (tests flagged that were fixed recently): narrow `--window-days` to 7 or 10
- **New-flakies focus** (detect newly introduced flakies only): use a 7-day window
