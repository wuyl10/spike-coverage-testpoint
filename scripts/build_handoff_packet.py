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


def gcov_basename_for_entry(entry: str) -> str:
    return Path(entry).name + ".gcov"


def is_instruction_entry(entry: str) -> bool:
    cleaned = entry
    while cleaned.startswith("../"):
        cleaned = cleaned[3:]
    return cleaned.startswith("riscv/insns/")


def needs_agent(reason: str) -> str:
    return f"needs source confirmation: {reason}"


def candidate_search_text(candidate: dict[str, Any], target: dict[str, Any]) -> str:
    dim = str(candidate.get("dimension", ""))
    parts = [dim]
    parts.extend(str(item) for item in candidate.get("entries", []))
    parts.extend(str(item) for item in candidate.get("inspection_files", []))
    for key in ("duplicate_search_terms", "duplicate_search_aliases", "inspection_hints"):
        mapping = target.get(key, {})
        if isinstance(mapping, dict):
            values = mapping.get(dim, [])
            if isinstance(values, list):
                parts.extend(str(item) for item in values)
    metadata = target.get("dimension_metadata", {})
    if isinstance(metadata, dict) and isinstance(metadata.get(dim), dict):
        parts.extend(str(value) for value in metadata[dim].values())
    return " ".join(parts).lower()


def candidate_matches(candidate: dict[str, Any], selected: set[str], target: dict[str, Any]) -> bool:
    if not selected:
        return True
    haystack = candidate_search_text(candidate, target)
    return any(item.lower() in haystack for item in selected)


def line_evidence_for_dimension(
    inspect_reports: list[dict[str, Any]],
    inspection_files: list[str],
    representative_entries: list[str],
    dimension: str,
    duplicate_search_terms: list[str],
    max_items: int,
) -> list[dict[str, Any]]:
    representative_gcov = {gcov_basename_for_entry(entry) for entry in representative_entries}
    wanted = {Path(item).name for item in inspection_files} | representative_gcov
    exact_wanted = wanted & representative_gcov
    semantic_terms = [
        term.lower()
        for term in [dimension, *duplicate_search_terms, *[short_name(entry) for entry in representative_entries]]
        if term
    ]
    entry_kind_by_gcov = {
        gcov_basename_for_entry(entry): "instruction-entry" if is_instruction_entry(entry) else "shared-source-entry"
        for entry in representative_entries
    }

    def report_rank(report: dict[str, Any]) -> tuple[int, str]:
        gcov_name = Path(report.get("gcov_file", "")).name
        if gcov_name in exact_wanted and entry_kind_by_gcov.get(gcov_name) == "shared-source-entry":
            return (0, gcov_name)
        if gcov_name in exact_wanted:
            return (1, gcov_name)
        if gcov_name in representative_gcov:
            return (2, gcov_name)
        if gcov_name in wanted and ".h.gcov" in gcov_name:
            return (3, gcov_name)
        if gcov_name in wanted:
            return (4, gcov_name)
        return (5, gcov_name)

    ordered_reports = sorted(
        inspect_reports,
        key=report_rank,
    )

    def classify_report(gcov_name: str) -> tuple[str, str]:
        if gcov_name in representative_gcov:
            if entry_kind_by_gcov.get(gcov_name) == "instruction-entry":
                return "exact-instruction-entry", "exact instruction entry .gcov was inspected"
            return "exact-shared-source-entry", "exact shared/source entry .gcov was inspected"
        if gcov_name in wanted:
            if any(term and term in gcov_name.lower() for term in semantic_terms):
                return "dimension-shared-source", "inspection file name matches dimension or semantic terms"
            return "inspection-hint-weak", "inspection file came from target hints, not an exact entry match"
        return "unmatched-inspect-report", "inspect report was not requested for this candidate"

    def function_matches_semantic_terms(fn: dict[str, Any]) -> bool:
        haystack_parts = [str(fn.get("name") or ""), str(fn.get("mangled_name") or "")]
        for event in fn.get("events", []):
            haystack_parts.append(str(event.get("text") or ""))
            haystack_parts.append(str(event.get("source_code") or ""))
        haystack = " ".join(haystack_parts).lower()
        return any(term and term in haystack for term in semantic_terms)

    def collect(allow_shared: bool, prefer_semantic: bool, limit: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for report in ordered_reports:
            gcov_name = Path(report.get("gcov_file", "")).name
            if wanted and gcov_name not in wanted:
                continue
            exact = gcov_name in exact_wanted or gcov_name in representative_gcov
            if not allow_shared and not exact:
                continue
            functions = report.get("functions", [])
            if prefer_semantic:
                matching = [fn for fn in functions if function_matches_semantic_terms(fn)]
                if matching:
                    functions = matching
            evidence_strength, strength_reason = classify_report(gcov_name)
            for fn in functions[:limit]:
                events = fn.get("events", [])
                first = next((event for event in events if event.get("source_line") is not None), None)
                counts: dict[str, int] = {}
                for event in events:
                    counts[event.get("kind", "unknown")] = counts.get(event.get("kind", "unknown"), 0) + 1
                results.append(
                    {
                        "gcov_file": gcov_name,
                        "evidence_match": "representative-entry" if exact else "inspection-hint",
                        "evidence_strength": evidence_strength,
                        "strength_reason": strength_reason,
                        "semantic_term_match": function_matches_semantic_terms(fn),
                        "function": fn.get("name"),
                        "first_source_line": first.get("source_line") if first else None,
                        "first_evidence": first.get("text") if first else None,
                        "miss_kinds": counts,
                    }
                )
                if len(results) >= limit:
                    return results
        return results

    exact_results = collect(allow_shared=False, prefer_semantic=False, limit=max(1, max_items // 2))
    shared_results = collect(allow_shared=True, prefer_semantic=True, limit=max_items)
    combined: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int | None, str | None]] = set()
    for item in exact_results + shared_results:
        key = (
            str(item.get("gcov_file")),
            str(item.get("function")),
            item.get("first_source_line"),
            str(item.get("first_evidence")),
        )
        if key not in seen:
            combined.append(item)
            seen.add(key)
        if len(combined) >= max_items:
            return combined
    if combined:
        return combined
    return collect(allow_shared=True, prefer_semantic=False, limit=max_items)


def line_evidence_status(
    evidence: list[dict[str, Any]],
    inspection_files: list[str],
    missing_files: list[str],
) -> str:
    if missing_files and not evidence:
        return "unreviewed-missing-files"
    strengths = {item.get("evidence_strength") for item in evidence}
    if "exact-shared-source-entry" in strengths:
        return "exact-shared-source-evidence"
    if "exact-instruction-entry" in strengths and (
        "dimension-shared-source" in strengths or "exact-shared-source-entry" in strengths
    ):
        return "instruction-entry-plus-shared-source-evidence"
    if "exact-instruction-entry" in strengths:
        return "exact-instruction-entry-evidence"
    if "dimension-shared-source" in strengths:
        return "dimension-shared-source-evidence"
    if evidence:
        return "weak-inspection-hint-only"
    if inspection_files:
        return "no-line-evidence-from-requested-files"
    return "no-line-evidence-requested"


def do_not_finalize_without(status: str, missing_files: list[str]) -> list[str]:
    items: list[str] = []
    if status in {
        "exact-instruction-entry-evidence",
        "weak-inspection-hint-only",
        "no-line-evidence-from-requested-files",
        "unreviewed-missing-files",
    }:
        items.append("inspect exact entry .gcov files or source-priority shared files for this candidate")
    if missing_files:
        items.append("inspect missing files: " + ", ".join(missing_files[:8]))
    return items


def same_flow_evidence_stub(candidate: dict[str, Any], evidence_status: str) -> dict[str, str]:
    has_low_branch = bool(candidate.get("low_branch_entries"))
    has_low_call = bool(candidate.get("low_call_entries"))
    has_zero = bool(candidate.get("zero_entries"))
    if has_zero:
        status = "suite-summary-gap"
        reason = "one or more candidate entries are zero in suite coverage; agent must confirm whether they are must-pass points for this path"
        basis = "summary-zero-entry"
    elif has_low_branch or has_low_call:
        status = "aggregate-only"
        reason = "line/branch/call counters are suite-level evidence; same-flow correlation needs single-case increment or path markers"
        basis = "summary-low-branch-or-call"
    else:
        status = "none"
        reason = "candidate has no path-correlation evidence in the handoff packet"
        basis = "no-path-evidence"
    if evidence_status in {"exact-instruction-entry-evidence", "weak-inspection-hint-only"}:
        reason += "; current line evidence is not enough to prove shared MemBlock source flow"
    return {
        "status": status,
        "basis": basis,
        "reason": reason,
        "required_to_upgrade": "single-case-increment-confirmed or marker-correlated evidence with pc+insn/seq/access_id",
    }


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


def infer_profile_from_entries(entries: list[str], dimension: str) -> dict[str, Any]:
    haystack = " ".join([dimension, *entries]).lower()
    rules = [
        ("V", ("riscv/insns/v", " vector ", "vector")),
        ("A / Zaamo / Zalrsc", ("amo", "amocas", "lr_", "sc_")),
        ("C / Zc*", ("riscv/insns/c_", " compressed ", "compressed")),
        ("F/D/Q/Zfh family", ("riscv/insns/fl", "riscv/insns/fs", " fp ", "floating")),
        ("Zicbom/Zicboz/Zicbop family", ("cbo_", "cbo/", "cbo")),
        ("S-mode translation", ("sfence_vma", "satp", "pte", "tlb", "stage1")),
        ("Debug/trigger", ("trigger", "mcontrol", "debug")),
    ]
    matched = [name for name, needles in rules if any(needle in haystack for needle in needles)]
    return {
        "extension_required_inferred": matched or ["unknown"],
        "inference_basis": "rough inference from coverage dimension and representative entries",
        "needs_agent_profile_confirmation": True,
    }


def profile_gate_stub(candidate: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    spec = target.get("spec", {}) if isinstance(target.get("spec"), dict) else {}
    included = spec.get("included_extensions_or_features", [])
    excluded = spec.get("excluded_extensions_or_features", [])
    if not isinstance(included, list):
        included = []
    if not isinstance(excluded, list):
        excluded = []
    spec_profile = spec.get("profile", "")
    entries = ", ".join(candidate.get("entries", [])[:4])
    class_note = candidate.get("evidence_class", "unknown")
    inferred = infer_profile_from_entries(candidate.get("entries", []), str(candidate.get("dimension", "")))
    dimension_gate = candidate.get("dimension_gate", {}) if isinstance(candidate.get("dimension_gate"), dict) else {}
    gate_note = dimension_gate.get("gate_note") if isinstance(dimension_gate.get("gate_note"), str) else ""
    manual_only = bool(dimension_gate.get("manual_only"))
    default_allowed = dimension_gate.get("default_gate_allowed")
    default_gate_eligible = needs_agent(
        "yes/no/unknown after confirming feature availability and deterministic observable"
    )
    if manual_only or default_allowed is False:
        default_gate_eligible = "no - target dimension is manual/special-run by target metadata"
    return {
        "extension_required": needs_agent(
            "infer required ISA/profile feature from source and representative entries"
            + (f" ({entries})" if entries else "")
        ),
        **inferred,
        "current_profile_evidence": (
            f"target spec profile={spec_profile or 'unspecified'}; "
            f"included={included}; excluded={excluded}"
        ),
        "default_gate_eligible": default_gate_eligible,
        "profile_gate_note": (
            (gate_note + "; " if gate_note else "")
            + f"evidence_class={class_note}; do not recommend default gate until profile and "
            "platform observability are checked"
        ),
    }


def gate_note_for_candidate(candidate: dict[str, Any], handoff: dict[str, Any]) -> str:
    dimension_gate = candidate.get("dimension_gate", {}) if isinstance(candidate.get("dimension_gate"), dict) else {}
    gate_note = dimension_gate.get("gate_note") if isinstance(dimension_gate.get("gate_note"), str) else ""
    if dimension_gate.get("manual_only") or dimension_gate.get("default_gate_allowed") is False:
        return gate_note or "manual/special-run"
    return handoff.get("default_gate_note", "needs profile decision")


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
    signature_fields = (
        path_analysis.get("path_signature_fields", [])
        if isinstance(path_analysis.get("path_signature_fields"), list)
        else []
    )
    confidence_levels = (
        path_analysis.get("confidence_levels", [])
        if isinstance(path_analysis.get("confidence_levels"), list)
        else []
    )
    candidates = [
        candidate
        for candidate in summary.get("candidates", [])
            if candidate_matches(candidate, selected, summary.get("target", {}))
    ][:top]

    packet_candidates = []
    for candidate in candidates:
        dimension = candidate.get("dimension", "")
        inspection_files = candidate.get("inspection_files", [])
        duplicate_search_terms = duplicate_terms(target, dimension)
        line_evidence = line_evidence_for_dimension(
            inspect_reports,
            inspection_files,
            candidate.get("entries", []),
            dimension,
            duplicate_search_terms,
            max_line_evidence,
        )
        missing_files = missing_inspection_files(inspect_reports, inspection_files)
        evidence_status = line_evidence_status(line_evidence, inspection_files, missing_files)
        same_flow_evidence = same_flow_evidence_stub(candidate, evidence_status)
        packet_candidates.append(
            {
                "candidate_name": needs_agent(f"interpret {dimension} as an architecture-visible scenario"),
                "coverage_dimension": dimension,
                "evidence_class": candidate.get("evidence_class", "unknown"),
                "evidence_class_reason": candidate.get("evidence_class_reason", ""),
                "classification_confidence": candidate.get("classification_confidence", ""),
                "coverage_evidence": candidate.get("evidence"),
                "line_evidence_status": evidence_status,
                "source_or_gcov_evidence": line_evidence,
                "do_not_finalize_without": do_not_finalize_without(evidence_status, missing_files),
                "dimension_gate": candidate.get("dimension_gate", {}),
                "same_flow_evidence": same_flow_evidence,
                "path_confidence": needs_agent(
                    "choose one after evidence review: "
                    + " | ".join(
                        confidence_levels
                        or [
                            "confirmed-not-executed",
                            "counter-increment-observed",
                            "single-case-increment-confirmed",
                            "edge-covered-path-unknown",
                            "needs-path-instrumentation",
                            "out-of-scope",
                        ]
                    )
                ),
                "path_signature": {
                    field: needs_agent("derive this field from source/gcov/path-marker evidence")
                    for field in signature_fields
                },
                "required_evidence_points": [
                    needs_agent("list must-pass line/branch/call/path-marker evidence and current status")
                ],
                "target_semantic": needs_agent("map uncovered code to an architecture-visible scenario"),
                "scope_status": needs_agent("in-scope | out-of-scope | needs target decision"),
                "expected_observable": needs_agent("register/memory/trap/CSR/vector observable"),
                "profile_gate": profile_gate_stub(candidate, target),
                "duplicate_search_terms": duplicate_search_terms,
                "suggested_test_point_area": handoff.get("suggested_test_point_area", ""),
                "suggested_case_area": handoff.get("suggested_case_area", ""),
                "gate_note": gate_note_for_candidate(candidate, handoff),
                "profile_questions": [
                    "hyptest-workflow must confirm spec_profile and gate applicability before writing cases",
                    "hyptest-workflow must confirm duplicate search before writing cases",
                ],
                "implementation_owner": handoff.get("implementation_owner", "hyptest-workflow"),
                "inspection_files": inspection_files,
                "missing_inspection_files": missing_files,
                "representative_entries": candidate.get("entries", []),
                "entry_selection_reason": candidate.get("entry_selection_reason", ""),
                "zero_entries": candidate.get("zero_entries", []),
                "low_line_entries": candidate.get("low_line_entries", []),
                "low_branch_entries": candidate.get("low_branch_entries", []),
                "low_call_entries": candidate.get("low_call_entries", []),
                "missing_entries": candidate.get("missing_entries", []),
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
        print(f"- evidence_class: {candidate['evidence_class']}")
        if candidate.get("evidence_class_reason"):
            print(f"- evidence_class_reason: {candidate['evidence_class_reason']}")
        if candidate.get("classification_confidence"):
            print(f"- classification_confidence: {candidate['classification_confidence']}")
        print(f"- coverage_evidence: {candidate['coverage_evidence']}")
        if candidate.get("entry_selection_reason"):
            print(f"- entry_selection_reason: {candidate['entry_selection_reason']}")
        print(f"- line_evidence_status: {candidate['line_evidence_status']}")
        if candidate.get("same_flow_evidence"):
            print("- same_flow_evidence:")
            for key, value in candidate["same_flow_evidence"].items():
                print(f"  - {key}: {value}")
        print(f"- path_confidence: {candidate['path_confidence']}")
        if candidate.get("dimension_gate"):
            print("- dimension_gate:")
            for key, value in candidate["dimension_gate"].items():
                print(f"  - {key}: {value}")
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
        if candidate.get("profile_gate"):
            print("- profile_gate:")
            for key, value in candidate["profile_gate"].items():
                print(f"  - {key}: {value}")
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
        if candidate["do_not_finalize_without"]:
            print("- do_not_finalize_without:")
            for item in candidate["do_not_finalize_without"]:
                print(f"  - {item}")
        if candidate["representative_entries"]:
            print("- representative_entries: `" + "`, `".join(candidate["representative_entries"][:8]) + "`")
        for field in ("zero_entries", "low_line_entries", "low_branch_entries", "low_call_entries"):
            if candidate.get(field):
                print(f"- {field}: `" + "`, `".join(candidate[field][:8]) + "`")
        if candidate.get("missing_entries"):
            print("- missing_entries: `" + "`, `".join(candidate["missing_entries"][:8]) + "`")
        if candidate["source_or_gcov_evidence"]:
            print("- source_or_gcov_evidence:")
            for item in candidate["source_or_gcov_evidence"]:
                print(
                    f"  - `{item['gcov_file']}` ({item['evidence_strength']}, {item['evidence_match']}) "
                    f"`{item['function']}` "
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
