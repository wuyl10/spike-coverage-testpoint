#!/usr/bin/env python3
"""Inspect .gcov files and extract uncovered source/branch/call regions.

This is the line-level companion to analyze_spike_gcov.py. It does not try to
understand RISC-V semantics by itself; it gives the agent compact evidence:
uncovered lines, never-executed branches/calls, enclosing function blocks, and
source context. The agent then maps those code paths to test scenarios.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


@dataclass
class MissEvent:
    kind: str
    gcov_line: int
    source_line: int | None
    text: str
    source_code: str | None = None
    ordinal: int | None = None
    counter_format: str | None = None


@dataclass
class FunctionBlock:
    name: str
    mangled_name: str | None
    gcov_line: int
    called: int | None
    returned_pct: str | None
    blocks_pct: str | None
    events: list[MissEvent]


@dataclass
class ExcludedCounts:
    functions: int = 0
    events: int = 0


@dataclass
class FileReport:
    gcov_file: str
    source: str | None
    functions: list[FunctionBlock]
    uncovered_lines: int
    never_branches: int
    never_calls: int
    excluded_counts: ExcludedCounts


FUNCTION_RE = re.compile(
    r"function\s+(?P<name>\S+)\s+called\s+(?P<called>\d+)\s+returned\s+(?P<returned>\S+)\s+blocks executed\s+(?P<blocks>\S+)"
)
GCOV_SOURCE_LINE_RE = re.compile(r"^\s*(?P<count>[-#=\d\*]+):\s*(?P<line>\d+):(?P<code>.*)$")
BRANCH_RE = re.compile(r"^\s*branch\s+(?P<num>\d+)\s+(?P<rest>.*)$")
CALL_RE = re.compile(r"^\s*call\s+(?P<num>\d+)\s+(?P<rest>.*)$")


def parse_gcov(path: Path, include_file_scope: bool = False) -> FileReport:
    source: str | None = None
    functions: list[FunctionBlock] = []
    current = FunctionBlock(
        name="<file-scope>",
        mangled_name=None,
        gcov_line=0,
        called=None,
        returned_pct=None,
        blocks_pct=None,
        events=[],
    )
    functions.append(current)
    last_source_line: int | None = None
    last_source_code: str | None = None

    lines = path.read_text(errors="replace").splitlines()
    for idx, line in enumerate(lines, start=1):
        if line.startswith("        -:    0:Source:"):
            source = line.split("Source:", 1)[1].strip()
            continue

        match = FUNCTION_RE.match(line)
        if match:
            mangled = match.group("name")
            current = FunctionBlock(
                name=demangle(mangled),
                mangled_name=mangled,
                gcov_line=idx,
                called=int(match.group("called")),
                returned_pct=match.group("returned"),
                blocks_pct=match.group("blocks"),
                events=[],
            )
            functions.append(current)
            continue

        src_match = GCOV_SOURCE_LINE_RE.match(line)
        if src_match:
            last_source_line = int(src_match.group("line"))
            count = src_match.group("count")
            code = src_match.group("code").rstrip()
            last_source_code = code.strip()
            if "#" in count:
                current.events.append(
                    MissEvent(
                        kind="uncovered-line",
                        gcov_line=idx,
                        source_line=last_source_line,
                        text=code.strip(),
                        source_code=code.strip(),
                    )
                )
            continue

        kind: str | None = None
        ordinal: int | None = None
        counter_format: str | None = None
        branch_match = BRANCH_RE.match(line)
        call_match = CALL_RE.match(line)
        if branch_match:
            ordinal = int(branch_match.group("num"))
            rest = branch_match.group("rest")
            counter_format = branch_or_call_counter_format(rest)
            if "never executed" in rest:
                kind = "branch-never"
            elif re.search(r"\btaken\s+0(?=$|\s)", rest):
                kind = "branch-taken-0"
        elif call_match:
            ordinal = int(call_match.group("num"))
            rest = call_match.group("rest")
            counter_format = branch_or_call_counter_format(rest)
            if "never executed" in rest:
                kind = "call-never"
            elif re.search(r"\breturned\s+0(?=$|\s)", rest):
                kind = "call-returned-0"

        if kind:
            current.events.append(
                MissEvent(
                    kind=kind,
                    gcov_line=idx,
                    source_line=last_source_line,
                    text=line.strip(),
                    source_code=last_source_code,
                    ordinal=ordinal,
                    counter_format=counter_format,
                )
            )

    functions = [
        fn
        for fn in functions
        if (include_file_scope or fn.name != "<file-scope>") and (fn.events or (fn.called == 0))
    ]
    return FileReport(
        gcov_file=str(path),
        source=source,
        functions=functions,
        uncovered_lines=sum(1 for fn in functions for ev in fn.events if ev.kind == "uncovered-line"),
        never_branches=sum(1 for fn in functions for ev in fn.events if ev.kind in {"branch-never", "branch-taken-0"}),
        never_calls=sum(1 for fn in functions for ev in fn.events if ev.kind in {"call-never", "call-returned-0"}),
        excluded_counts=ExcludedCounts(),
    )


def function_haystack(fn: FunctionBlock) -> str:
    parts = [fn.name, fn.mangled_name or ""]
    for event in fn.events:
        parts.append(event.text)
        if event.source_code:
            parts.append(event.source_code)
    return " ".join(parts)


def function_identity_haystack(fn: FunctionBlock) -> str:
    return " ".join([fn.name, fn.mangled_name or ""])


def event_haystack(event: MissEvent) -> str:
    return " ".join([event.text, event.source_code or ""])


def function_priority(fn: FunctionBlock, patterns: list[re.Pattern[str]]) -> int:
    haystack = function_haystack(fn)
    return sum(1 for pattern in patterns if pattern.search(haystack))


def event_key(event: MissEvent) -> tuple[str, int | None, str, str]:
    return (
        event.kind,
        event.source_line,
        str(event.ordinal) if event.ordinal is not None else "",
        event.text,
        event.source_code or "",
    )


def branch_or_call_counter_format(rest: str) -> str:
    if "never executed" in rest:
        return "never"
    if re.search(r"\b(?:taken|returned)\s+\d+(?:\.\d+)?%", rest):
        return "percent"
    if re.search(r"\b(?:taken|returned)\s+\d+(?=$|\s)", rest):
        return "count"
    return "unknown"


def function_merge_key(fn: FunctionBlock) -> str:
    line = first_source_line(fn.events)
    return "|".join([fn.name, fn.mangled_name or "", str(line if line is not None else fn.gcov_line)])


def merge_duplicate_functions(functions: list[FunctionBlock], mode: str) -> list[FunctionBlock]:
    if mode == "none":
        return functions
    merged: dict[str, FunctionBlock] = {}
    order: list[str] = []

    for fn in functions:
        key = fn.name if mode == "name" else function_merge_key(fn)
        created = False
        if key not in merged:
            merged[key] = FunctionBlock(
                name=fn.name,
                mangled_name=fn.mangled_name,
                gcov_line=fn.gcov_line,
                called=fn.called,
                returned_pct=fn.returned_pct,
                blocks_pct=fn.blocks_pct,
                events=[],
            )
            order.append(key)
            created = True
        dst = merged[key]
        if (dst.called is None or dst.called == 0) and fn.called and fn.called > 0:
            dst.returned_pct = fn.returned_pct
            dst.blocks_pct = fn.blocks_pct
            if fn.mangled_name:
                dst.mangled_name = fn.mangled_name
        if first_source_line(fn.events) is not None and (
            first_source_line(dst.events) is None
            or first_source_line(fn.events) < first_source_line(dst.events)  # type: ignore[operator]
        ):
            dst.gcov_line = fn.gcov_line
        if not created and dst.called is not None and fn.called is not None:
            dst.called += fn.called
        elif not created and dst.called is None:
            dst.called = fn.called
        seen = {event_key(event) for event in dst.events}
        for event in fn.events:
            key_event = event_key(event)
            if key_event not in seen:
                dst.events.append(event)
                seen.add(key_event)

    return [merged[key] for key in order]


def apply_exclude_regex(report: FileReport, patterns: list[re.Pattern[str]], merge_mode: str) -> FileReport:
    excluded_counts = ExcludedCounts()

    def rebuild(functions: list[FunctionBlock]) -> FileReport:
        return FileReport(
            gcov_file=report.gcov_file,
            source=report.source,
            functions=functions,
            uncovered_lines=sum(1 for fn in functions for ev in fn.events if ev.kind == "uncovered-line"),
            never_branches=sum(1 for fn in functions for ev in fn.events if ev.kind in {"branch-never", "branch-taken-0"}),
            never_calls=sum(1 for fn in functions for ev in fn.events if ev.kind in {"call-never", "call-returned-0"}),
            excluded_counts=excluded_counts,
        )

    if not patterns:
        return rebuild(merge_duplicate_functions(report.functions, merge_mode))

    functions = []
    for fn in report.functions:
        haystack = function_identity_haystack(fn)
        if any(pattern.search(haystack) for pattern in patterns):
            excluded_counts.functions += 1
            excluded_counts.events += len(fn.events)
            continue
        filtered_events = []
        for event in fn.events:
            if any(pattern.search(event_haystack(event)) for pattern in patterns):
                excluded_counts.events += 1
            else:
                filtered_events.append(event)
        if filtered_events or (fn.called == 0 and not fn.events):
            functions.append(
                FunctionBlock(
                    name=fn.name,
                    mangled_name=fn.mangled_name,
                    gcov_line=fn.gcov_line,
                    called=fn.called,
                    returned_pct=fn.returned_pct,
                    blocks_pct=fn.blocks_pct,
                    events=filtered_events,
                )
            )
    return rebuild(merge_duplicate_functions(functions, merge_mode))


def load_target_line_rules(path: Path | None) -> tuple[list[str], list[str]]:
    if path is None:
        return [], []
    data = json.loads(path.read_text(errors="replace"))
    return (
        read_regex_list(data, "line_exclude_regex"),
        read_regex_list(data, "line_priority_regex"),
    )


def read_regex_list(data: dict, field: str) -> list[str]:
    patterns = data.get(field, [])
    if patterns is None:
        return []
    if isinstance(patterns, str):
        return [patterns]
    if isinstance(patterns, list) and all(isinstance(item, str) for item in patterns):
        return patterns
    raise TypeError(f"target field '{field}' must be a string or list of strings")


def load_source_context(source_root: Path | None, source: str | None, line_no: int, context: int) -> list[tuple[int, str]]:
    if not source_root or not source:
        return []

    candidates = []
    src = Path(source)
    if src.is_absolute():
        candidates.append(src)
    else:
        cleaned = source
        while cleaned.startswith("../"):
            cleaned = cleaned[3:]
        candidates.append(source_root / cleaned)
        candidates.append(source_root / source)

    source_path = next((candidate for candidate in candidates if candidate.exists()), None)
    if not source_path:
        return []

    lines = source_path.read_text(errors="replace").splitlines()
    start = max(1, line_no - context)
    end = min(len(lines), line_no + context)
    return [(idx, lines[idx - 1]) for idx in range(start, end + 1)]


_DEMANGLE_CACHE: dict[str, str] = {}


def demangle(name: str) -> str:
    if name in _DEMANGLE_CACHE:
        return _DEMANGLE_CACHE[name]
    try:
        proc = subprocess.run(
            ["c++filt", name],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        result = proc.stdout.strip() or name
    except OSError:
        result = name
    _DEMANGLE_CACHE[name] = result
    return result


def first_source_line(events: Iterable[MissEvent]) -> int | None:
    for event in events:
        if event.source_line is not None:
            return event.source_line
    return None


def grouped_event_rows(events: list[MissEvent], max_rows: int) -> tuple[list[tuple[str, int | None, str, str]], int]:
    grouped: dict[tuple[int | None, int], dict] = {}
    order: list[tuple[int | None, int]] = []

    for event in events:
        key = (event.source_line, event.source_line if event.source_line is not None else event.gcov_line)
        if key not in grouped:
            grouped[key] = {"counts": {}, "code": "", "samples": []}
            order.append(key)
        item = grouped[key]
        item["counts"][event.kind] = item["counts"].get(event.kind, 0) + 1
        if event.ordinal is not None:
            item.setdefault("ordinals", set()).add(f"{event.kind}:{event.ordinal}")
        if event.counter_format:
            item.setdefault("counter_formats", set()).add(event.counter_format)
        if event.kind == "uncovered-line" and event.text:
            item["code"] = event.text
        elif event.source_code and not item["code"]:
            item["code"] = event.source_code
        elif len(item["samples"]) < 3:
            item["samples"].append(event.text)

    rows: list[tuple[str, int | None, str, str]] = []
    for key in order[:max_rows]:
        item = grouped[key]
        kinds = ", ".join(f"{name}={count}" for name, count in sorted(item["counts"].items()))
        ordinals = ", ".join(sorted(item.get("ordinals", set()))) or "-"
        formats = ", ".join(sorted(item.get("counter_formats", set()))) or "-"
        evidence = item["code"] or "; ".join(item["samples"])
        detail = f"ordinals={ordinals}; formats={formats}"
        rows.append((kinds, key[0], detail, evidence))
    return rows, max(0, len(order) - max_rows)


def print_markdown(
    reports: list[FileReport],
    source_root: Path | None,
    context: int,
    max_functions: int,
    max_events: int,
    priority_patterns: list[re.Pattern[str]],
    context_exclude_patterns: list[re.Pattern[str]],
) -> None:
    total_uncovered = sum(report.uncovered_lines for report in reports)
    total_branches = sum(report.never_branches for report in reports)
    total_calls = sum(report.never_calls for report in reports)
    total_excluded_functions = sum(report.excluded_counts.functions for report in reports)
    total_excluded_events = sum(report.excluded_counts.events for report in reports)
    print("# Spike gcov line evidence")
    print()
    print("## Conclusion")
    print()
    print(
        f"- Inspected {len(reports)} `.gcov` file(s): uncovered lines={total_uncovered}, "
        f"never/zero branches={total_branches}, never/zero calls={total_calls}."
    )
    print(
        f"- Target filters excluded functions={total_excluded_functions}, events={total_excluded_events}; "
        "filtered evidence can affect candidate completeness."
    )
    print("- Use the function/source evidence below to map coverage gaps to architecture scenarios; this report does not decide test intent by itself.")
    print()
    print("## Data")
    print()
    print("| File | Source | Uncovered lines | Never/zero branches | Never/zero calls | Excluded functions | Excluded events |")
    print("|---|---|---:|---:|---:|---:|---:|")
    for report in reports:
        print(
            f"| `{Path(report.gcov_file).name}` | `{report.source or '-'}` | {report.uncovered_lines} | "
            f"{report.never_branches} | {report.never_calls} | {report.excluded_counts.functions} | {report.excluded_counts.events} |"
        )
    print()
    print("## Limits / Next steps")
    print()
    print("- Line evidence identifies uncovered source/branch/call points, not the architecture scenario by itself.")
    print("- Map the listed functions and source lines to a target path signature before writing tests.")
    print("- If same-flow correlation matters, confirm with a single-case increment run or path markers.")
    print()
    print("## Evidence")
    print()
    for report in reports:
        print(f"## {Path(report.gcov_file).name}")
        print()
        print(f"- gcov file: `{report.gcov_file}`")
        print(f"- source: `{report.source or '-'}`")
        print(f"- uncovered lines: {report.uncovered_lines}")
        print(f"- never branches: {report.never_branches}")
        print(f"- never calls: {report.never_calls}")
        print(
            "- excluded by filters: "
            f"functions={report.excluded_counts.functions}, events={report.excluded_counts.events}"
        )
        print()

        ranked = sorted(
            report.functions,
            key=lambda fn: (
                -function_priority(fn, priority_patterns),
                -(sum(1 for ev in fn.events if ev.kind == "uncovered-line")),
                -(sum(1 for ev in fn.events if ev.kind.startswith("branch"))),
                -(sum(1 for ev in fn.events if ev.kind.startswith("call"))),
                fn.name,
            ),
        )

        for fn in ranked[:max_functions]:
            line = first_source_line(fn.events)
            print(f"### Function `{fn.name}`")
            print()
            if fn.mangled_name and fn.mangled_name != fn.name:
                print(f"- mangled: `{fn.mangled_name}`")
            print(
                f"- called: {fn.called if fn.called is not None else '-'}, "
                f"returned: {fn.returned_pct or '-'}, blocks: {fn.blocks_pct or '-'}, "
                f"first source line: {line if line is not None else '-'}"
            )
            counts = {}
            for event in fn.events:
                counts[event.kind] = counts.get(event.kind, 0) + 1
            print("- miss kinds: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
            print()

            print("| Miss kinds | Source line | Branch/call detail | Evidence |")
            print("|---|---:|---|---|")
            rows, remaining = grouped_event_rows(fn.events, max_events)
            for kinds, source_line, detail, evidence in rows:
                text = evidence.replace("|", "\\|")
                print(f"| `{kinds}` | {source_line if source_line is not None else '-'} | `{detail}` | `{text}` |")
            if remaining:
                print(f"| ... | - | - | +{remaining} more source locations |")
            print()

            if line is not None:
                context_lines = load_source_context(source_root, report.source, line, context)
                if context_lines:
                    print("```cpp")
                    for idx, text in context_lines:
                        marker = ">" if idx == line else " "
                        shown_text = (
                            "<filtered by target line_exclude_regex>"
                            if any(pattern.search(text) for pattern in context_exclude_patterns)
                            else text
                        )
                        print(f"{marker}{idx:5d}: {shown_text}")
                    print("```")
                    print()


def render_markdown(
    reports: list[FileReport],
    source_root: Path | None,
    context: int,
    max_functions: int,
    max_events: int,
    priority_patterns: list[re.Pattern[str]],
    context_exclude_patterns: list[re.Pattern[str]],
) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_markdown(
            reports,
            source_root,
            context,
            max_functions,
            max_events,
            priority_patterns,
            context_exclude_patterns,
        )
    return buf.getvalue()


def expand_gcov_inputs(gcov_dir: Path | None, files: list[str]) -> list[Path]:
    result: list[Path] = []
    for item in files:
        path = Path(item)
        if path.exists():
            result.append(path)
            continue
        if gcov_dir:
            candidate = gcov_dir / item
            if candidate.exists():
                result.append(candidate)
                continue
            if not item.endswith(".gcov"):
                candidate = gcov_dir / f"{item}.gcov"
                if candidate.exists():
                    result.append(candidate)
                    continue
        raise FileNotFoundError(f"cannot find gcov file: {item}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gcov-dir", type=Path, help="directory containing .gcov files")
    parser.add_argument("--source-root", type=Path, help="Spike source repository root")
    parser.add_argument("--target", required=True, type=Path, help="target JSON; uses line_exclude_regex for evidence filtering")
    parser.add_argument(
        "--exclude-regex",
        action="append",
        default=[],
        help="exclude matching functions by name and matching events by source/evidence text; can be repeated",
    )
    parser.add_argument(
        "--priority-regex",
        action="append",
        default=[],
        help="rank functions higher when demangled name or event text matches this regex; can be repeated",
    )
    parser.add_argument("--file", action="append", required=True, help="gcov file path or filename under --gcov-dir; can be repeated")
    parser.add_argument("--context", type=int, default=5, help="source context lines around first miss")
    parser.add_argument("--max-functions", type=int, default=12, help="max functions to print per file")
    parser.add_argument("--max-events", type=int, default=12, help="max miss events to print per function")
    parser.add_argument(
        "--merge-functions",
        choices=("none", "identity", "name"),
        default="identity",
        help="merge duplicate function blocks: none, identity=(demangled+mangled+line), or name=(old broad demangled-name merge)",
    )
    parser.add_argument(
        "--include-file-scope",
        action="store_true",
        help="include file-scope gcov events that are not attached to a function header",
    )
    parser.add_argument("--json-out", type=Path, help="write JSON report to this path")
    parser.add_argument("--markdown", action="store_true", help="print markdown report")
    parser.add_argument("--markdown-out", type=Path, help="write markdown report to this path")
    args = parser.parse_args()

    paths = expand_gcov_inputs(args.gcov_dir, args.file)
    target_exclude_regex, target_priority_regex = load_target_line_rules(args.target)
    exclude_regex = target_exclude_regex + args.exclude_regex
    priority_regex = target_priority_regex + args.priority_regex
    exclude_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in exclude_regex]
    priority_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in priority_regex]
    reports = [
        apply_exclude_regex(parse_gcov(path, include_file_scope=args.include_file_scope), exclude_patterns, args.merge_functions)
        for path in paths
    ]

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps([asdict(report) for report in reports], indent=2, ensure_ascii=False) + "\n")

    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(
            render_markdown(
                reports,
                args.source_root,
                args.context,
                args.max_functions,
                args.max_events,
                priority_patterns,
                exclude_patterns,
            ),
            encoding="utf-8",
        )

    if args.markdown or (not args.json_out and not args.markdown_out):
        print_markdown(
            reports,
            args.source_root,
            args.context,
            args.max_functions,
            args.max_events,
            priority_patterns,
            exclude_patterns,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
