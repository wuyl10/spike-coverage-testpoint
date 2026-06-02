#!/usr/bin/env python3
"""Validate a Spike coverage project spec JSON file.

Project specs define implementation-level facts shared by targets: environment
interfaces, coverage Spike defaults, support matrix rows, and unsupported
feature filters. This checker catches structural mistakes before targets depend
on the spec.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from target_config import load_json_object
from validate_target import check_project_spec_coverage_spike, check_project_spec_rules, is_str_list


REQUIRED_TOP_LEVEL = {
    "name",
    "title",
    "description",
    "environment",
    "implementation_model",
    "coverage_spike",
    "isa_profile",
    "available_implementation_features",
    "excluded_implementation_features",
    "target_policy",
}

OPTIONAL_TOP_LEVEL = {
    "memblock_relevant_constraints",
    "unsupported_feature_rules",
    "notes",
}


def check_string_field(data: dict[str, Any], key: str, errors: list[str]) -> None:
    if not isinstance(data.get(key), str) or not data.get(key):
        errors.append(f"`{key}` must be a non-empty string")


def check_str_map(data: dict[str, Any], key: str, errors: list[str]) -> None:
    value = data.get(key)
    if not isinstance(value, dict) or not value:
        errors.append(f"`{key}` must be a non-empty object")
        return
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not item_key:
            errors.append(f"`{key}` has an invalid key")
        if not isinstance(item_value, str) or not item_value:
            errors.append(f"`{key}.{item_key}` must be a non-empty string")


def check_isa_profile(data: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    profile = data.get("isa_profile")
    if not isinstance(profile, dict):
        errors.append("`isa_profile` must be an object")
        return

    if not isinstance(profile.get("profile_name"), str) or not profile.get("profile_name"):
        errors.append("`isa_profile.profile_name` must be a non-empty string")

    status_values = profile.get("status_values", [])
    if not is_str_list(status_values) or not status_values:
        errors.append("`isa_profile.status_values` must be a non-empty list of strings")
        status_set: set[str] = set()
    else:
        status_set = {item.upper() for item in status_values}
        for required in ("YES", "NO", "UNKNOWN"):
            if required not in status_set:
                warnings.append(f"`isa_profile.status_values` does not include {required}")

    support = profile.get("support")
    if not isinstance(support, dict) or not support:
        errors.append("`isa_profile.support` must be a non-empty object")
        return
    for extension, status in support.items():
        if not isinstance(extension, str) or not extension:
            errors.append("`isa_profile.support` has an invalid extension name")
            continue
        if not isinstance(status, str) or not status:
            errors.append(f"`isa_profile.support.{extension}` must be a non-empty string")
            continue
        if status_set and status.upper() not in status_set:
            errors.append(f"`isa_profile.support.{extension}` has status `{status}` outside status_values")

    unclear = profile.get("image_rows_with_unclear_status", [])
    if unclear is not None and not is_str_list(unclear):
        errors.append("`isa_profile.image_rows_with_unclear_status` must be a list of strings when present")
    elif is_str_list(unclear):
        support_map = {str(k): str(v).upper() for k, v in support.items()}
        unexpected = sorted(item for item in unclear if support_map.get(item) != "UNKNOWN")
        if unexpected:
            warnings.append(
                "`isa_profile.image_rows_with_unclear_status` entries are not marked UNKNOWN: "
                + ", ".join(unexpected)
            )


def validate(path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        data = load_json_object(path)
    except json.JSONDecodeError as exc:
        return [f"spec file is not valid JSON: {exc}"], warnings
    except TypeError as exc:
        return [str(exc)], warnings

    missing = sorted(REQUIRED_TOP_LEVEL - set(data))
    if missing:
        errors.append("missing required fields: " + ", ".join(missing))
    unknown = sorted(set(data) - REQUIRED_TOP_LEVEL - OPTIONAL_TOP_LEVEL)
    if unknown:
        warnings.append("unknown top-level fields: " + ", ".join(unknown))

    for key in ("name", "title", "description"):
        check_string_field(data, key, errors)
    check_str_map(data, "environment", errors)
    check_str_map(data, "implementation_model", errors)
    check_project_spec_coverage_spike(data, path, errors, warnings)
    check_isa_profile(data, errors, warnings)
    check_project_spec_rules(data, path, errors, warnings)

    for key in (
        "available_implementation_features",
        "excluded_implementation_features",
        "target_policy",
        "notes",
        "memblock_relevant_constraints",
    ):
        if key in data and not is_str_list(data.get(key)):
            errors.append(f"`{key}` must be a list of strings")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="project spec JSON to validate")
    parser.add_argument("--json", action="store_true", help="print machine-readable result")
    args = parser.parse_args()

    errors, warnings = validate(args.spec)
    result = {"spec": str(args.spec), "errors": errors, "warnings": warnings, "ok": not errors}

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"spec: {args.spec}")
        if errors:
            print("errors:")
            for item in errors:
                print(f"- {item}")
        if warnings:
            print("warnings:")
            for item in warnings:
                print(f"- {item}")
        if not errors and not warnings:
            print("ok: spec looks good")
        elif not errors:
            print("ok: spec has warnings only")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
