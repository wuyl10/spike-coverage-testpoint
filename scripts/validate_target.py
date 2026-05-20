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

    return errors, warnings


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
