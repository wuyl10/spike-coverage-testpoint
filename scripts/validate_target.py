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
from string import Formatter
from typing import Any

from target_config import load_json_object, resolve_project_spec_path, unsupported_active_matches

REQUIRED_TOP_LEVEL = {
    "name",
    "title",
    "description",
    "project_spec",
    "coverage_focus",
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
    "scenario_coverage",
    "path_analysis",
    "special_run_scope",
    "manual_only_dimensions",
    "dimension_metadata",
    "duplicate_search_aliases",
    "coverage_thresholds",
}

DEPRECATED_TOP_LEVEL = {
    "spec",
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


def check_project_spec(
    data: dict[str, Any],
    target_path: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    value = data.get("project_spec")
    if not isinstance(value, str) or not value:
        errors.append("`project_spec` must be a non-empty string path to specs/*.json")
        return {}
    if not value.endswith(".json"):
        warnings.append("`project_spec` should usually point to a JSON file under specs/")

    try:
        spec_path = resolve_project_spec_path(target_path, value)
        spec_data = load_json_object(spec_path)
    except FileNotFoundError:
        errors.append(f"`project_spec` path `{value}` does not exist")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"`project_spec` file `{spec_path}` is not valid JSON: {exc}")
        return {}
    except TypeError as exc:
        errors.append(f"`project_spec` file `{spec_path}` must contain a JSON object")
        return {}
    for key in ("name", "title", "description"):
        if not isinstance(spec_data.get(key), str) or not spec_data.get(key):
            warnings.append(f"`project_spec` file `{spec_path}` is missing non-empty `{key}`")
    check_project_spec_coverage_spike(spec_data, spec_path, errors, warnings)
    check_project_spec_rules(spec_data, spec_path, errors, warnings)
    return spec_data


def check_project_spec_coverage_spike(
    spec_data: dict[str, Any],
    spec_path: Path,
    errors: list[str],
    warnings: list[str],
) -> None:
    coverage_spike = spec_data.get("coverage_spike")
    if coverage_spike is None:
        errors.append(
            f"`project_spec` file `{spec_path}` is missing `coverage_spike`; "
            "define project-owned coverage Spike defaults or pass --command-template explicitly for special runs"
        )
        return
    if not isinstance(coverage_spike, dict):
        errors.append(f"`project_spec` file `{spec_path}` has non-object `coverage_spike`")
        return

    allowed_fields = {"default_isa", "default_priv", "default_args", "notes"}
    unknown = sorted(set(coverage_spike) - allowed_fields)
    if unknown:
        warnings.append(f"`project_spec.coverage_spike` in `{spec_path}` has unknown fields: " + ", ".join(unknown))

    for key in ("default_isa", "default_priv"):
        if key in coverage_spike and not isinstance(coverage_spike[key], str):
            errors.append(f"`project_spec.coverage_spike.{key}` in `{spec_path}` must be a string")
        elif key in coverage_spike and not coverage_spike[key]:
            warnings.append(f"`project_spec.coverage_spike.{key}` in `{spec_path}` is empty")

    notes = coverage_spike.get("notes", [])
    if notes is not None and not is_str_list(notes):
        errors.append(f"`project_spec.coverage_spike.notes` in `{spec_path}` must be a list of strings")

    raw_args = coverage_spike.get("default_args", [])
    if isinstance(raw_args, str):
        default_args = [raw_args]
    elif isinstance(raw_args, list) and all(isinstance(item, str) for item in raw_args):
        default_args = raw_args
    else:
        errors.append(
            f"`project_spec.coverage_spike.default_args` in `{spec_path}` must be a string or list of strings"
        )
        return

    if not default_args:
        errors.append(
            f"`project_spec.coverage_spike.default_args` in `{spec_path}` is empty; "
            "the case matrix runner needs project-owned default Spike args when --command-template is omitted"
        )
        return

    scalar_fields = {
        key
        for key, value in coverage_spike.items()
        if isinstance(value, (str, int, float)) and not isinstance(value, bool)
    }
    simple_name_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    for raw_arg in default_args:
        try:
            parsed_fields = [field_name for _, field_name, _, _ in Formatter().parse(raw_arg)]
        except ValueError as exc:
            errors.append(
                f"`project_spec.coverage_spike.default_args` item `{raw_arg}` in `{spec_path}` "
                f"has invalid format syntax: {exc}"
            )
            continue
        for field_name in parsed_fields:
            if field_name is None:
                continue
            if not simple_name_re.match(field_name):
                errors.append(
                    f"`project_spec.coverage_spike.default_args` item `{raw_arg}` in `{spec_path}` "
                    f"uses unsupported placeholder `{{{field_name}}}`; use a simple scalar field name"
                )
                continue
            if field_name not in scalar_fields:
                errors.append(
                    f"`project_spec.coverage_spike.default_args` item `{raw_arg}` in `{spec_path}` "
                    f"references unknown scalar field `{{{field_name}}}`"
                )


def check_project_spec_rules(
    spec_data: dict[str, Any],
    spec_path: Path,
    errors: list[str],
    warnings: list[str],
) -> None:
    support = spec_data.get("isa_profile", {}).get("support", {})
    if support is not None and not isinstance(support, dict):
        errors.append(f"`project_spec` file `{spec_path}` has non-object `isa_profile.support`")
        support = {}

    rules = spec_data.get("unsupported_feature_rules", {})
    if rules is None:
        return
    if not isinstance(rules, dict):
        errors.append(f"`project_spec` file `{spec_path}` has non-object `unsupported_feature_rules`")
        return

    rule_fields = {"tokens", "summary_exclude_regex", "line_exclude_regex", "scope_warning_regex"}
    regex_fields = {"summary_exclude_regex", "line_exclude_regex", "scope_warning_regex"}
    for extension, body in rules.items():
        rule_name = f"`project_spec.unsupported_feature_rules.{extension}`"
        if not isinstance(extension, str) or not extension:
            errors.append(f"`project_spec` file `{spec_path}` has an invalid unsupported-feature rule name")
            continue
        if not isinstance(body, dict):
            errors.append(f"{rule_name} must be an object")
            continue

        status = str(support.get(extension, "")).upper()
        if status and status != "NO":
            warnings.append(f"{rule_name} is defined but isa_profile.support marks {extension}={status}")
        elif not status:
            warnings.append(f"{rule_name} is defined but {extension} is missing from isa_profile.support")

        unknown = sorted(set(body) - rule_fields)
        if unknown:
            warnings.append(f"{rule_name} has unknown fields: " + ", ".join(unknown))

        for field in rule_fields:
            value = body.get(field, [])
            if isinstance(value, str):
                values = [value]
            elif isinstance(value, list) and all(isinstance(item, str) for item in value):
                values = value
            else:
                errors.append(f"{rule_name}.{field} must be a string or list of strings")
                continue
            if field == "tokens" and not values:
                warnings.append(f"{rule_name}.tokens is empty; target active-scope checks will be weak")
            if field in regex_fields:
                for pattern in values:
                    try:
                        re.compile(pattern)
                    except re.error as exc:
                        errors.append(f"{rule_name}.{field} regex `{pattern}` does not compile: {exc}")


def check_coverage_focus(data: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    focus = data.get("coverage_focus")
    if not isinstance(focus, dict):
        errors.append("`coverage_focus` must be an object")
        return
    if not isinstance(focus.get("profile"), str) or not focus.get("profile"):
        warnings.append("`coverage_focus.profile` is missing; reports will be less clear")
    if "purpose" in focus and not isinstance(focus.get("purpose"), str):
        errors.append("`coverage_focus.purpose` must be a string")
    for key in ("included_features", "excluded_features", "notes"):
        if key in focus and not is_str_list(focus.get(key)):
            errors.append(f"`coverage_focus.{key}` must be a list of strings")
    deprecated = sorted(
        {"included_extensions_or_features", "excluded_extensions_or_features", "source_of_truth"} & set(focus)
    )
    if deprecated:
        errors.append(
            "`coverage_focus` contains old spec field names; use included_features/excluded_features/purpose instead: "
            + ", ".join(deprecated)
        )


def check_project_spec_exclusions(data: dict[str, Any], spec_data: dict[str, Any], errors: list[str]) -> None:
    for extension, matched in unsupported_active_matches(data, spec_data).items():
        errors.append(
            f"`project_spec` marks {extension}=NO but target active scope/dimensions include: "
            + ", ".join(matched)
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
    deprecated = sorted(DEPRECATED_TOP_LEVEL & set(data))
    if deprecated:
        errors.append(
            "deprecated top-level fields are no longer allowed; use `project_spec` plus `coverage_focus`: "
            + ", ".join(deprecated)
        )
    unknown = sorted(set(data) - REQUIRED_TOP_LEVEL - OPTIONAL_TOP_LEVEL - DEPRECATED_TOP_LEVEL)
    if unknown:
        warnings.append("unknown top-level fields: " + ", ".join(unknown))

    for key in ("name", "title", "description"):
        if not isinstance(data.get(key), str) or not data.get(key):
            errors.append(f"`{key}` must be a non-empty string")

    spec_data = check_project_spec(data, path, errors, warnings)
    check_coverage_focus(data, errors, warnings)
    if spec_data:
        check_project_spec_exclusions(data, spec_data, errors)

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

    scenario_coverage = data.get("scenario_coverage")
    if scenario_coverage is not None:
        validate_scenario_coverage(scenario_coverage, errors, warnings)

    path_analysis = data.get("path_analysis")
    if path_analysis is not None:
        validate_path_analysis(path_analysis, errors, warnings)

    return errors, warnings


def validate_scenario_coverage(value: Any, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("`scenario_coverage` must be an object when present")
        return

    discouraged = sorted({"combination_axes", "cartesian_product", "full_matrix"} & set(value))
    if discouraged:
        warnings.append(
            "`scenario_coverage` should not define blind scenario matrices; discouraged fields: "
            + ", ".join(discouraged)
        )

    allowed = {"purpose", "scenario_axes", "evidence_policy", "priority_scenarios"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        warnings.append("`scenario_coverage` has unknown fields: " + ", ".join(unknown))

    if "purpose" in value and not isinstance(value.get("purpose"), str):
        errors.append("`scenario_coverage.purpose` must be a string")
    for key in ("scenario_axes", "evidence_policy", "priority_scenarios"):
        if key in value and not is_str_list(value.get(key)):
            errors.append(f"`scenario_coverage.{key}` must be a list of strings")

    axes = value.get("scenario_axes", [])
    if not axes:
        warnings.append("`scenario_coverage.scenario_axes` is missing; final reports may drift back to counter-only gaps")
    elif is_str_list(axes):
        joined_axes = " ".join(axes).lower()
        recommended_terms = {
            "instruction/access": ("instruction", "access"),
            "profile/gate": ("profile", "gate", "privilege"),
            "condition": ("condition", "translation", "protection", "device", "exception"),
            "observable": ("observable", "assert"),
        }
        for label, terms in recommended_terms.items():
            if not any(term in joined_axes for term in terms):
                warnings.append(f"`scenario_coverage.scenario_axes` may be missing {label} axis")

    policy = value.get("evidence_policy", [])
    if not policy:
        warnings.append("`scenario_coverage.evidence_policy` is missing; agent may over-treat counters as goals")
    elif is_str_list(policy):
        joined_policy = " ".join(policy).lower()
        if "cartesian" in joined_policy and "do not" not in joined_policy and "not" not in joined_policy:
            warnings.append("`scenario_coverage.evidence_policy` mentions Cartesian products without a clear guardrail")
        if not any(term in joined_policy for term in ("line", "branch", "call", "counter", "coverage")):
            warnings.append("`scenario_coverage.evidence_policy` should state that coverage counters are supporting evidence")


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
