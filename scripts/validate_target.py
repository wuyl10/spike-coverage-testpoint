#!/usr/bin/env python3
"""Validate a Spike coverage target JSON file.

This checks target structure, regex syntax, dimension item syntax, inspection
hint coverage, and handoff defaults. It does not decide whether a target is
architecturally correct; it only catches configuration mistakes that would make
coverage evidence weaker or harder to hand off.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL = {
    "name",
    "title",
    "description",
    "spec",
    "scope_in",
    "scope_out",
    "summary_include_regex",
    "summary_exclude_prefixes",
    "summary_exclude_regex",
    "line_exclude_regex",
    "line_priority_regex",
    "source_priority",
    "dimensions",
    "inspection_hints",
    "analysis_notes",
    "duplicate_search_terms",
    "handoff_defaults",
}

OPTIONAL_TOP_LEVEL = {
    "path_analysis",
    "special_run_scope",
    "manual_only_dimensions",
    "dimension_metadata",
    "duplicate_search_aliases",
    "coverage_thresholds",
}

REQUIRED_HANDOFF = {
    "suggested_test_point_area",
    "suggested_case_area",
    "default_gate_note",
    "implementation_owner",
}


def is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def check_str_list(data: dict[str, Any], key: str, errors: list[str]) -> None:
    if not is_str_list(data.get(key)):
        errors.append(f"`{key}` must be a list of strings")


def check_regex_list(data: dict[str, Any], key: str, errors: list[str]) -> None:
    check_str_list(data, key, errors)
    if not is_str_list(data.get(key)):
        return
    for pattern in data[key]:
        try:
            re.compile(pattern)
        except re.error as exc:
            errors.append(f"`{key}` regex `{pattern}` does not compile: {exc}")


def check_str_list_map(data: dict[str, Any], key: str, errors: list[str]) -> None:
    value = data.get(key)
    if not isinstance(value, dict):
        errors.append(f"`{key}` must be an object mapping strings to string lists")
        return
    for name, items in value.items():
        if not isinstance(name, str):
            errors.append(f"`{key}` has a non-string key")
        if not is_str_list(items):
            errors.append(f"`{key}.{name}` must be a list of strings")


def check_dimension_metadata(data: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    metadata = data.get("dimension_metadata")
    if metadata is None:
        return
    if not isinstance(metadata, dict):
        errors.append("`dimension_metadata` must be an object when present")
        return

    allowed_keys = {"default_gate_allowed", "requires_runtime_option", "gate_note"}
    for dim, body in metadata.items():
        if not isinstance(dim, str):
            errors.append("`dimension_metadata` has a non-string key")
            continue
        if not isinstance(body, dict):
            errors.append(f"`dimension_metadata.{dim}` must be an object")
            continue
        unknown = sorted(set(body) - allowed_keys)
        if unknown:
            warnings.append(f"`dimension_metadata.{dim}` has unknown fields: " + ", ".join(unknown))
        if "default_gate_allowed" in body and not isinstance(body["default_gate_allowed"], bool):
            errors.append(f"`dimension_metadata.{dim}.default_gate_allowed` must be a boolean")
        if "requires_runtime_option" in body and not isinstance(body["requires_runtime_option"], bool):
            errors.append(f"`dimension_metadata.{dim}.requires_runtime_option` must be a boolean")
        if "gate_note" in body and not isinstance(body["gate_note"], str):
            errors.append(f"`dimension_metadata.{dim}.gate_note` must be a string")


def check_coverage_thresholds(data: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    thresholds = data.get("coverage_thresholds")
    if thresholds is None:
        return
    if not isinstance(thresholds, dict):
        errors.append("`coverage_thresholds` must be an object when present")
        return
    allowed = {"low_line_pct", "low_branch_pct", "low_call_pct"}
    unknown = sorted(set(thresholds) - allowed)
    if unknown:
        warnings.append("`coverage_thresholds` has unknown fields: " + ", ".join(unknown))
    for key in allowed & set(thresholds):
        value = thresholds[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"`coverage_thresholds.{key}` must be a number")
        elif value < 0 or value > 100:
            errors.append(f"`coverage_thresholds.{key}` must be between 0 and 100")


def check_dimension_item(item: str, dim: str, errors: list[str]) -> None:
    if item.startswith("insn:"):
        if item == "insn:" or "/" in item:
            errors.append(f"`dimensions.{dim}` has invalid instruction item `{item}`")
        return
    if item.startswith("glob:"):
        if item == "glob:":
            errors.append(f"`dimensions.{dim}` has empty glob item")
        return
    if not item.startswith("riscv/"):
        errors.append(
            f"`dimensions.{dim}` item `{item}` should be `riscv/...`, `insn:...`, or `glob:...`"
        )


def validate(path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    data = json.loads(path.read_text(errors="replace"))
    if not isinstance(data, dict):
        return ["target root must be a JSON object"], warnings

    missing = sorted(REQUIRED_TOP_LEVEL - set(data))
    if missing:
        errors.append("missing required fields: " + ", ".join(missing))
    unknown = sorted(set(data) - REQUIRED_TOP_LEVEL - OPTIONAL_TOP_LEVEL)
    if unknown:
        warnings.append("unknown top-level fields: " + ", ".join(unknown))

    for key in ("name", "title", "description"):
        if not isinstance(data.get(key), str) or not data.get(key):
            errors.append(f"`{key}` must be a non-empty string")

    spec = data.get("spec")
    if not isinstance(spec, dict):
        errors.append("`spec` must be an object")
    elif "profile" not in spec:
        warnings.append("`spec.profile` is missing; reports will be less clear")

    for key in ("scope_in", "scope_out", "summary_exclude_prefixes", "source_priority", "analysis_notes"):
        check_str_list(data, key, errors)

    for key in ("summary_include_regex", "summary_exclude_regex", "line_exclude_regex", "line_priority_regex"):
        check_regex_list(data, key, errors)

    check_str_list_map(data, "duplicate_search_terms", errors)
    check_str_list_map(data, "inspection_hints", errors)
    if "duplicate_search_aliases" in data:
        check_str_list_map(data, "duplicate_search_aliases", errors)
    if "special_run_scope" in data:
        check_str_list(data, "special_run_scope", errors)
    if "manual_only_dimensions" in data:
        check_str_list(data, "manual_only_dimensions", errors)
    check_dimension_metadata(data, errors, warnings)
    check_coverage_thresholds(data, errors, warnings)

    dimensions = data.get("dimensions")
    if not isinstance(dimensions, dict) or not dimensions:
        errors.append("`dimensions` must be a non-empty object")
    elif all(is_str_list(items) for items in dimensions.values()):
        for dim, items in dimensions.items():
            if not items:
                warnings.append(f"`dimensions.{dim}` is empty")
            for item in items:
                check_dimension_item(item, dim, errors)

        hints = data.get("inspection_hints") if isinstance(data.get("inspection_hints"), dict) else {}
        missing_hints = sorted(set(dimensions) - set(hints))
        if missing_hints:
            warnings.append("dimensions without inspection_hints: " + ", ".join(missing_hints))

        extra_hints = sorted(set(hints) - set(dimensions))
        if extra_hints:
            warnings.append("inspection_hints without matching dimensions: " + ", ".join(extra_hints))
        manual_dims = data.get("manual_only_dimensions", [])
        if is_str_list(manual_dims):
            missing_manual_dims = sorted(set(manual_dims) - set(dimensions))
            if missing_manual_dims:
                warnings.append("manual_only_dimensions without matching dimensions: " + ", ".join(missing_manual_dims))
        metadata = data.get("dimension_metadata", {})
        if isinstance(metadata, dict):
            extra_metadata = sorted(set(metadata) - set(dimensions))
            if extra_metadata:
                warnings.append("dimension_metadata without matching dimensions: " + ", ".join(extra_metadata))
        aliases = data.get("duplicate_search_aliases", {})
        if isinstance(aliases, dict):
            extra_aliases = sorted(set(aliases) - set(dimensions))
            if extra_aliases:
                warnings.append("duplicate_search_aliases without matching dimensions: " + ", ".join(extra_aliases))
            alias_values = {
                alias
                for values in aliases.values()
                if is_str_list(values)
                for alias in values
            }
        else:
            alias_values = set()
        special_scope = data.get("special_run_scope", [])
        if is_str_list(special_scope):
            unmatched_special = sorted(set(special_scope) - set(dimensions) - alias_values)
            if unmatched_special:
                warnings.append(
                    "special_run_scope entries are not exact dimensions or duplicate_search_aliases and will not gate by name: "
                    + ", ".join(unmatched_special)
                )
        terms = data.get("duplicate_search_terms", {})
        if isinstance(terms, dict):
            extra_terms = sorted(set(terms) - set(dimensions))
            if extra_terms:
                warnings.append(
                    "duplicate_search_terms without matching dimensions; use duplicate_search_aliases or document as semantic aliases: "
                    + ", ".join(extra_terms)
                )
    else:
        errors.append("each `dimensions.*` value must be a list of strings")

    handoff = data.get("handoff_defaults")
    if not isinstance(handoff, dict):
        errors.append("`handoff_defaults` must be an object")
    else:
        missing_handoff = sorted(REQUIRED_HANDOFF - set(handoff))
        if missing_handoff:
            errors.append("`handoff_defaults` missing: " + ", ".join(missing_handoff))
        if handoff.get("implementation_owner") != "hyptest-workflow":
            warnings.append("`handoff_defaults.implementation_owner` should usually be `hyptest-workflow`")

    if not data.get("scope_in"):
        warnings.append("`scope_in` is empty; agent will have weak in-scope judgment")
    if not data.get("scope_out"):
        warnings.append("`scope_out` is empty; agent may over-propose out-of-scope tests")

    path_analysis = data.get("path_analysis")
    if path_analysis is not None:
        validate_path_analysis(path_analysis, errors, warnings)

    return errors, warnings


def validate_path_analysis(value: Any, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("`path_analysis` must be an object when present")
        return

    if "combination_axes" in value:
        warnings.append(
            "`path_analysis.combination_axes` is discouraged; prefer evidence_policy and "
            "path_signature_fields so the agent derives paths from source/gcov evidence"
        )

    confidence = value.get("confidence_levels", [])
    if confidence is not None and not is_str_list(confidence):
        errors.append("`path_analysis.confidence_levels` must be a list of strings")
    elif is_str_list(confidence):
        recommended = {
            "confirmed-not-executed",
            "counter-increment-observed",
            "single-case-increment-confirmed",
            "edge-covered-path-unknown",
            "needs-path-instrumentation",
            "out-of-scope",
        }
        missing = sorted(recommended - set(confidence))
        if missing:
            warnings.append("`path_analysis.confidence_levels` missing recommended labels: " + ", ".join(missing))
        stale = sorted({"confirmed-executed", "marker-confirmed"} & set(confidence))
        if stale:
            errors.append("`path_analysis.confidence_levels` contains stale overclaiming labels: " + ", ".join(stale))

    for key in ("evidence_policy", "path_signature_fields"):
        if key in value and not is_str_list(value.get(key)):
            errors.append(f"`path_analysis.{key}` must be a list of strings")
    if not value.get("evidence_policy"):
        warnings.append("`path_analysis.evidence_policy` is missing; path analysis may over-infer")
    if not value.get("path_signature_fields"):
        warnings.append("`path_analysis.path_signature_fields` is missing; handoff path signatures will be sparse")

    markers = value.get("path_markers", {})
    if markers is not None:
        if not isinstance(markers, dict):
            errors.append("`path_analysis.path_markers` must be an object")
        else:
            for marker, body in markers.items():
                if not isinstance(marker, str):
                    errors.append("`path_analysis.path_markers` has a non-string key")
                    continue
                if not isinstance(body, dict):
                    errors.append(f"`path_analysis.path_markers.{marker}` must be an object")
                    continue
                if not isinstance(body.get("meaning", ""), str) or not body.get("meaning"):
                    warnings.append(f"`path_analysis.path_markers.{marker}.meaning` is missing")
                locations = body.get("suggested_locations", [])
                if locations is not None and not is_str_list(locations):
                    errors.append(
                        f"`path_analysis.path_markers.{marker}.suggested_locations` must be a list of strings"
                    )
            policy = value.get("marker_correlation_policy")
            if markers and not policy:
                warnings.append(
                    "`path_analysis.marker_correlation_policy` is missing; marker evidence may overclaim same-flow correlation"
                )
            elif policy is not None and not is_str_list(policy):
                errors.append("`path_analysis.marker_correlation_policy` must be a list of strings")

    single_case = value.get("single_case_increment", {})
    if single_case is not None:
        if not isinstance(single_case, dict):
            errors.append("`path_analysis.single_case_increment` must be an object")
        else:
            for key in ("required_practice", "interpretation"):
                if key in single_case and not is_str_list(single_case.get(key)):
                    errors.append(f"`path_analysis.single_case_increment.{key}` must be a list of strings")
            interpretation = " ".join(single_case.get("interpretation", [])) if is_str_list(single_case.get("interpretation", [])) else ""
            if "counter-increment-observed" not in interpretation:
                warnings.append("`path_analysis.single_case_increment.interpretation` should mention counter-increment-observed downgrade")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="target JSON to validate")
    parser.add_argument("--json", action="store_true", help="print machine-readable result")
    args = parser.parse_args()

    errors, warnings = validate(args.target)
    result = {"target": str(args.target), "errors": errors, "warnings": warnings, "ok": not errors}

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"target: {args.target}")
        if errors:
            print("errors:")
            for item in errors:
                print(f"- {item}")
        if warnings:
            print("warnings:")
            for item in warnings:
                print(f"- {item}")
        if not errors and not warnings:
            print("ok: target looks good")
        elif not errors:
            print("ok: target has warnings only")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
