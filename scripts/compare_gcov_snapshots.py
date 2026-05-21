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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


GCOV_SOURCE_LINE_RE = re.compile(r"^\s*(?P<count>[^:]+):\s*(?P<line>\d+):(?P<code>.*)$")
BRANCH_RE = re.compile(r"^\s*branch\s+(?P<num>\d+)\s+(?P<rest>.*)$")
CALL_RE = re.compile(r"^\s*call\s+(?P<num>\d+)\s+(?P<rest>.*)$")


@dataclass(frozen=True)
class EventKey:
    file: str
    kind: str
    source_line: int | None
    ordinal: int | None
    source_code: str


@dataclass
class Event:
    file: str
    kind: str
    source_line: int | None
    ordinal: int | None
    source_code: str
    count: int | None
    raw: str


@dataclass
class EventDelta:
    file: str
    kind: str
    source_line: int | None
    ordinal: int | None
    source_code: str
    before: int | None
    after: int | None
    delta: int | None
    status: str


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
    match = re.search(r"\b(?:taken|returned)\s+(\d+)\b", rest)
    if match:
        return int(match.group(1))
    return None


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
            str(event.source_line or ""),
            str(event.ordinal or ""),
            event.source_code,
            event.raw,
        ]
    )
    return any(pattern.search(haystack) for pattern in patterns)


def parse_gcov(path: Path, display_name: str, patterns: list[re.Pattern[str]]) -> dict[EventKey, Event]:
    events: dict[EventKey, Event] = {}
    if not path.exists():
        return events

    last_source_line: int | None = None
    last_source_code = ""

    for line in path.read_text(errors="replace").splitlines():
        src_match = GCOV_SOURCE_LINE_RE.match(line)
        if src_match:
            last_source_line = int(src_match.group("line"))
            last_source_code = src_match.group("code").strip()
            count = parse_count_token(src_match.group("count"))
            if count is not None:
                event = Event(
                    file=display_name,
                    kind="line",
                    source_line=last_source_line,
                    ordinal=None,
                    source_code=last_source_code,
                    count=count,
                    raw=line.strip(),
                )
                if not excluded(event, patterns):
                    events[
                        EventKey(
                            file=display_name,
                            kind=event.kind,
                            source_line=event.source_line,
                            ordinal=event.ordinal,
                            source_code=event.source_code,
                        )
                    ] = event
            continue

        branch_match = BRANCH_RE.match(line)
        if branch_match:
            event = Event(
                file=display_name,
                kind="branch",
                source_line=last_source_line,
                ordinal=int(branch_match.group("num")),
                source_code=last_source_code,
                count=parse_branch_or_call_count(branch_match.group("rest")),
                raw=line.strip(),
            )
            if not excluded(event, patterns):
                events[
                    EventKey(
                        file=display_name,
                        kind=event.kind,
                        source_line=event.source_line,
                        ordinal=event.ordinal,
                        source_code=event.source_code,
                    )
                ] = event
            continue

        call_match = CALL_RE.match(line)
        if call_match:
            event = Event(
                file=display_name,
                kind="call",
                source_line=last_source_line,
                ordinal=int(call_match.group("num")),
                source_code=last_source_code,
                count=parse_branch_or_call_count(call_match.group("rest")),
                raw=line.strip(),
            )
            if not excluded(event, patterns):
                events[
                    EventKey(
                        file=display_name,
                        kind=event.kind,
                        source_line=event.source_line,
                        ordinal=event.ordinal,
                        source_code=event.source_code,
                    )
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
        ]
    ).lower()
    return any(term.lower() in haystack for term in focus_terms)


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
            continue

        before_count = before_event.count if before_event else (0 if missing_before_zero else None)
        after_count = after_event.count
        delta: int | None = None
        status = "unknown"

        if before_count is not None and after_count is not None:
            delta = after_count - before_count
            if before_count <= 0 and after_count > 0:
                status = "newly-covered"
            elif after_count > before_count:
                status = "increased"
            elif after_count == 0:
                status = "still-zero"
            else:
                status = "unchanged-covered"
        elif after_count == 0:
            status = "still-zero"

        deltas.append(
            EventDelta(
                file=key.file,
                kind=key.kind,
                source_line=key.source_line,
                ordinal=key.ordinal,
                source_code=key.source_code,
                before=before_count,
                after=after_count,
                delta=delta,
                status=status,
            )
        )
    return deltas


def rank_delta(delta: EventDelta) -> tuple[int, str, int, int]:
    status_rank = {
        "newly-covered": 0,
        "increased": 1,
        "still-zero": 2,
        "unchanged-covered": 3,
        "unknown": 4,
    }.get(delta.status, 5)
    kind_rank = {"branch": 0, "call": 1, "line": 2}.get(delta.kind, 3)
    return (status_rank, delta.file, delta.source_line or -1, kind_rank)


def summarize(deltas: list[EventDelta]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    by_kind: dict[str, dict[str, int]] = {}
    for delta in deltas:
        counts[delta.status] = counts.get(delta.status, 0) + 1
        by_kind.setdefault(delta.kind, {})
        by_kind[delta.kind][delta.status] = by_kind[delta.kind].get(delta.status, 0) + 1
    return {"status_counts": counts, "kind_status_counts": by_kind}


def print_markdown(result: dict[str, Any], limit: int) -> None:
    print("## Single-case gcov increment evidence")
    print()
    print(f"- before_dir: `{result['before_dir']}`")
    print(f"- after_dir: `{result['after_dir']}`")
    if result.get("target"):
        print(f"- target: `{result['target']}`")
    print("- meaning: this is counter-delta evidence, not full path coverage by itself")
    print()

    print("## Summary")
    print()
    for status, count in sorted(result["summary"]["status_counts"].items()):
        print(f"- {status}: {count}")
    print()

    for title, statuses in (
        ("Newly covered", {"newly-covered"}),
        ("Increased", {"increased"}),
        ("Still zero", {"still-zero"}),
    ):
        rows = [item for item in result["deltas"] if item["status"] in statuses]
        print(f"## {title}")
        print()
        if not rows:
            print("- none")
            print()
            continue
        print("| File | Kind | Line | Ordinal | Before | After | Delta | Source |")
        print("|---|---|---:|---:|---:|---:|---:|---|")
        for item in rows[:limit]:
            source = str(item["source_code"]).replace("|", "\\|")
            print(
                "| {file} | {kind} | {line} | {ordinal} | {before} | {after} | {delta} | `{source}` |".format(
                    file=item["file"],
                    kind=item["kind"],
                    line=item["source_line"] if item["source_line"] is not None else "-",
                    ordinal=item["ordinal"] if item["ordinal"] is not None else "-",
                    before=item["before"] if item["before"] is not None else "-",
                    after=item["after"] if item["after"] is not None else "-",
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
    missing_after: list[str] = []
    for name in files:
        before_events.update(parse_gcov(args.before_dir / name, name, patterns))
        parsed_after = parse_gcov(args.after_dir / name, name, patterns)
        if not parsed_after:
            missing_after.append(name)
        after_events.update(parsed_after)

    deltas = compare_events(before_events, after_events, args.missing_before_zero)
    deltas = [delta for delta in deltas if event_matches_focus(delta, args.focus)]
    deltas = sorted(deltas, key=rank_delta)

    result = {
        "before_dir": str(args.before_dir),
        "after_dir": str(args.after_dir),
        "target": str(args.target) if args.target else None,
        "files": files,
        "missing_after_files": missing_after,
        "summary": summarize(deltas),
        "deltas": [asdict(delta) for delta in deltas],
        "interpretation_rule": (
            "newly-covered/increased confirms counter movement for a required edge/call/line in this "
            "isolated run. If all required points move in a tiny single-purpose case, confidence is high; "
            "otherwise mark path-correlation-unknown or use path markers."
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
