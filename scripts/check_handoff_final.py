#!/usr/bin/env python3
"""Check final Spike coverage reports for overclaiming placeholders.

This is a small hygiene check before pasting a handoff packet or final report
to the user. It does not judge architecture quality; it only catches phrases
that usually mean the agent copied a skeleton or old status name without
finishing the evidence review.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    message: str


RULES = [
    Rule(
        name="raw-agent-todo",
        pattern=re.compile(r"TODO\(agent\)|TODO:\s*interpret", re.IGNORECASE),
        message="replace raw TODO placeholders with agent reasoning or `needs source confirmation: <reason>`",
    ),
    Rule(
        name="old-marker-confirmed-status",
        pattern=re.compile(r"\bconfirmed-executed\b", re.IGNORECASE),
        message="use `marker-sequence-observed`; marker logs are evidence, not final path proof",
    ),
    Rule(
        name="marker-overclaim",
        pattern=re.compile(r"\bmarker-confirmed\b", re.IGNORECASE),
        message="describe marker evidence as observed, then let the agent choose final path confidence",
    ),
]


def check_file(path: Path) -> list[str]:
    findings: list[str] = []
    text = path.read_text(errors="replace")
    for line_no, line in enumerate(text.splitlines(), start=1):
        for rule in RULES:
            if rule.pattern.search(line):
                findings.append(f"{path}:{line_no}: {rule.name}: {rule.message}: {line.strip()}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="markdown/json/text files to check")
    args = parser.parse_args()

    findings: list[str] = []
    for path in args.files:
        findings.extend(check_file(path))

    if findings:
        print("handoff final check failed:")
        for item in findings:
            print(f"- {item}")
        return 1

    print("handoff final check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
