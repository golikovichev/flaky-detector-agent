# Flaky test patterns and root causes

This reference complements `SKILL.md` by mapping the flip patterns the detector surfaces to common root causes. The detector itself does not classify causes; it lists candidates for human triage.

## Pattern interpretation

A flip is a transition between failure states (pass to fail or fail to pass). Inside a 14-day window the patterns below are typical signatures.

| Pattern | Likely cause |
|---|---|
| `P F P F P` | Timing race in setup or shared fixture |
| `F P F P F` | Resource contention; test passes when system is idle, fails under load |
| `P P F P F` | Flakiness emerging recently; possible new dependency added |
| `P F F F P` | Threshold flake; system at the edge of timeout limits |
| `F F P P P` followed by stability | Old bug fixed, history before window cutoff still shows it |

## Common root causes

### Timing issues

- Fixed `time.sleep()` instead of polling with backoff
- `asyncio.sleep()` waits that race against real work completion
- Missing `await` on async fixtures
- DNS resolution timeouts in test setup

**Mitigation:** replace fixed sleeps with polling helpers (`pytest-retry`, `tenacity`). Mock time-sensitive paths.

### Shared state

- Class-level test fixtures retain data between tests
- Global singletons leak state across test files
- Database rows created in one test and read in another
- Cache lines persisted across pytest invocations

**Mitigation:** scope fixtures to `function` not `class`. Reset singletons in `conftest.py`. Use transaction rollback per test.

### External dependencies

- Real network calls to public APIs
- Hard-coded timestamps that drift past validation
- Third-party service rate limits
- File system races on parallel runners

**Mitigation:** mock at the boundary using `responses`, `httpretty`, or `pytest-vcr`. Use `freezegun` for time. Use temp directories from pytest fixtures.

### Resource exhaustion

- File descriptor leaks (test opens files, never closes)
- Database connection pool saturation
- Memory pressure on CI runners with small heaps
- Browser tab leaks in Selenium / Playwright suites

**Mitigation:** use context managers, explicit teardown, `pytest --maxfail=1` during debugging.

### Order dependency

- Test A leaves state that test B depends on (passes only when ordered)
- Test C corrupts state that test D needs (fails only when ordered)

**Mitigation:** run tests in random order with `pytest-randomly`. Treat order-dependent failures as real bugs.

## When the pattern does not match

If a flagged test has none of the patterns above, treat the flag as a candidate for investigation rather than a confirmed flaky. Some tests are simply correlated with infrastructure transients (CI runner restarts, GitHub Actions outages) and self-resolve.

## References

- Google Testing Blog: "Where do our flaky tests come from?" (2016)
- Microsoft Research: "An empirical analysis of flaky tests" (Luo et al., 2014)
- pytest documentation on `pytest-rerunfailures` and `pytest-flaky`
