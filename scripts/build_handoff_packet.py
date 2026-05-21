#!/usr/bin/env python3
"""Build a hyptest-workflow handoff packet skeleton from coverage evidence.

This script only copies and organizes evidence from analyze_spike_gcov.py JSON
and an optional inspect_gcov_lines.py JSON report. It intentionally leaves
architecture interpretation fields for the agent to fill.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def short_name(path: str) -> str:
    name = Path(path).name
    for suffix in (".h", ".cc", ".c", ".cpp", ".gcov"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def candidate_matches(candidate: dict[str, Any], selected: set[str]) -> bool:
    if not selected:
        return True
    dim = candidate.get("dimension", "")
    entries = [short_name(item) for item in candidate.get("entries", [])]
    haystack = " ".join([dim] + entries).lower()
    return any(item.lower() in haystack for item in selected)


def line_evidence_for_dimension(
    inspect_reports: list[dict[str, Any]],
    inspection_files: list[str],
    representative_entries: list[str],
    max_items: int,
) -> list[dict[str, Any]]:
    representative_gcov = {Path(entry).name + ".gcov" for entry in representative_entries}
    wanted = {Path(item).name for item in inspection_files} | representative_gcov
    exact_wanted = wanted & representative_gcov

    def report_rank(report: dict[str, Any]) -> tuple[int, str]:
        gcov_name = Path(report.get("gcov_file", "")).name
        if gcov_name in exact_wanted:
            return (0, gcov_name)
        if gcov_name in representative_gcov:
            return (1, gcov_name)
        if gcov_name in wanted and ".h.gcov" in gcov_name:
            return (2, gcov_name)
        if gcov_name in wanted:
            return (3, gcov_name)
        return (4, gcov_name)

    ordered_reports = sorted(
        inspect_reports,
        key=report_rank,
    )

    def collect(allow_shared: bool) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for report in ordered_reports:
            gcov_name = Path(report.get("gcov_file", "")).name
            if wanted and gcov_name not in wanted:
                continue
            exact = gcov_name in exact_wanted or gcov_name in representative_gcov
            if not allow_shared and not exact:
                continue
            for fn in report.get("functions", [])[:max_items]:
                events = fn.get("events", [])
                first = next((event for event in events if event.get("source_line") is not None), None)
                counts: dict[str, int] = {}
                for event in events:
                    counts[event.get("kind", "unknown")] = counts.get(event.get("kind", "unknown"), 0) + 1
                results.append(
                    {
                        "gcov_file": gcov_name,
                        "evidence_match": "representative-entry" if exact else "inspection-hint",
                        "function": fn.get("name"),
                        "first_source_line": first.get("source_line") if first else None,
                        "first_evidence": first.get("text") if first else None,
                        "miss_kinds": counts,
                    }
                )
                if len(results) >= max_items:
                    return results
        return results

    results = collect(allow_shared=False)
    if results:
        return results
    results = collect(allow_shared=True)
    return results


def missing_inspection_files(inspect_reports: list[dict[str, Any]], inspection_files: list[str]) -> list[str]:
    if not inspection_files:
        return []
    seen = {Path(report.get("gcov_file", "")).name for report in inspect_reports}
    missing = [Path(item).name for item in inspection_files if Path(item).name not in seen]
    return list(dict.fromkeys(missing))


def duplicate_terms(target: dict[str, Any], dimension: str) -> list[str]:
    terms = target.get("duplicate_search_terms", {})
    if not isinstance(terms, dict):
        return []
    dim_lc = dimension.lower()
    matched: list[str] = []
    for name, values in terms.items():
        if name.lower() == dim_lc:
            matched.extend(values)
    if not matched:
        aliases = target.get("duplicate_search_aliases", {})
        if isinstance(aliases, dict):
            for name, values in terms.items():
                alias_values = aliases.get(name, [])
                if isinstance(alias_values, list) and any(str(alias).lower() == dim_lc for alias in alias_values):
                    matched.extend(values)
    if not matched:
        for name, values in terms.items():
            if name.lower() in dim_lc or dim_lc in name.lower():
                matched.extend(values)
    if not matched:
        fallback_keys = ("vector", "atomic", "amo", "compressed", "scalar", "fp", "cbo", "lr/sc")
        for name, values in terms.items():
            name_lc = name.lower()
            if name_lc in fallback_keys and name_lc in dim_lc:
                matched.extend(values)
    return sorted(dict.fromkeys(matched))


def build_packet(
    summary: dict[str, Any],
    inspect_reports: list[dict[str, Any]],
    selected: set[str],
    top: int,
    max_line_evidence: int,
) -> dict[str, Any]:
    target = summary.get("target", {})
    handoff = target.get("handoff_defaults", {})
    path_analysis = target.get("path_analysis", {}) if isinstance(target.get("path_analysis"), dict) else {}
    axes = path_analysis.get("combination_axes", {}) if isinstance(path_analysis.get("combination_axes"), dict) else {}
    confidence_levels = path_analysis.get("confidence_levels", []) if isinstance(path_analysis.get("confidence_levels"), list) else []
    candidates = [
        candidate
        for candidate in summary.get("candidates", [])
        if candidate_matches(candidate, selected)
    ][:top]

    packet_candidates = []
    for candidate in candidates:
        dimension = candidate.get("dimension", "")
        inspection_files = candidate.get("inspection_files", [])
        packet_candidates.append(
            {
                "candidate_name": f"TODO: interpret {dimension}",
                "coverage_dimension": dimension,
                "coverage_evidence": candidate.get("evidence"),
                "source_or_gcov_evidence": line_evidence_for_dimension(
                    inspect_reports,
                    inspection_files,
                    candidate.get("entries", []),
                    max_line_evidence,
                ),
                "path_confidence": "TODO(agent): "
                + " | ".join(confidence_levels or [
                    "confirmed-not-executed",
                    "single-case-increment-confirmed",
                    "edge-covered-path-unknown",
                    "needs-path-instrumentation",
                    "out-of-scope",
                ]),
                "path_signature": {axis: "TODO(agent)" for axis in axes},
                "required_evidence_points": [
                    "TODO(agent): list must-pass line/branch/call/path-marker evidence and current status"
                ],
                "target_semantic": "TODO(agent): map uncovered code to an architecture-visible scenario",
                "scope_status": "TODO(agent): in-scope | out-of-scope | needs target decision",
                "expected_observable": "TODO(agent): register/memory/trap/CSR/vector observable",
                "duplicate_search_terms": duplicate_terms(target, dimension),
                "suggested_test_point_area": handoff.get("suggested_test_point_area", ""),
                "suggested_case_area": handoff.get("suggested_case_area", ""),
                "gate_note": handoff.get("default_gate_note", "needs profile decision"),
                "profile_questions": [
                    "TODO(hyptest-workflow): confirm spec_profile and gate applicability",
                    "TODO(hyptest-workflow): confirm duplicate search before writing cases",
                ],
                "implementation_owner": handoff.get("implementation_owner", "hyptest-workflow"),
                "inspection_files": inspection_files,
                "missing_inspection_files": missing_inspection_files(inspect_reports, inspection_files),
                "representative_entries": candidate.get("entries", []),
                "script_rationale": candidate.get("rationale"),
            }
        )

    return {
        "target_file": target.get("path"),
        "target_name": target.get("name"),
        "target_title": target.get("title"),
        "target_scope_out": target.get("scope_out", []),
        "path_analysis_available": bool(path_analysis),
        "handoff_rule": "This packet is not permission to write cases. Use hyptest-workflow only after the user asks to implement.",
        "selected_candidates": packet_candidates,
    }


def print_markdown(packet: dict[str, Any]) -> None:
    print("## hyptest-workflow handoff packet")
    print()
    print(f"- target_file: `{packet.get('target_file')}`")
    print(f"- target_name: `{packet.get('target_name')}`")
    print(f"- rule: {packet.get('handoff_rule')}")
    print()
    for idx, candidate in enumerate(packet.get("selected_candidates", []), start=1):
        print(f"### Candidate {idx}: {candidate['coverage_dimension']}")
        print()
        print(f"- candidate_name: {candidate['candidate_name']}")
        print(f"- coverage_dimension: {candidate['coverage_dimension']}")
        print(f"- coverage_evidence: {candidate['coverage_evidence']}")
        print(f"- path_confidence: {candidate['path_confidence']}")
        if candidate.get("path_signature"):
            print("- path_signature:")
            for axis, value in candidate["path_signature"].items():
                print(f"  - {axis}: {value}")
        if candidate.get("required_evidence_points"):
            print("- required_evidence_points:")
            for item in candidate["required_evidence_points"]:
                print(f"  - {item}")
        print(f"- target_semantic: {candidate['target_semantic']}")
        print(f"- scope_status: {candidate['scope_status']}")
        print(f"- expected_observable: {candidate['expected_observable']}")
        print(f"- gate_note: {candidate['gate_note']}")
        print(f"- implementation_owner: {candidate['implementation_owner']}")
        print(f"- suggested_test_point_area: `{candidate['suggested_test_point_area']}`")
        print(f"- suggested_case_area: `{candidate['suggested_case_area']}`")
        if candidate["duplicate_search_terms"]:
            print("- duplicate_search_terms: `" + "`, `".join(candidate["duplicate_search_terms"]) + "`")
        if candidate["inspection_files"]:
            print("- inspection_files: `" + "`, `".join(candidate["inspection_files"]) + "`")
        if candidate["missing_inspection_files"]:
            print("- missing_inspection_files: `" + "`, `".join(candidate["missing_inspection_files"][:12]) + "`")
        if candidate["representative_entries"]:
            print("- representative_entries: `" + "`, `".join(candidate["representative_entries"][:8]) + "`")
        if candidate["source_or_gcov_evidence"]:
            print("- source_or_gcov_evidence:")
            for item in candidate["source_or_gcov_evidence"]:
                print(
                    f"  - `{item['gcov_file']}` ({item['evidence_match']}) `{item['function']}` "
                    f"line {item['first_source_line']}: {item['first_evidence']}"
                )
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary-json", required=True, type=Path, help="JSON from analyze_spike_gcov.py")
    parser.add_argument("--inspect-json", type=Path, help="JSON from inspect_gcov_lines.py")
    parser.add_argument("--select", action="append", default=[], help="dimension or entry substring to include; can be repeated")
    parser.add_argument("--top", type=int, default=5, help="max selected candidates")
    parser.add_argument("--max-line-evidence", type=int, default=4, help="line evidence items per candidate")
    parser.add_argument("--json-out", type=Path, help="write packet JSON")
    parser.add_argument("--markdown", action="store_true", help="print markdown")
    args = parser.parse_args()

    summary = json.loads(args.summary_json.read_text(errors="replace"))
    inspect_reports = []
    if args.inspect_json:
        inspect_reports = json.loads(args.inspect_json.read_text(errors="replace"))

    packet = build_packet(
        summary=summary,
        inspect_reports=inspect_reports,
        selected=set(args.select),
        top=args.top,
        max_line_evidence=args.max_line_evidence,
    )

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n")

    if args.markdown or not args.json_out:
        print_markdown(packet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
