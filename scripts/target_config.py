"""Shared target/project-spec helpers for Spike coverage scripts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]


def read_str_list(data: dict[str, Any], field: str) -> list[str]:
    value = data.get(field, [])
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise TypeError(f"target field '{field}' must be a string or list of strings")


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return data


def resolve_project_spec_path(target_path: Path, reference: object) -> Path:
    if not isinstance(reference, str) or not reference:
        raise TypeError("target field 'project_spec' must be a non-empty string")

    ref_path = Path(reference)
    candidates = [ref_path] if ref_path.is_absolute() else [SKILL_ROOT / ref_path, target_path.parent / ref_path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"project_spec `{reference}` does not exist")


def load_target_with_project_spec(path: Path) -> tuple[dict[str, Any], str, Path, dict[str, Any]]:
    target = load_json_object(path)
    project_spec_ref = target.get("project_spec")
    spec_path = resolve_project_spec_path(path, project_spec_ref)
    spec = load_json_object(spec_path)
    return target, str(project_spec_ref), spec_path, spec


def project_spec_rule_map(spec: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    rules = spec.get("unsupported_feature_rules", {})
    if not isinstance(rules, dict):
        return {}
    result: dict[str, dict[str, list[str]]] = {}
    for extension, body in rules.items():
        if not isinstance(extension, str) or not isinstance(body, dict):
            continue
        entry: dict[str, list[str]] = {}
        for key in ("tokens", "summary_exclude_regex", "line_exclude_regex", "scope_warning_regex"):
            value = body.get(key, [])
            if isinstance(value, str):
                entry[key] = [value]
            elif isinstance(value, list) and all(isinstance(item, str) for item in value):
                entry[key] = value
            else:
                entry[key] = []
        result[extension] = entry
    return result


def unsupported_project_rules(spec: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    support = spec.get("isa_profile", {}).get("support", {})
    if not isinstance(support, dict):
        return {}
    rules = project_spec_rule_map(spec)
    return {
        extension: body
        for extension, body in rules.items()
        if str(support.get(extension, "")).upper() == "NO"
    }


def spec_summary_exclude_regex(spec: dict[str, Any]) -> list[str]:
    patterns: list[str] = []
    for body in unsupported_project_rules(spec).values():
        patterns.extend(body.get("summary_exclude_regex", []))
    return list(dict.fromkeys(patterns))


def spec_line_exclude_regex(spec: dict[str, Any]) -> list[str]:
    patterns: list[str] = []
    for body in unsupported_project_rules(spec).values():
        patterns.extend(body.get("line_exclude_regex", []))
    return list(dict.fromkeys(patterns))


def merged_regex_list(target: dict[str, Any], spec: dict[str, Any], field: str) -> list[str]:
    if field == "summary_exclude_regex":
        spec_patterns = spec_summary_exclude_regex(spec)
    elif field == "line_exclude_regex":
        spec_patterns = spec_line_exclude_regex(spec)
    else:
        spec_patterns = []
    return list(dict.fromkeys([*read_str_list(target, field), *spec_patterns]))


def active_target_text(data: dict[str, Any]) -> str:
    active_parts: list[str] = []
    focus = data.get("coverage_focus", {})
    if isinstance(focus, dict):
        for key in ("included_features", "profile", "purpose"):
            value = focus.get(key)
            if isinstance(value, list):
                active_parts.extend(str(item) for item in value)
            elif isinstance(value, str):
                active_parts.append(value)
    active_parts.extend(str(item) for item in data.get("scope_in", []) if isinstance(item, str))
    for field in ("dimensions", "inspection_hints"):
        value = data.get(field, {})
        if isinstance(value, dict):
            for name, items in value.items():
                active_parts.append(str(name))
                if isinstance(items, list):
                    active_parts.extend(str(item) for item in items)
    return " ".join(active_parts).lower()


def unsupported_active_matches(target: dict[str, Any], spec: dict[str, Any]) -> dict[str, list[str]]:
    active_text = active_target_text(target)
    matches: dict[str, list[str]] = {}
    for extension, body in unsupported_project_rules(spec).items():
        tokens = [token for token in body.get("tokens", []) if token.lower() in active_text]
        if tokens:
            matches[extension] = sorted(set(tokens))
    return matches


def compile_scope_warning_patterns(spec: dict[str, Any]) -> list[tuple[str, re.Pattern[str]]]:
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for extension, body in unsupported_project_rules(spec).items():
        for pattern in body.get("scope_warning_regex", []):
            patterns.append((f"project_spec unsupported {extension}", re.compile(pattern, re.IGNORECASE)))
    return patterns
