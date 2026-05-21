#!/usr/bin/env python3
"""Compare two .gcov snapshots for single-case incremental coverage evidence.

This script supports path-aware analysis without pretending that gcov provides
full path coverage. It answers a narrower, useful question:

  Did this isolated run increase the counters for the line/branch/call points
  that a proposed execution flow must pass?

Use it after running one small case with a coverage Spike and regenerating
.gcov files. The agent still owns the path interpretation.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


GCOV_SOURCE_LINE_RE = re.compile(r"^\s*(?P<count>[^:]+):\s*(?P<line>\d+):(?P<code>.*)$")
FUNCTION_RE = re.compile(
    r"function\s+(?P<name>\S+)\s+called\s+(?P<called>\d+)\s+returned\s+(?P<returned>\S+)\s+blocks executed\s+(?P<blocks>\S+)"
)
BRANCH_RE = re.compile(r"^\s*branch\s+(?P<num>\d+)\s+(?P<rest>.*)$")
CALL_RE = re.compile(r"^\s*call\s+(?P<num>\d+)\s+(?P<rest>.*)$")


@dataclass(frozen=True)
class EventKey:
    file: str
    kind: str
    source_line: int | None
    ordinal: int | None
    source_code: str
    function_discriminator: str | None = None


@dataclass
class Event:
    file: str
    function: str | None
    mangled_name: str | None
    kind: str
    source_line: int | None
    ordinal: int | None
    source_code: str
    count: int | None
    counter_format: str
    raw: str


@dataclass
class EventDelta:
    file: str
    function: str | None
    mangled_name: str | None
    kind: str
    source_line: int | None
    ordinal: int | None
    source_code: str
    before: int | None
    after: int | None
    before_counter_format: str | None
    after_counter_format: str | None
    delta: int | None
    status: str


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


def parse_count_token(token: str) -> int | None:
    token = token.strip()
    if token == "-":
        return None
    if "#" in token or "=" in token:
        return 0
    token = token.rstrip("*")
    return int(token) if token.isdigit() else None


def parse_branch_or_call_count(rest: str) -> int | None:
    if "never executed" in rest:
        return 0
    match = re.search(r"\b(?:taken|returned)\s+(\d+)(?=$|\s)", rest)
    if match:
        return int(match.group(1))
    return None


def parse_branch_or_call_counter_format(rest: str) -> str:
    if "never executed" in rest:
        return "never"
    if re.search(r"\b(?:taken|returned)\s+\d+(?:\.\d+)?%", rest):
        return "percent"
    if re.search(r"\b(?:taken|returned)\s+\d+(?=$|\s)", rest):
        return "count"
    return "unknown"


def load_target_excludes(path: Path | None) -> list[re.Pattern[str]]:
    if not path:
        return []
    data = json.loads(path.read_text(errors="replace"))
    patterns = data.get("line_exclude_regex", [])
    if not isinstance(patterns, list):
        return []
    return [re.compile(str(pattern), re.IGNORECASE) for pattern in patterns]


def excluded(event: Event, patterns: list[re.Pattern[str]]) -> bool:
    haystack = " ".join(
        [
            event.file,
            event.kind,
            event.function or "",
            event.mangled_name or "",
            str(event.source_line or ""),
            str(event.ordinal or ""),
            event.source_code,
            event.raw,
        ]
    )
    return any(pattern.search(haystack) for pattern in patterns)


def make_key(event: Event, key_mode: str) -> EventKey:
    function_discriminator = None
    if key_mode == "function-aware":
        function_discriminator = f"{event.function or ''}\0{event.mangled_name or ''}"
    return EventKey(
        file=event.file,
        kind=event.kind,
        source_line=event.source_line,
        ordinal=event.ordinal,
        source_code=event.source_code,
        function_discriminator=function_discriminator,
    )


def parse_gcov(path: Path, display_name: str, patterns: list[re.Pattern[str]], key_mode: str) -> dict[EventKey, Event]:
    events: dict[EventKey, Event] = {}
    if not path.exists():
        return events

    last_source_line: int | None = None
    last_source_code = ""
    current_function = "<file-scope>"
    current_mangled: str | None = None

    for line in path.read_text(errors="replace").splitlines():
        function_match = FUNCTION_RE.match(line)
        if function_match:
            current_mangled = function_match.group("name")
            current_function = demangle(current_mangled)
            continue

        src_match = GCOV_SOURCE_LINE_RE.match(line)
        if src_match:
            last_source_line = int(src_match.group("line"))
            last_source_code = src_match.group("code").strip()
            count = parse_count_token(src_match.group("count"))
            if count is not None:
                event = Event(
                    file=display_name,
                    function=current_function,
                    mangled_name=current_mangled,
                    kind="line",
                    source_line=last_source_line,
                    ordinal=None,
                    source_code=last_source_code,
                    count=count,
                    counter_format="count",
                    raw=line.strip(),
                )
                if not excluded(event, patterns):
                    events[make_key(event, key_mode)] = event
            continue

        branch_match = BRANCH_RE.match(line)
        if branch_match:
            event = Event(
                file=display_name,
                function=current_function,
                mangled_name=current_mangled,
                kind="branch",
                source_line=last_source_line,
                ordinal=int(branch_match.group("num")),
                source_code=last_source_code,
                count=parse_branch_or_call_count(branch_match.group("rest")),
                counter_format=parse_branch_or_call_counter_format(branch_match.group("rest")),
                raw=line.strip(),
            )
            if not excluded(event, patterns):
                events[
                    make_key(event, key_mode)
                ] = event
            continue

        call_match = CALL_RE.match(line)
        if call_match:
            event = Event(
                file=display_name,
                function=current_function,
                mangled_name=current_mangled,
                kind="call",
                source_line=last_source_line,
                ordinal=int(call_match.group("num")),
                source_code=last_source_code,
                count=parse_branch_or_call_count(call_match.group("rest")),
                counter_format=parse_branch_or_call_counter_format(call_match.group("rest")),
                raw=line.strip(),
            )
            if not excluded(event, patterns):
                events[
                    make_key(event, key_mode)
                ] = event
            continue

    return events


def collect_gcov_files(before_dir: Path, after_dir: Path, explicit: list[str]) -> list[str]:
    if explicit:
        return list(dict.fromkeys(Path(item).name for item in explicit))
    names = {path.name for path in before_dir.glob("*.gcov")}
    names.update(path.name for path in after_dir.glob("*.gcov"))
    return sorted(names)


def event_matches_focus(event: EventDelta, focus_terms: list[str]) -> bool:
    if not focus_terms:
        return True
    haystack = " ".join(
        [
            event.file,
            event.kind,
            str(event.source_line or ""),
            str(event.ordinal or ""),
            event.source_code,
            event.function or "",
            event.before_counter_format or "",
            event.after_counter_format or "",
        ]
    ).lower()
    return any(term.lower() in haystack for term in focus_terms)


def load_requirements(path: Path | None, cli_items: list[str]) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    if path:
        data = json.loads(path.read_text(errors="replace"))
        if isinstance(data, dict):
            data = data.get("requirements", [])
        if not isinstance(data, list):
            raise TypeError("requirements JSON must be a list or an object with a `requirements` list")
        for item in data:
            if not isinstance(item, dict):
                raise TypeError("each requirement must be an object")
            requirements.append(dict(item))
    for raw in cli_items:
        parts = raw.split(":")
        if len(parts) < 3:
            raise ValueError("--require-event format is file:kind:line[:ordinal]")
        req: dict[str, Any] = {"file": parts[0], "kind": parts[1], "source_line": int(parts[2])}
        if len(parts) >= 4 and parts[3]:
            req["ordinal"] = int(parts[3])
        requirements.append(req)
    return requirements


def requirement_matches_delta(requirement: dict[str, Any], delta: EventDelta) -> bool:
    if requirement.get("file") and Path(str(requirement["file"])).name != Path(delta.file).name:
        return False
    if requirement.get("kind") and str(requirement["kind"]) != delta.kind:
        return False
    if requirement.get("source_line") is not None and int(requirement["source_line"]) != delta.source_line:
        return False
    if requirement.get("ordinal") is not None and int(requirement["ordinal"]) != delta.ordinal:
        return False
    if requirement.get("source_contains") and str(requirement["source_contains"]) not in delta.source_code:
        return False
    if requirement.get("function_contains") and str(requirement["function_contains"]) not in (delta.function or ""):
        return False
    return True


def evaluate_requirements(requirements: list[dict[str, Any]], deltas: list[EventDelta]) -> dict[str, Any]:
    pass_statuses = {"newly-covered", "increased", "unchanged-covered"}
    hard_fail_statuses = {
        "still-zero",
        "missing-after-event",
        "decreased-or-reset",
        "not-comparable-counter-format",
        "unknown",
    }
    items: list[dict[str, Any]] = []
    for idx, requirement in enumerate(requirements, start=1):
        matches = [delta for delta in deltas if requirement_matches_delta(requirement, delta)]
        passing = [delta for delta in matches if delta.status in pass_statuses]
        hard_fails = [delta for delta in matches if delta.status in hard_fail_statuses]
        if passing and not hard_fails:
            status = "passed"
        elif matches:
            status = "failed"
        else:
            status = "missing"
        items.append(
            {
                "id": requirement.get("id", f"req-{idx}"),
                "requirement": requirement,
                "status": status,
                "matched_events": [asdict(delta) for delta in matches[:8]],
            }
        )
    return {
        "all_required_passed": bool(requirements) and all(item["status"] == "passed" for item in items),
        "requirement_count": len(requirements),
        "passed": sum(1 for item in items if item["status"] == "passed"),
        "failed": sum(1 for item in items if item["status"] == "failed"),
        "missing": sum(1 for item in items if item["status"] == "missing"),
        "items": items,
    }


def counter_format_comparable(counter_format: str | None) -> bool:
    return counter_format in {"count", "never", "synthetic-zero"}


def compare_events(
    before: dict[EventKey, Event],
    after: dict[EventKey, Event],
    missing_before_zero: bool,
) -> list[EventDelta]:
    keys = set(after) | set(before)
    deltas: list[EventDelta] = []
    for key in keys:
        before_event = before.get(key)
        after_event = after.get(key)
        if after_event is None:
            before_count = before_event.count if before_event else None
            deltas.append(
                EventDelta(
                    file=key.file,
                    function=before_event.function if before_event else None,
                    mangled_name=before_event.mangled_name if before_event else None,
                    kind=key.kind,
                    source_line=key.source_line,
                    ordinal=key.ordinal,
                    source_code=key.source_code,
                    before=before_count,
                    after=None,
                    before_counter_format=before_event.counter_format if before_event else None,
                    after_counter_format=None,
                    delta=None,
                    status="missing-after-event",
                )
            )
            continue

        before_count = before_event.count if before_event else (0 if missing_before_zero else None)
        before_counter_format = (
            before_event.counter_format if before_event else ("synthetic-zero" if missing_before_zero else None)
        )
        after_count = after_event.count
        after_counter_format = after_event.counter_format
        delta: int | None = None
        status = "missing-before-event" if before_event is None else "unknown"

        if before_count is not None and after_count is not None:
            delta = after_count - before_count
            if before_count <= 0 and after_count > 0:
                status = "newly-covered"
            elif after_count > before_count:
                status = "increased"
            elif after_count < before_count:
                status = "decreased-or-reset"
            elif after_count == 0:
                status = "still-zero"
            else:
                status = "unchanged-covered"
        elif before_event is not None and after_event is not None:
            if not counter_format_comparable(before_counter_format) or not counter_format_comparable(after_counter_format):
                status = "not-comparable-counter-format"
            elif after_count == 0:
                status = "still-zero"
        elif after_event is not None and not counter_format_comparable(after_counter_format):
            status = "not-comparable-counter-format"

        deltas.append(
            EventDelta(
                file=key.file,
                function=after_event.function or (before_event.function if before_event else None),
                mangled_name=after_event.mangled_name or (before_event.mangled_name if before_event else None),
                kind=key.kind,
                source_line=key.source_line,
                ordinal=key.ordinal,
                source_code=key.source_code,
                before=before_count,
                after=after_count,
                before_counter_format=before_counter_format,
                after_counter_format=after_counter_format,
                delta=delta,
                status=status,
            )
        )
    return deltas


def rank_delta(delta: EventDelta) -> tuple[int, str, int, int]:
    status_rank = {
        "newly-covered": 0,
        "increased": 1,
        "decreased-or-reset": 2,
        "missing-after-event": 3,
        "missing-before-event": 4,
        "not-comparable-counter-format": 5,
        "still-zero": 6,
        "unchanged-covered": 7,
        "unknown": 8,
    }.get(delta.status, 5)
    kind_rank = {"branch": 0, "call": 1, "line": 2}.get(delta.kind, 3)
    return (status_rank, delta.file, delta.source_line or -1, kind_rank)


def summarize(
    deltas: list[EventDelta],
    missing_before_files: list[str] | None = None,
    missing_after_files: list[str] | None = None,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    by_kind: dict[str, dict[str, int]] = {}
    counter_formats: dict[str, int] = {}
    for delta in deltas:
        counts[delta.status] = counts.get(delta.status, 0) + 1
        by_kind.setdefault(delta.kind, {})
        by_kind[delta.kind][delta.status] = by_kind[delta.kind].get(delta.status, 0) + 1
        format_pair = f"{delta.before_counter_format or '-'}->{delta.after_counter_format or '-'}"
        counter_formats[format_pair] = counter_formats.get(format_pair, 0) + 1
    file_status_counts = {
        "missing-before-file": len(missing_before_files or []),
        "missing-after-file": len(missing_after_files or []),
    }
    return {
        "status_counts": counts,
        "kind_status_counts": by_kind,
        "counter_format_counts": counter_formats,
        "file_status_counts": file_status_counts,
        "possible_key_drift": detect_possible_key_drift(deltas),
    }


def detect_possible_key_drift(deltas: list[EventDelta]) -> list[dict[str, Any]]:
    missing_after = [delta for delta in deltas if delta.status == "missing-after-event"]
    missing_before = [delta for delta in deltas if delta.status == "missing-before-event"]
    before_keys = {(d.file, d.kind, d.source_line, d.ordinal) for d in missing_before}
    findings: list[dict[str, Any]] = []
    for delta in missing_after:
        key = (delta.file, delta.kind, delta.source_line, delta.ordinal)
        if key in before_keys:
            findings.append(
                {
                    "file": delta.file,
                    "kind": delta.kind,
                    "source_line": delta.source_line,
                    "ordinal": delta.ordinal,
                    "note": "matching missing-before/missing-after at same file/kind/line/ordinal; source/function key may have drifted",
                }
            )
    return findings[:20]


def print_markdown(result: dict[str, Any], limit: int) -> None:
    print("## Single-case gcov increment evidence")
    print()
    print(f"- before_dir: `{result['before_dir']}`")
    print(f"- after_dir: `{result['after_dir']}`")
    if result.get("target"):
        print(f"- target: `{result['target']}`")
    print(f"- key_mode: `{result['key_mode']}`")
    if result.get("missing_before_files"):
        print("- missing before files: `" + "`, `".join(result["missing_before_files"]) + "`")
    if result.get("missing_after_files"):
        print("- missing after files: `" + "`, `".join(result["missing_after_files"]) + "`")
    print("- meaning: this is counter-delta evidence, not full path coverage by itself")
    print("- counter format: branch/call increment proof needs numeric counts, e.g. gcov generated with `-b -c`")
    print(
        "- invalid for path confirmation: `decreased-or-reset`, `missing-after-event`, "
        "`not-comparable-counter-format`, and unresolved missing files/events"
    )
    print()

    print("## Summary")
    print()
    for status, count in sorted(result["summary"]["status_counts"].items()):
        print(f"- {status}: {count}")
    for status, count in sorted(result["summary"].get("file_status_counts", {}).items()):
        if count:
            print(f"- {status}: {count}")
    if result["summary"].get("counter_format_counts"):
        format_bits = [
            f"{name}={count}" for name, count in sorted(result["summary"]["counter_format_counts"].items())
        ]
        print(f"- counter formats: {', '.join(format_bits)}")
    print()
    if result["summary"].get("possible_key_drift"):
        print("## Possible key drift")
        print()
        for item in result["summary"]["possible_key_drift"][:limit]:
            print(
                "- {file} {kind} line={line} ordinal={ordinal}: {note}".format(
                    file=item["file"],
                    kind=item["kind"],
                    line=item["source_line"],
                    ordinal=item["ordinal"],
                    note=item["note"],
                )
            )
        print()

    if result.get("requirements"):
        req = result["requirements"]
        print("## Required evidence points")
        print()
        print(f"- all_required_passed: {req['all_required_passed']}")
        print(f"- passed: {req['passed']} / {req['requirement_count']}")
        print(f"- failed: {req['failed']}")
        print(f"- missing: {req['missing']}")
        print()
        print("| ID | Status | Requirement | Matched statuses |")
        print("|---|---|---|---|")
        for item in req["items"][:limit]:
            requirement = json.dumps(item["requirement"], ensure_ascii=False, sort_keys=True)
            statuses = ", ".join(sorted({event["status"] for event in item["matched_events"]})) or "-"
            print(f"| `{item['id']}` | {item['status']} | `{requirement}` | `{statuses}` |")
        print()

    for title, statuses in (
        ("Newly covered", {"newly-covered"}),
        ("Increased", {"increased"}),
        ("Decreased or reset", {"decreased-or-reset"}),
        ("Missing after", {"missing-after-event"}),
        ("Missing before", {"missing-before-event"}),
        ("Not comparable counter format", {"not-comparable-counter-format"}),
        ("Still zero", {"still-zero"}),
    ):
        rows = [item for item in result["deltas"] if item["status"] in statuses]
        print(f"## {title}")
        print()
        if not rows:
            print("- none")
            print()
            continue
        print("| File | Function | Kind | Line | Ordinal | Before | After | Formats | Delta | Source |")
        print("|---|---|---|---:|---:|---:|---:|---|---:|---|")
        for item in rows[:limit]:
            source = str(item["source_code"]).replace("|", "\\|")
            print(
                "| {file} | `{function}` | {kind} | {line} | {ordinal} | {before} | {after} | {formats} | {delta} | `{source}` |".format(
                    file=item["file"],
                    function=(item.get("function") or "-").replace("|", "\\|"),
                    kind=item["kind"],
                    line=item["source_line"] if item["source_line"] is not None else "-",
                    ordinal=item["ordinal"] if item["ordinal"] is not None else "-",
                    before=item["before"] if item["before"] is not None else "-",
                    after=item["after"] if item["after"] is not None else "-",
                    formats=f"{item.get('before_counter_format') or '-'}->{item.get('after_counter_format') or '-'}",
                    delta=item["delta"] if item["delta"] is not None else "-",
                    source=source,
                )
            )
        if len(rows) > limit:
            print(f"- ... (+{len(rows) - limit})")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-dir", required=True, type=Path, help="directory containing baseline .gcov files")
    parser.add_argument("--after-dir", required=True, type=Path, help="directory containing post-run .gcov files")
    parser.add_argument("--file", action="append", default=[], help=".gcov file name to compare; can be repeated")
    parser.add_argument("--target", type=Path, help="target JSON; uses line_exclude_regex for filtering")
    parser.add_argument("--focus", action="append", default=[], help="substring filter on file/source/kind; can be repeated")
    parser.add_argument("--requirements-json", type=Path, help="JSON requirements that must be covered for this path")
    parser.add_argument(
        "--require-event",
        action="append",
        default=[],
        help="must-pass event shorthand file:kind:line[:ordinal]; can be repeated",
    )
    parser.add_argument(
        "--key-mode",
        choices=("stable-line", "function-aware"),
        default="stable-line",
        help="event matching key; stable-line ignores function name drift, function-aware includes function metadata",
    )
    parser.add_argument(
        "--missing-before-zero",
        action="store_true",
        help="treat events missing from the before snapshot as count 0",
    )
    parser.add_argument("--json-out", type=Path, help="write machine-readable comparison JSON")
    parser.add_argument("--markdown", action="store_true", help="print markdown")
    parser.add_argument("--limit", type=int, default=40, help="rows per markdown section")
    args = parser.parse_args()

    patterns = load_target_excludes(args.target)
    files = collect_gcov_files(args.before_dir, args.after_dir, args.file)

    before_events: dict[EventKey, Event] = {}
    after_events: dict[EventKey, Event] = {}
    missing_before: list[str] = []
    missing_after: list[str] = []
    for name in files:
        before_path = args.before_dir / name
        after_path = args.after_dir / name
        if not before_path.exists():
            missing_before.append(name)
        if not after_path.exists():
            missing_after.append(name)
        before_events.update(parse_gcov(before_path, name, patterns, args.key_mode))
        after_events.update(parse_gcov(after_path, name, patterns, args.key_mode))

    deltas = compare_events(before_events, after_events, args.missing_before_zero)
    deltas = [delta for delta in deltas if event_matches_focus(delta, args.focus)]
    deltas = sorted(deltas, key=rank_delta)
    requirements = load_requirements(args.requirements_json, args.require_event)
    requirement_result = evaluate_requirements(requirements, deltas)

    result = {
        "before_dir": str(args.before_dir),
        "after_dir": str(args.after_dir),
        "target": str(args.target) if args.target else None,
        "key_mode": args.key_mode,
        "files": files,
        "missing_before_files": missing_before,
        "missing_after_files": missing_after,
        "summary": summarize(deltas, missing_before, missing_after),
        "requirements": requirement_result,
        "deltas": [asdict(delta) for delta in deltas],
        "interpretation_rule": (
            "newly-covered/increased confirms counter movement for a required edge/call/line in this "
            "isolated run. If all required points move in a tiny single-purpose case, confidence is high; "
            "otherwise mark edge-covered-path-unknown or use path markers. decreased-or-reset and missing "
            "events/files are invalid for positive path confirmation until explained. "
            "not-comparable-counter-format means gcov did not provide numeric branch/call counts, commonly "
            "because the snapshot was generated as percentages instead of count mode."
        ),
    }

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    if args.markdown or not args.json_out:
        print_markdown(result, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
