#!/usr/bin/env python3
"""Analyze path-marker logs emitted by an instrumented coverage Spike.

Expected JSONL format, one JSON object per guest instruction or memory access:

  {"pc":"0x80001000","insn":"lw","markers":["mem.access.scalar_load","mem.translate.tlb_miss_walk"]}

The parser also accepts simple text lines containing marker names, but JSONL is
preferred because it preserves per-instruction correlation.
"""

from __future__ import annotations

import argparse
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


@dataclass
class SequenceResult:
    name: str
    required_markers: list[str]
    match_mode: str
    count: int
    json_record_count: int
    text_record_count: int
    example_line: int | None
    example_pc: str | None
    example_insn: str | None
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

    return MarkerRecord(
        line=line_no,
        pc=str(obj.get("pc")) if obj.get("pc") is not None else None,
        insn=str(obj.get("insn")) if obj.get("insn") is not None else None,
        markers=markers,
        raw=stripped,
        record_format="json",
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


def analyze_sequences(
    records: list[MarkerRecord],
    sequences: list[dict[str, Any]],
    ordered: bool,
) -> list[SequenceResult]:
    results: list[SequenceResult] = []
    for sequence in sequences:
        required = sequence["markers"]
        matches = [record for record in records if sequence_matches(record, required, ordered)]
        json_matches = [record for record in matches if record.record_format == "json"]
        text_matches = [record for record in matches if record.record_format != "json"]
        if json_matches:
            status = "marker-sequence-observed"
            evidence_strength = "per-record-json"
            example = json_matches[0]
        elif text_matches:
            status = "text-marker-sequence-observed-weak"
            evidence_strength = "text-fallback-weak"
            example = text_matches[0]
        else:
            status = "not-observed-in-marker-log"
            evidence_strength = "none"
            example = None
        results.append(
            SequenceResult(
                name=sequence["name"],
                required_markers=required,
                match_mode="ordered-subsequence" if ordered else "same-record-subset",
                count=len(matches),
                json_record_count=len(json_matches),
                text_record_count=len(text_matches),
                example_line=example.line if example else None,
                example_pc=example.pc if example else None,
                example_insn=example.insn if example else None,
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


def print_markdown(result: dict[str, Any], top_markers: int) -> None:
    print("## Path-marker evidence")
    print()
    print(f"- log: `{result['log']}`")
    print(f"- records: {result['record_count']}")
    if result.get("record_format_counts"):
        format_bits = [f"{name}={count}" for name, count in sorted(result["record_format_counts"].items())]
        print(f"- record formats: {', '.join(format_bits)}")
    print("- meaning: JSON per-instruction/access records can preserve same-flow marker correlation")
    print("- caution: text fallback is weak evidence and must not be treated as final path proof")
    print()

    if result["sequence_results"]:
        print("## Required sequences")
        print()
        print("| Sequence | Status | Strength | Match mode | Count | JSON | Text | Example line | Example PC | Example insn | Required markers |")
        print("|---|---|---|---|---:|---:|---:|---:|---|---|---|")
        for item in result["sequence_results"]:
            markers = ", ".join(f"`{marker}`" for marker in item["required_markers"])
            print(
                "| {name} | {status} | {strength} | {mode} | {count} | {json_count} | {text_count} | {line} | {pc} | {insn} | {markers} |".format(
                    name=item["name"],
                    status=item["status"],
                    strength=item["evidence_strength"],
                    mode=item["match_mode"],
                    count=item["count"],
                    json_count=item["json_record_count"],
                    text_count=item["text_record_count"],
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path, help="path marker JSONL/text log")
    parser.add_argument("--sequence-json", type=Path, help="JSON list of required marker sequences")
    parser.add_argument("--require", action="append", default=[], help="required marker for one CLI sequence")
    parser.add_argument("--ordered", action="store_true", help="require markers to appear in the listed order")
    parser.add_argument("--json-out", type=Path, help="write machine-readable JSON")
    parser.add_argument("--markdown", action="store_true", help="print markdown")
    parser.add_argument("--top-markers", type=int, default=40, help="number of marker counts to print")
    args = parser.parse_args()

    records = read_records(args.log)
    sequences = load_sequences(args.sequence_json, args.require)
    result = {
        "log": str(args.log),
        "record_count": len(records),
        "record_format_counts": summarize_record_formats(records),
        "marker_counts": summarize_markers(records),
        "sequence_results": [asdict(item) for item in analyze_sequences(records, sequences, args.ordered)],
    }

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    if args.markdown or not args.json_out:
        print_markdown(result, args.top_markers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
