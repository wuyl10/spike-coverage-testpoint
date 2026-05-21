#!/usr/bin/env python3
"""Summarize Spike gcov output by a target-defined coverage scope.

The script parses text produced by `gcov -b -c`, groups relevant Spike files by
the dimensions in a target JSON file, and prints either markdown or JSON. It
only extracts and ranks coverage evidence; it does not decide architecture
meaning or test-point value.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


@dataclass
class Entry:
    file: str
    name: str
    line_pct: float | None = None
    lines: int = 0
    branch_pct: float | None = None
    branches: int = 0
    call_pct: float | None = None
    calls: int = 0


@dataclass
class EvidenceCandidate:
    score: float
    dimension: str
    evidence_class: str
    evidence_class_reason: str
    classification_confidence: str
    entry_file_count: int
    shared_source_file_count: int
    inspection_hint_file_count: int
    evidence: str
    entries: list[str]
    rationale: str
    inspection_files: list[str]


@dataclass
class Target:
    path: str | None
    name: str
    title: str
    description: str
    spec: dict[str, Any]
    scope_in: list[str]
    scope_out: list[str]
    summary_include_regex: list[str]
    summary_exclude_prefixes: list[str]
    summary_exclude_regex: list[str]
    line_exclude_regex: list[str]
    dimensions: dict[str, list[str]]
    analysis_notes: list[str]
    duplicate_search_terms: dict[str, list[str]]
    source_priority: list[str]
    inspection_hints: dict[str, list[str]]
    handoff_defaults: dict[str, Any]
    path_analysis: dict[str, Any]


def as_str_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise TypeError(f"{field} must be a string or list of strings")


def as_str_list_map(value: object, field: str) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be an object mapping strings to string lists")
    result: dict[str, list[str]] = {}
    for key, items in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{field} keys must be strings")
        result[key] = as_str_list(items, f"{field}.{key}")
    return result


def as_object(value: object, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    raise TypeError(f"{field} must be an object")


def load_target(path: Path) -> Target:
    data = json.loads(path.read_text(errors="replace"))
    dimensions_raw = data.get("dimensions", {})
    if not isinstance(dimensions_raw, dict):
        raise TypeError("target field 'dimensions' must be an object")

    dimensions: dict[str, list[str]] = {}
    for name, items in dimensions_raw.items():
        if not isinstance(name, str):
            raise TypeError("dimension names must be strings")
        dimensions[name] = as_str_list(items, f"dimensions.{name}")

    return Target(
        path=str(path),
        name=str(data.get("name") or path.stem),
        title=str(data.get("title") or data.get("name") or path.stem),
        description=str(data.get("description") or ""),
        spec=as_object(data.get("spec"), "spec"),
        scope_in=as_str_list(data.get("scope_in"), "scope_in"),
        scope_out=as_str_list(data.get("scope_out"), "scope_out"),
        summary_include_regex=as_str_list(
            data.get("summary_include_regex", [r"^riscv/"]),
            "summary_include_regex",
        ),
        summary_exclude_prefixes=as_str_list(
            data.get("summary_exclude_prefixes"),
            "summary_exclude_prefixes",
        ),
        summary_exclude_regex=as_str_list(
            data.get("summary_exclude_regex"),
            "summary_exclude_regex",
        ),
        line_exclude_regex=as_str_list(
            data.get("line_exclude_regex"),
            "line_exclude_regex",
        ),
        dimensions=dimensions,
        analysis_notes=as_str_list(data.get("analysis_notes"), "analysis_notes"),
        duplicate_search_terms=as_str_list_map(
            data.get("duplicate_search_terms"),
            "duplicate_search_terms",
        ),
        source_priority=as_str_list(data.get("source_priority"), "source_priority"),
        inspection_hints=as_str_list_map(data.get("inspection_hints"), "inspection_hints"),
        handoff_defaults=as_object(data.get("handoff_defaults"), "handoff_defaults"),
        path_analysis=as_object(data.get("path_analysis"), "path_analysis"),
    )


def normalize_name(raw: str) -> str:
    while raw.startswith("../"):
        raw = raw[3:]
    return raw


def entry_stem(name: str) -> str:
    base = Path(name).name
    for suffix in (".h", ".cc", ".c", ".cpp"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def compile_regex(patterns: Sequence[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]


def keep_entry(entry: Entry, target: Target) -> bool:
    include_patterns = compile_regex(target.summary_include_regex)
    exclude_patterns = compile_regex(target.summary_exclude_regex)
    haystack = f"{entry.name} {entry_stem(entry.name)}"

    if include_patterns and not any(pattern.search(haystack) for pattern in include_patterns):
        return False
    if any(pattern.search(haystack) for pattern in exclude_patterns):
        return False

    stem = entry_stem(entry.name)
    if any(stem.startswith(prefix) for prefix in target.summary_exclude_prefixes):
        return False

    return True


def parse_summary(path: Path, target: Target) -> list[Entry]:
    entries: list[Entry] = []
    current: Entry | None = None

    for line in path.read_text(errors="replace").splitlines():
        match = re.match(r"File '(.+)'", line)
        if match:
            raw = match.group(1)
            name = normalize_name(raw)
            current = Entry(file=raw, name=name)
            entries.append(current)
            continue

        if line.startswith("Creating ") or line.startswith("Removing "):
            current = None
            continue

        if current is None:
            continue

        match = re.match(r"Lines executed:([0-9.]+)% of (\d+)", line)
        if match:
            current.line_pct = float(match.group(1))
            current.lines = int(match.group(2))
            continue

        match = re.match(r"Branches executed:([0-9.]+)% of (\d+)", line)
        if match:
            current.branch_pct = float(match.group(1))
            current.branches = int(match.group(2))
            continue

        match = re.match(r"Calls executed:([0-9.]+)% of (\d+)", line)
        if match:
            current.call_pct = float(match.group(1))
            current.calls = int(match.group(2))
            continue

    return [entry for entry in entries if keep_entry(entry, target)]


def insn(name: str) -> str:
    return f"riscv/insns/{name}.h"


def expand_dimension_item(item: str, entry_names: Sequence[str]) -> list[str]:
    if item.startswith("insn:"):
        return [insn(item.split(":", 1)[1])]
    if item.startswith("glob:"):
        pattern = item.split(":", 1)[1]
        return sorted(name for name in entry_names if fnmatch.fnmatch(name, pattern))
    return [normalize_name(item)]


def expand_dimensions(target: Target, entries: Iterable[Entry]) -> dict[str, list[str]]:
    entry_names = sorted({entry.name for entry in entries})
    dims: dict[str, list[str]] = {}
    for dim, items in target.dimensions.items():
        expanded: list[str] = []
        for item in items:
            expanded.extend(expand_dimension_item(item, entry_names))
        dims[dim] = sorted(dict.fromkeys(expanded))

    if not dims:
        dims[target.title] = entry_names
    return dims


def weighted_pct(entries: list[Entry], pct_attr: str, count_attr: str) -> float | None:
    total = sum(getattr(entry, count_attr) for entry in entries)
    if total == 0:
        return None
    return (
        sum((getattr(entry, pct_attr) or 0.0) * getattr(entry, count_attr) for entry in entries)
        / total
    )


def short_names(names: Iterable[str], limit: int = 10) -> str:
    simple = [Path(name).name.removesuffix(".h").removesuffix(".cc") for name in names]
    if not simple:
        return "-"
    if len(simple) <= limit:
        return ", ".join(simple)
    return ", ".join(simple[:limit]) + f" ... (+{len(simple) - limit})"


def gcov_name_for_entry(name: str) -> str:
    return Path(name).name + ".gcov"


def inspection_files_for_candidate(group: dict, target: Target, limit: int = 16) -> list[str]:
    entries = group["zero_entries"][:10] or group["low_branch_entries"][:10]
    files = [gcov_name_for_entry(entry) for entry in entries]
    files.extend(target.inspection_hints.get(group["dimension"], []))
    return list(dict.fromkeys(files))[:limit]


def is_insn_entry(name: str) -> bool:
    return normalize_name(name).startswith("riscv/insns/")


def evidence_class_for_group(group: dict, target: Target) -> dict[str, Any]:
    dimension = str(group.get("dimension", "")).lower()
    entries = [str(name) for name in group.get("entries", [])]
    evidence_entries = [str(name) for name in group.get("zero_entries", []) + group.get("low_branch_entries", [])]
    source_priority = {normalize_name(item) for item in target.source_priority}
    source_priority_basenames = {Path(item).name for item in source_priority}
    inspection_files = inspection_files_for_candidate(group, target)
    inspection_basenames = {Path(item).name for item in inspection_files}

    entry_file_count = sum(1 for name in entries if is_insn_entry(name))
    shared_source_file_count = sum(
        1
        for name in entries
        if name in source_priority or Path(name).name in source_priority_basenames
    )
    inspection_hint_file_count = len(inspection_files)

    if "shared" in dimension:
        return {
            "class": "shared-path",
            "reason": "dimension name declares shared path scope",
            "confidence": "medium",
            "entry_file_count": entry_file_count,
            "shared_source_file_count": shared_source_file_count,
            "inspection_hint_file_count": inspection_hint_file_count,
        }
    if shared_source_file_count:
        return {
            "class": "shared-path",
            "reason": "dimension entries include source_priority shared files",
            "confidence": "high",
            "entry_file_count": entry_file_count,
            "shared_source_file_count": shared_source_file_count,
            "inspection_hint_file_count": inspection_hint_file_count,
        }

    inspected_shared = any(
        item in inspection_basenames
        or Path(item).name in inspection_basenames
        or f"{Path(item).name}.gcov" in inspection_basenames
        for item in source_priority
    )
    if inspected_shared:
        return {
            "class": "mixed",
            "reason": "candidate entries are not shared files, but inspection_hints include source_priority files",
            "confidence": "medium",
            "entry_file_count": entry_file_count,
            "shared_source_file_count": shared_source_file_count,
            "inspection_hint_file_count": inspection_hint_file_count,
        }

    class_basis = evidence_entries or entries
    if class_basis and all(is_insn_entry(name) for name in class_basis):
        return {
            "class": "entry",
            "reason": "coverage gap basis is only riscv/insns entries",
            "confidence": "high",
            "entry_file_count": entry_file_count,
            "shared_source_file_count": shared_source_file_count,
            "inspection_hint_file_count": inspection_hint_file_count,
        }

    return {
        "class": "mixed",
        "reason": "mixed or unknown file basis; source review required",
        "confidence": "low",
        "entry_file_count": entry_file_count,
        "shared_source_file_count": shared_source_file_count,
        "inspection_hint_file_count": inspection_hint_file_count,
    }


def score_group(group: dict) -> float:
    score = 0.0
    if group["zero_count"]:
        score += min(30.0, group["zero_count"] * 2.0)
    branch_pct = group.get("branch_pct")
    call_pct = group.get("call_pct")
    line_pct = group.get("line_pct")
    if branch_pct is not None:
        score += max(0.0, 20.0 - branch_pct)
    if call_pct is not None:
        score += max(0.0, 15.0 - call_pct)
    if line_pct is not None:
        score += max(0.0, 15.0 - line_pct / 5.0)
    return round(score, 2)


def build_candidates(groups: list[dict], focus: str | None, target: Target) -> list[EvidenceCandidate]:
    candidates: list[EvidenceCandidate] = []
    focus_lc = focus.lower() if focus else None

    for group in groups:
        dim = group["dimension"]
        all_names = " ".join(group["zero_entries"] + group["low_branch_entries"]).lower()
        if focus_lc and focus_lc not in dim.lower() and focus_lc not in all_names:
            hint_text = " ".join(target.inspection_hints.get(dim, [])).lower()
            duplicate_text = " ".join(target.duplicate_search_terms.get(dim, [])).lower()
            if focus_lc not in hint_text and focus_lc not in duplicate_text:
                continue

        zero = short_names(group["zero_entries"], limit=8)
        low = short_names(group["low_branch_entries"], limit=8)
        evidence = (
            f"{dim}: line {pct(group['line_pct'])}, branch {pct(group['branch_pct'])}, "
            f"call {pct(group['call_pct'])}, zero entries {group['zero_count']} ({zero}), "
            f"low-branch entries {low}"
        )
        rationale_bits = []
        if group["zero_count"]:
            rationale_bits.append(f"{group['zero_count']} zero-coverage entries")
        if group.get("branch_pct") is not None and group["branch_pct"] < 10.0:
            rationale_bits.append("branch coverage <10%")
        if group.get("call_pct") is not None and group["call_pct"] < 10.0:
            rationale_bits.append("call coverage <10%")

        class_info = evidence_class_for_group(group, target)
        candidates.append(
            EvidenceCandidate(
                score=score_group(group),
                dimension=dim,
                evidence_class=class_info["class"],
                evidence_class_reason=class_info["reason"],
                classification_confidence=class_info["confidence"],
                entry_file_count=class_info["entry_file_count"],
                shared_source_file_count=class_info["shared_source_file_count"],
                inspection_hint_file_count=class_info["inspection_hint_file_count"],
                evidence=evidence,
                entries=group["zero_entries"][:10] or group["low_branch_entries"][:10],
                rationale="; ".join(rationale_bits)
                if rationale_bits
                else "lower-priority coverage gap",
                inspection_files=inspection_files_for_candidate(group, target),
            )
        )

    return sorted(candidates, key=lambda item: (-item.score, item.dimension))


def summarize(entries: list[Entry], target: Target, focus: str | None = None) -> dict:
    by_name = {entry.name: entry for entry in entries}
    dims = expand_dimensions(target, entries)
    groups = []
    scoped_names = {name for names in dims.values() for name in names}
    focused_names: set[str] = set()
    focus_lc = focus.lower() if focus else None

    for dim, names in dims.items():
        group_names = names
        if focus_lc:
            dim_matches = focus_lc in dim.lower()
            matching_names = [name for name in names if focus_lc in name.lower()]
            if not dim_matches and not matching_names:
                continue
            group_names = names if dim_matches else matching_names
        focused_names.update(group_names)
        present = [by_name[name] for name in group_names if name in by_name]
        if not present:
            continue

        zero = [entry.name for entry in present if entry.line_pct == 0.0]
        low_branch = [
            entry.name
            for entry in present
            if entry.branches > 0 and (entry.branch_pct or 0.0) < 10.0
        ]
        groups.append(
            {
                "dimension": dim,
                "files": len(present),
                "entries": [entry.name for entry in present],
                "line_pct": weighted_pct(present, "line_pct", "lines"),
                "branch_pct": weighted_pct(present, "branch_pct", "branches"),
                "call_pct": weighted_pct(present, "call_pct", "calls"),
                "zero_count": len(zero),
                "zero_entries": zero,
                "low_branch_entries": low_branch,
            }
        )

    detail_entries = [entry for entry in entries if entry.name in scoped_names]
    if not detail_entries:
        detail_entries = entries
    if focus_lc:
        detail_entries = [entry for entry in detail_entries if entry.name in focused_names]

    zero_entries = sorted(
        [entry for entry in detail_entries if entry.line_pct == 0.0],
        key=lambda entry: entry.name,
    )
    low_branch_entries = sorted(
        [
            entry
            for entry in detail_entries
            if entry.branches > 0 and (entry.branch_pct or 0.0) < 10.0
        ],
        key=lambda entry: ((entry.branch_pct or 0.0), entry.name),
    )
    return {
        "target": asdict(target),
        "groups": groups,
        "candidates": [asdict(candidate) for candidate in build_candidates(groups, focus, target)],
        "zero_entries": [asdict(entry) for entry in zero_entries],
        "low_branch_entries": [asdict(entry) for entry in low_branch_entries],
    }


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}%"


def print_markdown(summary: dict, top: int, detail_limit: int) -> None:
    target = summary["target"]
    print("## Target")
    print()
    print(f"- name: `{target['name']}`")
    print(f"- title: {target['title']}")
    if target["path"]:
        print(f"- target file: `{target['path']}`")
    if target["description"]:
        print(f"- description: {target['description']}")
    if target["spec"].get("profile"):
        print(f"- spec profile: {target['spec']['profile']}")
    if target["scope_in"]:
        print(f"- scope in: {'; '.join(target['scope_in'])}")
    if target["scope_out"]:
        print(f"- scope out: {'; '.join(target['scope_out'])}")
    if target["summary_exclude_prefixes"] or target["summary_exclude_regex"]:
        filters = target["summary_exclude_prefixes"] + target["summary_exclude_regex"]
        print(f"- summary exclusions: {'; '.join(filters)}")
    if target["source_priority"]:
        print(f"- source priority: {'; '.join(target['source_priority'])}")
    if target.get("path_analysis"):
        fields = target["path_analysis"].get("path_signature_fields", [])
        if isinstance(fields, list) and fields:
            print(f"- path signature checklist: {'; '.join(fields)}")
    print()

    print("## Dimension coverage evidence")
    print()
    print("| 维度 | 文件数 | 行覆盖 | 分支覆盖 | 调用覆盖 | 0%入口数 | 0%入口 | 分支<10%入口 |")
    print("|---|---:|---:|---:|---:|---:|---|---|")
    for group in summary["groups"]:
        print(
            "| {dimension} | {files} | {line_pct} | {branch_pct} | {call_pct} | {zero_count} | `{zero}` | `{low}` |".format(
                dimension=group["dimension"],
                files=group["files"],
                line_pct=pct(group["line_pct"]),
                branch_pct=pct(group["branch_pct"]),
                call_pct=pct(group["call_pct"]),
                zero_count=group["zero_count"],
                zero=short_names(group["zero_entries"]),
                low=short_names(group["low_branch_entries"]),
            )
        )

    def print_candidate_table(title: str, candidates: list[dict], max_rows: int) -> None:
        print(f"\n## {title} (top {max_rows})")
        print("| Rank | Score | Class | Class reason | Dimension | Coverage evidence | Rationale | Representative entries | Inspect next |")
        print("|---:|---:|---|---|---|---|---|---|---|")
        for idx, candidate in enumerate(candidates[:max_rows], start=1):
            print(
                "| {rank} | {score:.2f} | {klass} | {reason} | {dimension} | {evidence} | {rationale} | `{entries}` | `{inspect}` |".format(
                    rank=idx,
                    score=candidate["score"],
                    klass=candidate.get("evidence_class", "unknown"),
                    reason=(
                        str(candidate.get("evidence_class_reason", "-"))
                        + f" ({candidate.get('classification_confidence', 'unknown')})"
                    ).replace("|", "\\|"),
                    dimension=candidate["dimension"],
                    evidence=candidate["evidence"].replace("|", "\\|"),
                    rationale=candidate["rationale"].replace("|", "\\|"),
                    entries=short_names(candidate["entries"], limit=8),
                    inspect=", ".join(candidate.get("inspection_files") or []),
                )
            )

    print_candidate_table("Ranked coverage evidence", summary["candidates"], top)

    shared_candidates = [
        candidate for candidate in summary["candidates"] if candidate.get("evidence_class") == "shared-path"
    ]
    mixed_candidates = [
        candidate for candidate in summary["candidates"] if candidate.get("evidence_class") == "mixed"
    ]
    entry_candidates = [
        candidate for candidate in summary["candidates"] if candidate.get("evidence_class") == "entry"
    ]
    print_candidate_table("Ranked shared semantic path gaps", shared_candidates, top)
    print_candidate_table("Ranked mixed entry/shared-review gaps", mixed_candidates, top)
    print_candidate_table("Ranked entry coverage gaps", entry_candidates, top)

    print("\n## 0% entries")
    for entry in summary["zero_entries"][:detail_limit]:
        print(f"- `{entry['name']}` lines={entry['lines']} branches={entry['branches']} calls={entry['calls']}")
    if len(summary["zero_entries"]) > detail_limit:
        print(f"- ... (+{len(summary['zero_entries']) - detail_limit})")

    print("\n## Lowest branch entries")
    for entry in summary["low_branch_entries"][:detail_limit]:
        print(
            f"- `{entry['name']}` branch={pct(entry['branch_pct'])} line={pct(entry['line_pct'])} call={pct(entry['call_pct'])}"
        )
    if len(summary["low_branch_entries"]) > detail_limit:
        print(f"- ... (+{len(summary['low_branch_entries']) - detail_limit})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, type=Path, help="gcov text summary")
    parser.add_argument("--target", required=True, type=Path, help="target JSON defining scope, exclusions, and dimensions")
    parser.add_argument("--focus", help="only include dimensions or entries containing this text")
    parser.add_argument("--top", type=int, default=12, help="number of ranked evidence rows to print")
    parser.add_argument("--detail-limit", type=int, default=40, help="number of detailed zero/low-branch entries to print")
    parser.add_argument("--json-out", type=Path, help="write machine-readable JSON summary to this path")
    parser.add_argument("--markdown", action="store_true", help="print markdown instead of JSON")
    args = parser.parse_args()

    target = load_target(args.target)
    entries = parse_summary(args.summary, target)
    result = summarize(entries, target, args.focus)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    if args.markdown:
        print_markdown(result, args.top, args.detail_limit)
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
