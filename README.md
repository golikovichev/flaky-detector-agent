# flaky-detector-agent

Surface flaky tests from CI history. Propose fixes via an LLM agent.

> **Status: hackathon prototype.** Built in one day for A.I. Agent Skills Hack Night (Tessl × Neo4j × Hubble × OpenAI Codex, London, 13 May 2026). The code works for the heuristic it implements, but the project is not actively maintained. If you want production-grade Python testing tools from the same author, see [postman2pytest](https://github.com/golikovichev/postman2pytest) and [pytest-conversational](https://github.com/golikovichev/pytest-conversational).

## What it does

You have a CI history. Some tests pass-then-fail-then-pass within the same week without code changes nearby. Those tests slowly kill trust in the whole suite.

`flaky-detector-agent` reads JUnit XML from your CI runs, applies a 14-day-window flip-count heuristic, and tells you which tests are flaky. The LLM agent then proposes a quarantine plus a fix direction for each one.

## Heuristic

A test is flagged flaky when it shows **3 or more outcome flips inside any 14-day sliding window**. Both thresholds are configurable.

A flip is a transition between failure states (pass to fail, fail to pass). Always-failing tests are not flaky, they are broken. A single transient blip is not flaky, it is a one-off.

## Quickstart

```bash
git clone https://github.com/golikovichev/flaky-detector-agent
cd flaky-detector-agent
python -m venv .venv && source .venv/bin/activate
pip install -e .

flaky-detector data/sample_history/
```

Sample output on the bundled history (5 CI runs over 14 days, 9 tests):

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

## Tuning

```bash
flaky-detector data/sample_history/ --min-flips 5 --window-days 7
```

Stricter thresholds catch fewer tests. Looser thresholds catch more, including some that are merely unstable rather than truly flaky.

## Architecture

Three modules.

`parser.py` reads JUnit XML. Lenient with missing fields, picks up failure messages and timestamps, normalises into `TestRun` records.

`detector.py` groups runs per test and sorts by timestamp. It slides a window over the history, counts flips inside the window, then ranks results by flip count.

`agent.py` is the LLM hook. It takes a verdict and returns a `FixProposal` with a quarantine marker plus a suggested code direction. The default stub returns a `@pytest.mark.flaky(reruns=2)` plus a TODO comment. With `OPENAI_API_KEY` set, it calls an OpenAI-compatible chat endpoint, validates the response with `ast.parse`, and retries on invalid output.

`quarantine.py` handles the PR side. It applies markers to the actual test source, formats a markdown PR body, then shells out to `gh pr create`. The shell layer is dependency-injected so the unit tests cover the full flow without touching git or GitHub.

## PR autopost

Once the detector has flagged a few tests, the agent can open a quarantine PR for you. Two flags drive the workflow:

```bash
# Dry run: apply markers locally, print the PR body, skip git and gh entirely.
flaky-detector data/sample_history/ --dry-run-pr --tests-root tests/

# Live: create a new branch, commit the marker changes, push, open a PR via gh.
flaky-detector data/sample_history/ --open-pr --tests-root tests/
```

The branch name looks like `flaky-quarantine-20260511T100207`. The PR body lists each detected test with its flip pattern and reports whether the marker was applied, was already present, or had to be skipped.

The marker insertion is idempotent. Re-running on the same tree picks up only newly flaky tests.

## Roadmap

- v0.2: real OpenAI Chat Completions call in `agent.py`, with AST validation and retry. **Shipped.**
- v0.3: quarantine PR autopost via `gh pr create`. Markers, branch, body, dry-run mode. **Shipped.**
- v0.4: storage layer. SQLite cache so repeated runs do not re-process the whole history.
- v0.5: pytest plugin mode. Run inside CI directly, write back to the same repo.

## Tests

```bash
pytest tests/ -v
```

## Why this exists

I am sole QA on a backend e-commerce platform. Across a 200+ regression suite over two years, I have settled on the same heuristic: 3 unrelated CI runs flipping outcome inside a 14-day window with no relevant commit between them. That is the only definition of flaky I trust.

This tool encodes that heuristic and adds an LLM step on top, so the suggested action is concrete instead of abstract.

## Licence

MIT. See `LICENSE`.
