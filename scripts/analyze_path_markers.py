#!/usr/bin/env python3
"""Analyze path-marker logs emitted by an instrumented coverage Spike.

Expected JSONL format, one JSON object per guest instruction or memory access:

  {"pc":"0x80001000","insn":"lw","markers":["mem.access.scalar_load","mem.translate.tlb_miss_walk"]}

The parser also accepts simple text lines containing marker names, but JSONL is
preferred because it preserves per-instruction correlation.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


MARKER_RE = re.compile(r"[A-Za-z0-9_]+\.[A-Za-z0-9_.-]+")


@dataclass
class MarkerRecord:
    line: int
    pc: str | None
    insn: str | None
    markers: list[str]
    raw: str
    record_format: str
    correlation_strength: str
    correlation_fields: list[str]
    group_values: dict[str, str]


@dataclass
class SequenceResult:
    name: str
    required_markers: list[str]
    match_mode: str
    count: int
    json_record_count: int
    weak_json_record_count: int
    text_record_count: int
    example_line: int | None
    example_pc: str | None
    example_insn: str | None
    example_group: str | None
    evidence_strength: str
    status: str


def parse_record(line_no: int, text: str) -> MarkerRecord | None:
    stripped = text.strip()
    if not stripped:
        return None

    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        # Preserve first-seen order. Text logs can show marker co-occurrence on
        # one line, but they are weak evidence because the parser cannot prove a
        # per-instruction/access JSON record schema.
        markers = list(dict.fromkeys(MARKER_RE.findall(stripped)))
        if not markers:
            return None
        return MarkerRecord(
            line=line_no,
            pc=None,
            insn=None,
            markers=markers,
            raw=stripped,
            record_format="text",
            correlation_strength="text-fallback-weak",
            correlation_fields=[],
            group_values={},
        )

    if not isinstance(obj, dict):
        return None

    raw_markers = obj.get("markers", obj.get("path", obj.get("events", [])))
    markers: list[str] = []
    if isinstance(raw_markers, str):
        markers = [part for part in re.split(r"[|,\s]+", raw_markers) if part]
    elif isinstance(raw_markers, list):
        markers = [str(item) for item in raw_markers]

    if not markers:
        return None

    correlation_fields = [
        name
        for name in ("pc", "insn", "seq", "hart", "access_id", "record_kind")
        if obj.get(name) is not None
    ]
    field_set = set(correlation_fields)
    has_dynamic_correlation = {"pc", "insn"}.issubset(field_set) or bool(
        {"seq", "access_id"} & field_set
    )
    correlation_strength = "per-record-json" if has_dynamic_correlation else "json-record-weak"
    group_values = {
        name: str(obj.get(name))
        for name in ("pc", "insn", "seq", "hart", "access_id", "record_kind")
        if obj.get(name) is not None
    }

    return MarkerRecord(
        line=line_no,
        pc=str(obj.get("pc")) if obj.get("pc") is not None else None,
        insn=str(obj.get("insn")) if obj.get("insn") is not None else None,
        markers=markers,
        raw=stripped,
        record_format="json",
        correlation_strength=correlation_strength,
        correlation_fields=correlation_fields,
        group_values=group_values,
    )


def read_records(path: Path) -> list[MarkerRecord]:
    records: list[MarkerRecord] = []
    for idx, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
        record = parse_record(idx, line)
        if record:
            records.append(record)
    return records


def load_sequences(path: Path | None, required: list[str]) -> list[dict[str, Any]]:
    sequences: list[dict[str, Any]] = []
    if path:
        data = json.loads(path.read_text(errors="replace"))
        if isinstance(data, dict):
            data = data.get("sequences", [])
        if not isinstance(data, list):
            raise TypeError("sequence file must be a list or an object with a `sequences` list")
        for item in data:
            if not isinstance(item, dict):
                raise TypeError("each sequence must be an object")
            markers = item.get("required_markers", item.get("markers", []))
            if not isinstance(markers, list) or not all(isinstance(marker, str) for marker in markers):
                raise TypeError("sequence markers must be a list of strings")
            sequences.append({"name": str(item.get("name") or "|".join(markers)), "markers": markers})
    if required:
        sequences.append({"name": "cli-required", "markers": required})
    return sequences


def marker_set(record: MarkerRecord) -> set[str]:
    return set(record.markers)


def has_ordered_subsequence(markers: list[str], required: list[str]) -> bool:
    if not required:
        return True
    pos = 0
    for marker in markers:
        if marker == required[pos]:
            pos += 1
            if pos == len(required):
                return True
    return False


def sequence_matches(record: MarkerRecord, required: list[str], ordered: bool) -> bool:
    if ordered:
        return has_ordered_subsequence(record.markers, required)
    return set(required).issubset(marker_set(record))


def grouped_markers(records: list[MarkerRecord], group_by: str | None) -> list[tuple[str | None, list[MarkerRecord], list[str], str]]:
    if not group_by:
        return [(None, [record], record.markers, record.correlation_strength) for record in records]
    grouped: dict[str, list[MarkerRecord]] = {}
    for record in records:
        value = record.group_values.get(group_by)
        if value is None:
            continue
        grouped.setdefault(value, []).append(record)
    result = []
    for value, group in grouped.items():
        markers: list[str] = []
        for record in sorted(group, key=lambda item: item.line):
            markers.extend(record.markers)
        strengths = {record.correlation_strength for record in group}
        strength = "per-record-json" if "per-record-json" in strengths else "json-record-weak"
        result.append((value, sorted(group, key=lambda item: item.line), markers, strength))
    return result


def marker_sequence_matches(markers: list[str], required: list[str], ordered: bool) -> bool:
    if ordered:
        return has_ordered_subsequence(markers, required)
    return set(required).issubset(set(markers))


def analyze_sequences(
    records: list[MarkerRecord],
    sequences: list[dict[str, Any]],
    ordered: bool,
    group_by: str | None,
) -> list[SequenceResult]:
    results: list[SequenceResult] = []
    groups = grouped_markers(records, group_by)
    for sequence in sequences:
        required = sequence["markers"]
        matched_groups = [
            (group_value, group_records, strength)
            for group_value, group_records, markers, strength in groups
            if marker_sequence_matches(markers, required, ordered)
        ]
        matches = [group_records[0] for _group_value, group_records, _strength in matched_groups if group_records]
        json_matches = [
            group_records[0]
            for _group_value, group_records, strength in matched_groups
            if group_records and group_records[0].record_format == "json" and strength == "per-record-json"
        ]
        weak_json_matches = [
            group_records[0]
            for _group_value, group_records, strength in matched_groups
            if group_records and group_records[0].record_format == "json" and strength != "per-record-json"
        ]
        text_matches = [record for record in matches if record.record_format != "json"]
        if json_matches:
            status = "marker-sequence-observed"
            evidence_strength = "per-record-json"
            example = json_matches[0]
            example_group = next((value for value, group_records, strength in matched_groups if group_records and group_records[0] is example and strength == "per-record-json"), None)
        elif weak_json_matches:
            status = "json-marker-sequence-observed-weak"
            evidence_strength = "json-record-weak"
            example = weak_json_matches[0]
            example_group = next((value for value, group_records, strength in matched_groups if group_records and group_records[0] is example and strength != "per-record-json"), None)
        elif text_matches:
            status = "text-marker-sequence-observed-weak"
            evidence_strength = "text-fallback-weak"
            example = text_matches[0]
            example_group = None
        else:
            status = "not-observed-in-marker-log"
            evidence_strength = "none"
            example = None
            example_group = None
        results.append(
            SequenceResult(
                name=sequence["name"],
                required_markers=required,
                match_mode=(
                    (f"grouped-by-{group_by}-" if group_by else "")
                    + ("ordered-subsequence" if ordered else "same-record-subset")
                ),
                count=len(matched_groups),
                json_record_count=len(json_matches),
                weak_json_record_count=len(weak_json_matches),
                text_record_count=len(text_matches),
                example_line=example.line if example else None,
                example_pc=example.pc if example else None,
                example_insn=example.insn if example else None,
                example_group=example_group,
                evidence_strength=evidence_strength,
                status=status,
            )
        )
    return results


def summarize_markers(records: list[MarkerRecord]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for record in records:
        for marker in set(record.markers):
            counts[marker] = counts.get(marker, 0) + 1
    return [{"marker": marker, "records": count} for marker, count in sorted(counts.items())]


def summarize_record_formats(records: list[MarkerRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.record_format] = counts.get(record.record_format, 0) + 1
    return counts


def summarize_correlation_strength(records: list[MarkerRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.correlation_strength] = counts.get(record.correlation_strength, 0) + 1
    return counts


def print_markdown(result: dict[str, Any], top_markers: int) -> None:
    observed = sum(
        1
        for item in result.get("sequence_results", [])
        if "observed" in str(item.get("status", ""))
    )
    weak = sum(
        1
        for item in result.get("sequence_results", [])
        if "weak" in str(item.get("status", ""))
    )
    print("# Path marker 证据")
    print()
    print("## 结论")
    print()
    print(
        f"- 已解析记录数: {result['record_count']}；观察到的必需序列={observed}；弱证据观察={weak}。"
    )
    print("- Marker 证据只能证明 marker 序列出现；最终架构证明仍需复核 marker 插桩位置和 observable。")
    print()
    print("## 数据")
    print()
    print(f"- group_by: `{result.get('group_by') or '-'}`")
    print(f"- marker 种类数: {len(result.get('marker_counts', []))}")
    print(f"- 必需序列数: {len(result.get('sequence_results', []))}")
    print()
    print("## 限制与下一步")
    print()
    print("- marker 序列出现本身不是最终架构证明。")
    print("- 强置信度需要复核 marker 位置，并具备 pc/insn、seq 或 access_id 关联。")
    print("- 弱 JSON/text 证据在插桩增强前应保持降级处理。")
    print()
    print("## 证据")
    print()
    print("## Path marker 证据")
    print()
    print(f"- log: `{result['log']}`")
    print(f"- records: {result['record_count']}")
    if result.get("record_format_counts"):
        format_bits = [f"{name}={count}" for name, count in sorted(result["record_format_counts"].items())]
        print(f"- record formats: {', '.join(format_bits)}")
    if result.get("correlation_strength_counts"):
        strength_bits = [f"{name}={count}" for name, count in sorted(result["correlation_strength_counts"].items())]
        print(f"- correlation strengths: {', '.join(strength_bits)}")
    print("- 含义: 每条指令/访问一条 JSON 记录可以保留 same-flow marker 关联")
    print("- 强 JSON 证据字段要求: pc+insn、seq 或 access_id 应能识别动态指令/访问记录")
    print("- 注意: text fallback 是弱证据，不能当作最终路径证明")
    print()

    if result["sequence_results"]:
        print("## 必需序列")
        print()
        print("| 序列 | 状态 | 强度 | 匹配模式 | 计数 | 强 JSON | 弱 JSON | Text | 示例 group | 示例行 | 示例 PC | 示例 insn | 必需 marker |")
        print("|---|---|---|---|---:|---:|---:|---:|---|---:|---|---|---|")
        for item in result["sequence_results"]:
            markers = ", ".join(f"`{marker}`" for marker in item["required_markers"])
            print(
                "| {name} | {status} | {strength} | {mode} | {count} | {json_count} | {weak_json_count} | {text_count} | {group} | {line} | {pc} | {insn} | {markers} |".format(
                    name=item["name"],
                    status=item["status"],
                    strength=item["evidence_strength"],
                    mode=item["match_mode"],
                    count=item["count"],
                    json_count=item["json_record_count"],
                    weak_json_count=item["weak_json_record_count"],
                    text_count=item["text_record_count"],
                    group=item.get("example_group") or "-",
                    line=item["example_line"] if item["example_line"] is not None else "-",
                    pc=item["example_pc"] or "-",
                    insn=item["example_insn"] or "-",
                    markers=markers,
                )
            )
        print()

    print(f"## Marker counts (top {top_markers})")
    print()
    for item in result["marker_counts"][:top_markers]:
        print(f"- `{item['marker']}`: {item['records']}")


def render_markdown(result: dict[str, Any], top_markers: int) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_markdown(result, top_markers)
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path, help="path marker JSONL/text log")
    parser.add_argument("--sequence-json", type=Path, help="JSON list of required marker sequences")
    parser.add_argument("--require", action="append", default=[], help="required marker for one CLI sequence")
    parser.add_argument("--ordered", action="store_true", help="require markers to appear in the listed order")
    parser.add_argument(
        "--group-by",
        choices=("access_id", "seq", "pc"),
        help="group multiple JSON records by a correlation field before sequence matching",
    )
    parser.add_argument("--json-out", type=Path, help="write machine-readable JSON")
    parser.add_argument("--markdown", action="store_true", help="print markdown")
    parser.add_argument("--markdown-out", type=Path, help="write markdown report to this path")
    parser.add_argument("--top-markers", type=int, default=40, help="number of marker counts to print")
    args = parser.parse_args()

    records = read_records(args.log)
    sequences = load_sequences(args.sequence_json, args.require)
    result = {
        "log": str(args.log),
        "record_count": len(records),
        "record_format_counts": summarize_record_formats(records),
        "correlation_strength_counts": summarize_correlation_strength(records),
        "marker_counts": summarize_markers(records),
        "group_by": args.group_by,
        "sequence_results": [asdict(item) for item in analyze_sequences(records, sequences, args.ordered, args.group_by)],
    }

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(render_markdown(result, args.top_markers), encoding="utf-8")

    if args.markdown or (not args.json_out and not args.markdown_out):
        print_markdown(result, args.top_markers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
