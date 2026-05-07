"""Flaky test detector. Heuristic: 3+ unrelated CI runs flipping outcome inside a 14-day window."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from flaky_detector.parser import TestRun


@dataclass(frozen=True)
class FlakyVerdict:
    """A test ruled flaky by the detector, with supporting evidence."""

    test_id: str
    flip_count: int
    window_days: int
    runs_considered: int
    evidence: list[TestRun]

    @property
    def reason(self) -> str:
        return (
            f"{self.flip_count} outcome flips across {self.runs_considered} "
            f"runs within a {self.window_days}-day window"
        )


def detect_flaky(
    runs: Iterable[TestRun],
    *,
    min_flips: int = 3,
    window_days: int = 14,
) -> list[FlakyVerdict]:
    """Return one FlakyVerdict per test that meets the flip threshold inside the window.

    Algorithm:
      1. Group runs by test_id.
      2. Sort each test's runs by timestamp.
      3. Slide a window of `window_days` over the runs.
      4. Inside any window, count outcome flips between consecutive runs.
      5. If a window contains >= min_flips, the test is flaky.

    A flip is a transition between is_failure states (pass -> fail or fail -> pass).
    Skipped and error outcomes are treated as their literal value, so error -> passed
    counts as a flip.
    """
    by_test: dict[str, list[TestRun]] = defaultdict(list)
    for run in runs:
        by_test[run.test_id].append(run)

    verdicts: list[FlakyVerdict] = []
    cutoff = timedelta(days=window_days)

    for test_id, history in by_test.items():
        history.sort(key=lambda r: r.timestamp)
        if len(history) < min_flips + 1:
            continue

        flips, window_runs = _max_flips_in_window(history, cutoff)
        if flips >= min_flips:
            verdicts.append(
                FlakyVerdict(
                    test_id=test_id,
                    flip_count=flips,
                    window_days=window_days,
                    runs_considered=len(window_runs),
                    evidence=window_runs,
                )
            )

    verdicts.sort(key=lambda v: v.flip_count, reverse=True)
    return verdicts


def _max_flips_in_window(
    history: list[TestRun],
    cutoff: timedelta,
) -> tuple[int, list[TestRun]]:
    """Slide a time window over sorted history, return the max flip count seen and the runs in that window."""
    best_flips = 0
    best_window: list[TestRun] = []

    left = 0
    for right in range(len(history)):
        while history[right].timestamp - history[left].timestamp > cutoff:
            left += 1

        window = history[left : right + 1]
        flips = _count_flips(window)
        if flips > best_flips:
            best_flips = flips
            best_window = list(window)

    return best_flips, best_window


def _count_flips(window: list[TestRun]) -> int:
    flips = 0
    for prev, curr in zip(window, window[1:]):
        if prev.is_failure != curr.is_failure:
            flips += 1
    return flips
