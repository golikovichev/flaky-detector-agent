"""Command-line entry point for flaky-detector-agent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flaky_detector import __version__
from flaky_detector.detector import detect_flaky
from flaky_detector.parser import parse_directory, parse_junit_xml


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="flaky-detector",
        description="Detect flaky tests from CI history. Optionally propose fixes via LLM.",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to a JUnit XML file or a directory of them.",
    )
    parser.add_argument(
        "--min-flips",
        type=int,
        default=3,
        help="Minimum outcome flips inside the window to flag a test (default: 3).",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=14,
        help="Sliding window size in days (default: 14).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"flaky-detector {__version__}",
    )

    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1

    if args.input.is_dir():
        runs = list(parse_directory(args.input))
    else:
        runs = parse_junit_xml(args.input)

    if not runs:
        print("No test runs parsed.", file=sys.stderr)
        return 1

    verdicts = detect_flaky(
        runs,
        min_flips=args.min_flips,
        window_days=args.window_days,
    )

    print(f"Scanned {len(runs)} test executions across "
          f"{len({r.run_id for r in runs})} CI runs.")

    if not verdicts:
        print("No flaky tests detected.")
        return 0

    print(f"\nDetected {len(verdicts)} flaky test(s):\n")
    for v in verdicts:
        print(f"  - {v.test_id}")
        print(f"      {v.reason}")
        last_outcomes = " ".join(
            "F" if r.is_failure else "P" for r in v.evidence
        )
        print(f"      pattern: {last_outcomes}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
