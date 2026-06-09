"""JUnit XML parser. Reads CI history into normalised TestRun records."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class TestRun:
    """One execution of one test on one CI run."""

    # Tell pytest not to collect this dataclass as a test class
    __test__ = False

    test_id: str
    suite: str
    outcome: str  # "passed" | "failed" | "skipped" | "error"
    duration: float
    timestamp: datetime
    run_id: str
    failure_message: str = ""

    @property
    def is_failure(self) -> bool:
        return self.outcome in ("failed", "error")


def parse_junit_xml(path: str | Path) -> list[TestRun]:
    """Read a JUnit XML file and return TestRun records.

    Supports the standard schema:
      <testsuites>
        <testsuite name="..." timestamp="ISO8601" run-id="...">
          <testcase classname="..." name="..." time="N"/>
          <testcase classname="..." name="..."><failure message="..."/></testcase>
        </testsuite>
      </testsuites>

    The parser is lenient. Missing run-id falls back to file name. Missing
    timestamp falls back to current time. Skipped and error outcomes are
    preserved.
    """
    path = Path(path)
    tree = ET.parse(path)
    root = tree.getroot()

    runs: list[TestRun] = []

    suites = root.findall(".//testsuite") if root.tag == "testsuites" else [root]
    for suite in suites:
        suite_name = suite.attrib.get("name", "unknown")
        run_id = suite.attrib.get("run-id") or suite.attrib.get("id") or path.stem
        ts_raw = suite.attrib.get("timestamp", "")
        timestamp = _parse_timestamp(ts_raw)

        for case in suite.findall("testcase"):
            test_id = _build_test_id(case)
            outcome, message = _classify_outcome(case)
            duration = float(case.attrib.get("time", "0") or "0")

            runs.append(
                TestRun(
                    test_id=test_id,
                    suite=suite_name,
                    outcome=outcome,
                    duration=duration,
                    timestamp=timestamp,
                    run_id=run_id,
                    failure_message=message,
                )
            )

    return runs


def parse_directory(directory: str | Path) -> Iterator[TestRun]:
    """Yield TestRun records from every .xml file in a directory."""
    directory = Path(directory)
    for xml_path in sorted(directory.glob("*.xml")):
        yield from parse_junit_xml(xml_path)


def _build_test_id(case: ET.Element) -> str:
    classname = case.attrib.get("classname", "")
    name = case.attrib.get("name", "unknown")
    if classname:
        return f"{classname}::{name}"
    return name


def _classify_outcome(case: ET.Element) -> tuple[str, str]:
    failure = case.find("failure")
    if failure is not None:
        return "failed", failure.attrib.get("message", "") or (
            failure.text or ""
        ).strip()

    error = case.find("error")
    if error is not None:
        return "error", error.attrib.get("message", "") or (error.text or "").strip()

    skipped = case.find("skipped")
    if skipped is not None:
        return "skipped", skipped.attrib.get("message", "")

    return "passed", ""


def _parse_timestamp(raw: str) -> datetime:
    if not raw:
        return datetime.now()
    raw = raw.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now()
