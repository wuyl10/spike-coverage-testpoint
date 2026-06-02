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


DEFAULT_GATE_YES_RE = re.compile(
    r"default_gate_eligible\s*[:=-]\s*(`?yes`?|true)\b|"
    r"default_gate_eligible\s+(is\s+)?(`?yes`?|true)\b",
    re.IGNORECASE,
)

GENERIC_NEEDS_SOURCE_RE = re.compile(
    r"needs source confirmation:\s*(map uncovered code to an architecture-visible scenario|"
    r"map coverage evidence to the missing architecture-visible cross execution scenario|"
    r"register/memory/trap/CSR/vector observable|"
    r"register/memory/trap/CSR/vector/device observable|"
    r"choose one after evidence review|"
    r"derive this field from source/gcov/path-marker evidence|"
    r"derive from coverage dimension, representative entries, and inspected Spike source|"
    r"derive from target coverage_focus/profile and dimension gate.*|"
    r"derive only if source/gcov proves .+|"
    r"list must-pass line/branch/call/path-marker evidence and current status|"
    r"in-scope \| out-of-scope \| needs target decision|"
    r"infer required ISA/profile feature from source and representative entries|"
    r"yes/no/unknown after confirming feature availability and deterministic observable|"
    r"what is still not proven about this cross scenario or same-flow path|"
    r"interpret .+ as an architecture-visible (cross )?scenario)",
    re.IGNORECASE,
)


def check_file(path: Path) -> list[str]:
    findings: list[str] = []
    text = path.read_text(errors="replace")
    for line_no, line in enumerate(text.splitlines(), start=1):
        for rule in RULES:
            if rule.pattern.search(line):
                findings.append(f"{path}:{line_no}: {rule.name}: {rule.message}: {line.strip()}")
    return findings


def strict_handoff_check(path: Path, final_report: bool = False) -> list[str]:
    findings: list[str] = []
    text = path.read_text(errors="replace")
    required_terms = [
        "scenario_coverage_gap",
        "cross_scenario_signature",
        "coverage_evidence_role",
        "evidence_class",
        "line_evidence_status",
        "path_confidence",
        "profile_gate",
        "expected_observable",
    ]
    for term in required_terms:
        if term not in text:
            findings.append(f"{path}: strict-handoff: missing `{term}`")
    if "same_flow_evidence" not in text:
        findings.append(f"{path}: strict-handoff: missing `same_flow_evidence`")

    default_gate_lines = [
        (line_no, line)
        for line_no, line in enumerate(text.splitlines(), start=1)
        if re.search(r"gate_note:\s*default|gate_note:\s*`?default", line, re.IGNORECASE)
    ]
    for line_no, _line in default_gate_lines:
        window = "\n".join(text.splitlines()[max(0, line_no - 12): line_no + 12]).lower()
        if not DEFAULT_GATE_YES_RE.search(window):
            findings.append(
                f"{path}:{line_no}: strict-handoff: default gate requires nearby default_gate_eligible: yes evidence"
            )
    if final_report:
        for line_no, line in enumerate(text.splitlines(), start=1):
            if GENERIC_NEEDS_SOURCE_RE.search(line):
                findings.append(
                    f"{path}:{line_no}: strict-final-report: unresolved generic skeleton field: {line.strip()}"
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="markdown/json/text files to check")
    parser.add_argument("--strict-handoff", action="store_true", help="also require handoff evidence/profile fields")
    parser.add_argument(
        "--strict-final-report",
        action="store_true",
        help="reject generic needs-source skeleton fields that must be resolved before a user-facing final report",
    )
    args = parser.parse_args()

    findings: list[str] = []
    for path in args.files:
        findings.extend(check_file(path))
        if args.strict_handoff or args.strict_final_report:
            findings.extend(strict_handoff_check(path, final_report=args.strict_final_report))

    if findings:
        print("handoff final check failed:")
        for item in findings:
            print(f"- {item}")
        return 1

    print("handoff final check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
