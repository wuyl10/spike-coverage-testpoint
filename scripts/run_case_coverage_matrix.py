#!/usr/bin/env python3
"""Run hyptest ELFs one by one and collect per-case Spike gcov deltas.

This is an evidence generator for path-aware coverage work:

1. select cases using get_result.py-like selectors;
2. reset coverage counters for each case;
3. run exactly one ELF with the coverage Spike;
4. regenerate .gcov snapshots before/after the run;
5. compare the snapshots and write a final matrix report.

The report does not decide architecture intent by itself. It gives the agent
the per-case counter evidence needed to judge missing paths and test points.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_HYPTEST_REPO = Path("/nfs/home/wuyuanlong/workspace/riscv-hyp-tests-nhv5.1")
DEFAULT_SPIKE_COV_REPO = Path("/nfs/home/wuyuanlong/workspace/offical-spike-coverage")
DEFAULT_BUILD_DIR = DEFAULT_SPIKE_COV_REPO / "build-cov"
DEFAULT_TARGET = SKILL_ROOT / "targets" / "memblock_non_h.json"
ARTIFACT_MAP_FILE = "artifact_name_map.json"
SHORT_RUN_NAME_LIMIT = 80
SHORT_RUN_NAME_PREFIX = 48
WHOLE_WORD_MARKERS = {"PASSED", "FAILED"}
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

DEFAULT_SPIKE_ISA = (
    "rv64IMAFDCV_zicond_zicntr_zihpm_zba_zbb_zbc_zbs_zbkb_zbkc_zbkx_"
    "zimop_zcmop_zcb_zknd_zkne_zknh_zksed_zksh_zvbb_svinval_sscofpmf_svpbmt_"
    "zicbom_zicboz_sstc_svnapot_smstateen_zicclsm"
)
DEFAULT_COMMAND_TEMPLATE = (
    "{spike_bin} "
    f"--isa={DEFAULT_SPIKE_ISA} "
    "{elf}"
)
DEFAULT_REQUIRED_MARKERS = ["PASSED"]
DEFAULT_FORBIDDEN_MARKERS = ["FAILED", "untested exception", "ERROR:"]


@dataclass
class CaseSpec:
    name: str
    elf_path: Path
    run_name: str
    suggestions: list[str]


@dataclass
class GcovSnapshot:
    out_dir: Path
    commands: list[str]
    returncodes: list[int]
    stdout_stderr_log: Path
    generated_files: list[str]
    failed_commands: int


@dataclass
class RunnerResult:
    status: str
    command: str
    returncode: int | None
    timed_out: bool
    missing_required: list[str]
    found_forbidden: list[str]
    scope_warnings: list[str]
    setup_notes: list[str]
    log_path: Path


@dataclass
class CaseMatrixResult:
    index: int
    case_name: str
    run_name: str
    elf_path: str
    suggestions: list[str]
    status: str
    runner: dict[str, Any] | None
    before_snapshot: dict[str, Any] | None
    after_snapshot: dict[str, Any] | None
    compare_json: str | None
    compare_markdown: str | None
    requirements: dict[str, Any] | None
    coverage_status_counts: dict[str, int]
    file_status_counts: dict[str, int]
    gcda_after_run: dict[str, bool]
    gcda_missing_after_run: list[str]
    compared_files: list[str]
    top_changed_files: list[dict[str, Any]]
    top_still_zero_files: list[dict[str, Any]]
    entry_changed_files: list[dict[str, Any]]
    entry_still_zero_files: list[dict[str, Any]]
    changed_counter_count: int
    invalid_evidence_count: int
    evidence_use: str
    case_dir: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hyptest-repo", type=Path, default=DEFAULT_HYPTEST_REPO)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET, help="target JSON for scope filters")
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR, help="Spike coverage build dir")
    parser.add_argument("--spike-bin", type=Path, help="coverage Spike executable; overrides env")
    parser.add_argument(
        "--elf-dir",
        type=Path,
        help="directory containing case ELFs; default is <hyptest-repo>/case_elf_asm/spike",
    )
    parser.add_argument("--out-dir", type=Path, help="output directory; default is /tmp/spike_cov_case_matrix_<time>")

    selectors = parser.add_argument_group("case selection")
    selectors.add_argument("--case", action="append", default=[], help="case name to run; repeatable")
    selectors.add_argument("--elf", action="append", default=[], help="explicit ELF path to run; repeatable")
    selectors.add_argument("--case-list", action="append", default=[], help="file with case names or ELF paths")
    selectors.add_argument("--all-elves", action="store_true", help="select mapped ELFs under --elf-dir")
    selectors.add_argument(
        "--include-unmapped-elves",
        action="store_true",
        help="with --all-elves, also include unmapped ai_*.ELF files",
    )
    selectors.add_argument("--exclude-case", action="append", default=[], help="case to skip; repeatable")
    selectors.add_argument("--exclude-list", action="append", default=[], help="file with cases to skip")
    selectors.add_argument(
        "--case-regex",
        action="append",
        default=[],
        help="keep only selected case names matching this regex; repeatable",
    )
    selectors.add_argument("--limit", type=int, default=0, help="run only the first N selected cases")

    runner = parser.add_argument_group("runner")
    runner.add_argument(
        "--command-template",
        default=DEFAULT_COMMAND_TEMPLATE,
        help=(
            "runner command template. Supports {spike_bin}, {elf}, {elf_name}, "
            "{elf_dir}, {case_name}, {run_name}, and {case_dir}"
        ),
    )
    runner.add_argument("--timeout", type=float, default=15.0)
    runner.add_argument("--required-marker", action="append", default=None)
    runner.add_argument("--forbidden-marker", action="append", default=None)
    runner.add_argument("--keep-ansi", action="store_true")
    runner.add_argument(
        "--fail-on-case-fail",
        action="store_true",
        help="return nonzero when any case runner status is not PASS",
    )

    gcov = parser.add_argument_group("gcov")
    gcov.add_argument("--gcov-tool", default="gcov")
    gcov.add_argument("--gcno", action="append", default=[], help=".gcno path/name or .gcov hint; repeatable")
    gcov.add_argument("--gcno-list", action="append", default=[], help="file with .gcno path/name entries")
    gcov.add_argument(
        "--gcno-from-target",
        action="store_true",
        help="resolve .gcno files from target inspection_hints/source_priority",
    )
    gcov.add_argument(
        "--dimension",
        action="append",
        default=[],
        help="when using --gcno-from-target, only use matching target dimension names; repeatable",
    )
    gcov.add_argument(
        "--reset-scope",
        choices=("selected", "all", "none"),
        default="selected",
        help="which .gcda counters to delete before each case",
    )
    gcov.add_argument(
        "--skip-gcov",
        action="store_true",
        help="run cases and logs only; do not generate snapshots or comparisons",
    )

    compare = parser.add_argument_group("snapshot compare")
    compare.add_argument("--compare-file", action="append", default=[], help=".gcov file to compare; repeatable")
    compare.add_argument(
        "--compare-files-from-target",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="when --compare-file is absent, compare only target inspection/source-priority .gcov files",
    )
    compare.add_argument("--focus", action="append", default=[], help="focus term passed to compare_gcov_snapshots")
    compare.add_argument("--requirements-json", action="append", default=[], help="global requirements JSON")
    compare.add_argument("--requirements-dir", type=Path, help="case-specific requirements JSON directory")
    compare.add_argument("--require-event", action="append", default=[], help="file:kind:line[:ordinal]")
    compare.add_argument(
        "--key-mode",
        choices=("stable-line", "function-aware"),
        default="stable-line",
    )
    compare.add_argument(
        "--missing-before-zero",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="treat before-missing events as zero during comparison",
    )
    compare.add_argument("--compare-limit", type=int, default=40)

    parser.add_argument("--dry-run", action="store_true", help="show selected cases/gcno files and exit")
    return parser.parse_args()


def resolve_path(path: str | Path, base: Path | None = None) -> Path:
    expanded = Path(os.path.expandvars(str(path))).expanduser()
    if expanded.is_absolute():
        return expanded
    return (base or Path.cwd()) / expanded


def normalize_case_name_token(token: str) -> str:
    name = token.strip()
    if not name:
        return ""
    name = name.split("#", 1)[0].split("//", 1)[0].strip()
    if not name:
        return ""
    path = Path(name)
    if path.suffix == ".ELF":
        return path.stem
    return path.name


def unique_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def make_run_name(case_name: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", case_name)
    if len(safe_name) <= SHORT_RUN_NAME_LIMIT:
        return safe_name
    digest = hashlib.sha1(case_name.encode("utf-8")).hexdigest()[:16]
    return f"{safe_name[:SHORT_RUN_NAME_PREFIX]}__{digest}"


def load_artifact_map(elf_dir: Path) -> dict[str, str]:
    map_path = elf_dir / ARTIFACT_MAP_FILE
    if not map_path.exists():
        return {}
    try:
        payload = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return {}
    return {
        str(case_name): str(artifact_stem)
        for case_name, artifact_stem in artifacts.items()
        if isinstance(case_name, str) and isinstance(artifact_stem, str)
    }


def discover_cases_from_elf_dir(
    elf_dir: Path,
    artifact_map: dict[str, str],
    include_unmapped_elves: bool,
) -> tuple[list[str], int]:
    cases: list[str] = []
    seen_case_names: set[str] = set()
    mapped_stems: set[str] = set()
    skipped_unmapped = 0

    for case_name, artifact_stem in artifact_map.items():
        if (elf_dir / f"{artifact_stem}.ELF").exists():
            cases.append(case_name)
            seen_case_names.add(case_name)
            mapped_stems.add(artifact_stem)

    for path in sorted(elf_dir.glob("ai_*.ELF")):
        stem = path.stem
        if stem in mapped_stems or stem in seen_case_names:
            continue
        if artifact_map and not include_unmapped_elves:
            skipped_unmapped += 1
            continue
        cases.append(stem)
        seen_case_names.add(stem)

    return cases, skipped_unmapped


def resolve_elf_path(case_name: str, elf_dir: Path, artifact_map: dict[str, str]) -> Path:
    artifact_stem = artifact_map.get(case_name)
    if artifact_stem:
        return elf_dir / f"{artifact_stem}.ELF"
    return elf_dir / f"{case_name}.ELF"


def suggest_case_names(case_name: str, elf_dir: Path, artifact_map: dict[str, str], limit: int = 6) -> list[str]:
    candidates = sorted(set(artifact_map) | {path.stem for path in elf_dir.glob("*.ELF")})
    if not candidates:
        return []
    lower_case = case_name.lower()
    token_hits = [
        candidate
        for candidate in candidates
        if lower_case in candidate.lower() or candidate.lower() in lower_case
    ]
    close = difflib.get_close_matches(case_name, candidates, n=limit, cutoff=0.58)
    return unique_keep_order(token_hits[:limit] + close)[:limit]


def read_case_tokens(list_paths: Iterable[str], base: Path) -> list[str]:
    tokens: list[str] = []
    for raw_path in list_paths:
        path = resolve_path(raw_path, base)
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            token = line.split("#", 1)[0].split("//", 1)[0].strip()
            if token:
                tokens.append(token)
    return tokens


def select_cases(args: argparse.Namespace, elf_dir: Path, artifact_map: dict[str, str]) -> tuple[list[CaseSpec], str]:
    explicit_elves: list[Path] = [resolve_path(item, args.hyptest_repo) for item in args.elf]
    for token in read_case_tokens(args.case_list, args.hyptest_repo):
        path = Path(os.path.expandvars(token)).expanduser()
        if token.endswith(".ELF") or path.is_absolute():
            explicit_elves.append(resolve_path(token, args.hyptest_repo))
        else:
            args.case.append(token)

    source_desc = ""
    case_names: list[str] = []
    if args.case:
        case_names.extend(normalize_case_name_token(item) for item in args.case)
        source_desc = "explicit --case/--case-list names"
    if args.all_elves:
        discovered, skipped_unmapped = discover_cases_from_elf_dir(
            elf_dir,
            artifact_map,
            include_unmapped_elves=args.include_unmapped_elves,
        )
        case_names.extend(discovered)
        source_desc = "mapped ELF artifacts under elf dir"
        if args.include_unmapped_elves:
            source_desc = "mapped and unmapped ai ELFs under elf dir"
        elif skipped_unmapped:
            source_desc += f" (skipped {skipped_unmapped} stale unmapped ai ELFs)"
    if explicit_elves:
        source_desc = (source_desc + "; " if source_desc else "") + "explicit --elf paths"

    excluded = {normalize_case_name_token(item) for item in args.exclude_case}
    for token in read_case_tokens(args.exclude_list, args.hyptest_repo):
        excluded.add(normalize_case_name_token(token))
    excluded.discard("")

    specs: list[CaseSpec] = []
    for case_name in unique_keep_order(name for name in case_names if name):
        if case_name in excluded:
            continue
        elf_path = resolve_elf_path(case_name, elf_dir, artifact_map)
        suggestions = [] if elf_path.exists() else suggest_case_names(case_name, elf_dir, artifact_map)
        specs.append(CaseSpec(case_name, elf_path, make_run_name(case_name), suggestions))

    for elf_path in explicit_elves:
        case_name = normalize_case_name_token(str(elf_path))
        if not case_name or case_name in excluded:
            continue
        suggestions = [] if elf_path.exists() else suggest_case_names(case_name, elf_dir, artifact_map)
        specs.append(CaseSpec(case_name, elf_path, make_run_name(case_name), suggestions))

    deduped: list[CaseSpec] = []
    seen: set[tuple[str, str]] = set()
    for spec in specs:
        key = (spec.name, str(spec.elf_path))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)

    if args.case_regex:
        patterns = [re.compile(pattern) for pattern in args.case_regex]
        before_count = len(deduped)
        deduped = [spec for spec in deduped if any(pattern.search(spec.name) for pattern in patterns)]
        source_desc += f" (case-regex kept {len(deduped)}/{before_count})"

    if args.limit:
        deduped = deduped[: max(args.limit, 0)]
        source_desc += f" (limit {args.limit})"

    return deduped, source_desc or "no explicit case selector"


def marker_present(output: str, marker: str) -> bool:
    if marker in WHOLE_WORD_MARKERS:
        return re.search(rf"\b{re.escape(marker)}\b", output) is not None
    return marker in output


def scope_warning_patterns_from_target(target: dict[str, Any]) -> list[tuple[str, re.Pattern[str]]]:
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for item in target.get("scope_out", []):
        text = str(item).lower()
        if "hs/vs/vu" in text or "virtualization" in text:
            patterns.extend(
                [
                    ("scope_out: HS/VS/VU virtualization text", re.compile(r"\b(?:hs|vs|vu)\s+", re.IGNORECASE)),
                    ("scope_out: HS/VS/VU virtualization text", re.compile(r"\b(?:hs|vs|vu)[_-]", re.IGNORECASE)),
                ]
            )
        if "hgatp" in text:
            patterns.append(("scope_out: hgatp/vsatp/henvcfg control path", re.compile(r"\b(?:hgatp|vsatp|henvcfg)\b", re.IGNORECASE)))
        if "stage2" in text:
            patterns.append(("scope_out: stage2 translation text", re.compile(r"\b(?:stage2|stage\s*2|s2xlate)\b", re.IGNORECASE)))
        if "guest page" in text:
            patterns.append(("scope_out: guest page fault text", re.compile(r"\bguest page fault\b|\btrap_.*guest_page_fault\b", re.IGNORECASE)))
        if "hlv" in text or "hsv" in text:
            patterns.append(("scope_out: H load/store instruction text", re.compile(r"\b(?:hlv|hlvx|hsv)[a-z0-9_.]*\b", re.IGNORECASE)))
    deduped: list[tuple[str, re.Pattern[str]]] = []
    seen: set[tuple[str, str]] = set()
    for label, pattern in patterns:
        key = (label, pattern.pattern)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, pattern))
    return deduped


def find_scope_warnings(output: str, patterns: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    warnings: list[str] = []
    for label, pattern in patterns:
        match = pattern.search(output)
        if not match:
            continue
        snippet_start = max(output.rfind("\n", 0, match.start()) + 1, 0)
        snippet_end = output.find("\n", match.end())
        if snippet_end == -1:
            snippet_end = min(len(output), match.end() + 120)
        snippet = output[snippet_start:snippet_end].strip()
        warnings.append(f"{label}: {snippet[:220]}")
    return unique_keep_order(warnings)


def normalize_output(output: str, keep_ansi: bool) -> str:
    if keep_ansi:
        return output
    return ANSI_ESCAPE_RE.sub("", output)


def output_to_text(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def resolve_runner_spike_bin(env: dict[str, str]) -> str:
    spike_bin = env.get("HYPTEST_SPIKE_BIN") or env.get("SPIKE_BIN")
    if not spike_bin:
        raise ValueError("set --spike-bin, HYPTEST_SPIKE_BIN, or SPIKE_BIN to the coverage Spike executable")
    return spike_bin


def build_command(
    command_template: str,
    elf_path: Path,
    case_name: str,
    run_name: str,
    case_dir: Path,
    env: dict[str, str],
) -> str:
    placeholders = {
        "spike_bin": shlex.quote(resolve_runner_spike_bin(env)),
        "elf": shlex.quote(str(elf_path)),
        "elf_name": shlex.quote(elf_path.name),
        "elf_dir": shlex.quote(str(elf_path.parent)),
        "case_name": shlex.quote(case_name),
        "run_name": shlex.quote(run_name),
        "case_dir": shlex.quote(str(case_dir)),
    }
    if not any(f"{{{name}}}" in command_template for name in placeholders):
        raise ValueError(
            'command template must contain one of "{spike_bin}", "{elf}", "{elf_name}", '
            '"{elf_dir}", "{case_name}", "{run_name}", or "{case_dir}"'
        )
    return command_template.format(**placeholders)


def make_runner_env(spike_bin: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    if spike_bin:
        env["HYPTEST_SPIKE_BIN"] = str(spike_bin)
    elif not env.get("HYPTEST_SPIKE_BIN") and env.get("SPIKE_BIN"):
        env["HYPTEST_SPIKE_BIN"] = env["SPIKE_BIN"]
    if env.get("HYPTEST_SPIKE_BIN") and not env.get("SPIKE_BIN"):
        env["SPIKE_BIN"] = env["HYPTEST_SPIKE_BIN"]
    return env


def run_case(
    spec: CaseSpec,
    args: argparse.Namespace,
    env: dict[str, str],
    case_dir: Path,
    scope_warning_patterns: list[tuple[str, re.Pattern[str]]],
) -> RunnerResult:
    log_path = case_dir / "run.log"
    if not spec.elf_path.exists():
        setup_notes = [f"missing ELF: {spec.elf_path}"]
        setup_notes.extend(f"similar case: {name}" for name in spec.suggestions)
        message = "\n".join(setup_notes) + "\n"
        log_path.write_text(message, encoding="utf-8")
        return RunnerResult("MISSING_ELF", "", None, False, [], [], [], setup_notes, log_path)

    try:
        command = build_command(args.command_template, spec.elf_path, spec.name, spec.run_name, case_dir, env)
        completed = subprocess.run(
            shlex.split(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=args.timeout,
            check=False,
        )
        raw_output = (completed.stdout or "") + (completed.stderr or "")
        returncode: int | None = completed.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        command = build_command(args.command_template, spec.elf_path, spec.name, spec.run_name, case_dir, env)
        raw_output = output_to_text(exc.stdout) + output_to_text(exc.stderr)
        raw_output += f"\nTIMEOUT: exceeded {args.timeout} seconds\n"
        returncode = 124
        timed_out = True
    except Exception as exc:
        command = ""
        raw_output = f"runner setup failed: {exc}\n"
        returncode = 1
        timed_out = False

    output = normalize_output(raw_output, args.keep_ansi)
    log_path.write_text(output, encoding="utf-8", errors="replace")
    required_markers = args.required_marker or list(DEFAULT_REQUIRED_MARKERS)
    forbidden_markers = args.forbidden_marker or list(DEFAULT_FORBIDDEN_MARKERS)
    missing_required = [marker for marker in required_markers if not marker_present(output, marker)]
    found_forbidden = [marker for marker in forbidden_markers if marker_present(output, marker)]
    scope_warnings = find_scope_warnings(output, scope_warning_patterns)

    if timed_out:
        status = "TIMEOUT"
    elif output.startswith("runner setup failed"):
        status = "RUNNER_ERROR"
    elif returncode != 0:
        status = "NONZERO_EXIT"
    elif missing_required or found_forbidden:
        status = "MARKER_MISMATCH"
    else:
        status = "PASS"

    return RunnerResult(status, command, returncode, timed_out, missing_required, found_forbidden, scope_warnings, [], log_path)


def load_target(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def dimension_selected(name: str, filters: list[str]) -> bool:
    if not filters:
        return True
    lower_name = name.lower()
    return any(item.lower() in lower_name for item in filters)


def gcov_hint_to_stems(hint: str) -> list[str]:
    name = Path(str(hint)).name
    if name.endswith(".gcov"):
        name = name[:-5]
    stems = [name]
    for suffix in (".cc", ".cpp", ".cxx", ".c", ".h", ".hpp"):
        if name.endswith(suffix):
            stems.append(name[: -len(suffix)])
    return unique_keep_order(stem for stem in stems if stem)


def resolve_gcno_token(token: str, build_dir: Path) -> tuple[list[Path], list[str]]:
    token = token.strip()
    if not token:
        return [], []

    token_path = Path(os.path.expandvars(token)).expanduser()
    if token_path.is_absolute() and token_path.exists():
        return [token_path], []
    if any(char in token for char in "*?[]"):
        matches = sorted(build_dir.rglob(token))
        return [path for path in matches if path.suffix == ".gcno"], [] if matches else [token]

    stems = gcov_hint_to_stems(token)
    if token_path.suffix == ".gcno":
        stems.insert(0, token_path.stem)
    candidates: list[Path] = []
    for stem in unique_keep_order(stems):
        direct = build_dir / f"{stem}.gcno"
        if direct.exists():
            candidates.append(direct)
            continue
        candidates.extend(sorted(build_dir.rglob(f"{stem}.gcno")))
    candidates = unique_paths(candidates)
    return candidates, [] if candidates else [token]


def unique_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def read_gcno_list(paths: Iterable[str], base: Path) -> list[str]:
    tokens: list[str] = []
    for raw_path in paths:
        path = resolve_path(raw_path, base)
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            token = line.split("#", 1)[0].strip()
            if token:
                tokens.append(token)
    return tokens


def target_gcno_tokens(target: dict[str, Any], dimensions: list[str]) -> list[str]:
    tokens: list[str] = []
    inspection_hints = target.get("inspection_hints", {})
    if isinstance(inspection_hints, dict):
        for dim_name, hints in inspection_hints.items():
            if not dimension_selected(str(dim_name), dimensions):
                continue
            if isinstance(hints, list):
                tokens.extend(str(item) for item in hints)
    source_priority = target.get("source_priority", [])
    if isinstance(source_priority, list) and not dimensions:
        for item in source_priority:
            name = Path(str(item)).name
            if name:
                tokens.append(f"{name}.gcov")
    return unique_keep_order(tokens)


def target_compare_file_names(target: dict[str, Any], dimensions: list[str]) -> list[str]:
    names: list[str] = []
    inspection_hints = target.get("inspection_hints", {})
    if isinstance(inspection_hints, dict):
        for dim_name, hints in inspection_hints.items():
            if not dimension_selected(str(dim_name), dimensions):
                continue
            if isinstance(hints, list):
                names.extend(Path(str(item)).name for item in hints if str(item).endswith(".gcov"))
    source_priority = target.get("source_priority", [])
    if isinstance(source_priority, list) and not dimensions:
        for item in source_priority:
            name = Path(str(item)).name
            if name:
                names.append(f"{name}.gcov")
    return unique_keep_order(name for name in names if name)


def resolve_gcno_paths(args: argparse.Namespace, target: dict[str, Any]) -> tuple[list[Path], list[str], list[str]]:
    tokens: list[str] = []
    tokens.extend(args.gcno)
    tokens.extend(read_gcno_list(args.gcno_list, SKILL_ROOT))
    target_tokens: list[str] = []
    if args.gcno_from_target:
        target_tokens = target_gcno_tokens(target, args.dimension)
        tokens.extend(target_tokens)

    resolved: list[Path] = []
    unresolved: list[str] = []
    for token in unique_keep_order(tokens):
        paths, missing = resolve_gcno_token(token, args.build_dir)
        resolved.extend(paths)
        unresolved.extend(missing)

    return unique_paths(resolved), unique_keep_order(unresolved), target_tokens


def reset_gcda(build_dir: Path, gcno_paths: list[Path], scope: str) -> list[str]:
    deleted: list[str] = []
    if scope == "none":
        return deleted
    if scope == "all":
        paths = sorted(build_dir.rglob("*.gcda"))
    else:
        paths = [path.with_suffix(".gcda") for path in gcno_paths]
    for path in unique_paths(paths):
        if not path.exists():
            continue
        try:
            path.unlink()
            deleted.append(str(path))
        except OSError:
            pass
    return deleted


def gcda_presence(gcno_paths: list[Path]) -> dict[str, bool]:
    return {path.with_suffix(".gcda").name: path.with_suffix(".gcda").exists() for path in gcno_paths}


def missing_gcda_after_run(gcno_paths: list[Path], generated_gcov_files: list[str]) -> list[str]:
    generated_set = set(generated_gcov_files)
    missing: list[str] = []
    for path in gcno_paths:
        gcda_name = path.with_suffix(".gcda").name
        source_name = f"{path.stem}.cc.gcov"
        header_name = f"{path.stem}.h.gcov"
        if path.with_suffix(".gcda").exists():
            continue
        if source_name in generated_set or header_name in generated_set:
            missing.append(gcda_name)
    return missing


def parse_created_gcov_files(output: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r"(?:Creating|Removing)\s+'([^']+\.gcov)'", output):
        names.append(Path(match.group(1)).name)
    return unique_keep_order(names)


def generate_gcov_snapshot(
    gcov_tool: str,
    build_dir: Path,
    gcno_paths: list[Path],
    out_dir: Path,
) -> GcovSnapshot:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "gcov.log"
    commands: list[str] = []
    returncodes: list[int] = []
    log_chunks: list[str] = []
    failed = 0
    created_files: set[str] = set()
    for gcno_path in gcno_paths:
        cmd = [gcov_tool, "-b", "-c", "-o", str(build_dir), str(gcno_path)]
        commands.append(" ".join(shlex.quote(part) for part in cmd))
        completed = subprocess.run(
            cmd,
            cwd=build_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        returncodes.append(completed.returncode)
        if completed.returncode != 0:
            failed += 1
        log_chunks.append(f"$ {commands[-1]}\n")
        log_chunks.append(completed.stdout or "")
        log_chunks.append(completed.stderr or "")
        if log_chunks and not log_chunks[-1].endswith("\n"):
            log_chunks.append("\n")
        for name in parse_created_gcov_files((completed.stdout or "") + (completed.stderr or "")):
            source_path = build_dir / name
            if not source_path.exists():
                continue
            target_path = out_dir / name
            shutil.copy2(source_path, target_path)
            created_files.add(name)
            try:
                source_path.unlink()
            except OSError:
                pass
    log_path.write_text("".join(log_chunks), encoding="utf-8", errors="replace")
    generated = sorted(created_files | {path.name for path in out_dir.glob("*.gcov")})
    return GcovSnapshot(out_dir, commands, returncodes, log_path, generated, failed)


def load_requirements_payload(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(data, dict):
        data = data.get("requirements", [])
    if not isinstance(data, list):
        raise TypeError(f"requirements JSON must be a list or object with requirements: {path}")
    return [dict(item) for item in data if isinstance(item, dict)]


def case_requirement_paths(args: argparse.Namespace, spec: CaseSpec) -> list[Path]:
    paths: list[Path] = [resolve_path(item, SKILL_ROOT) for item in args.requirements_json]
    if args.requirements_dir:
        req_dir = resolve_path(args.requirements_dir, SKILL_ROOT)
        for name in (f"{spec.name}.json", f"{spec.run_name}.json", "default.json", "requirements.json"):
            candidate = req_dir / name
            if candidate.exists():
                paths.append(candidate)
    return unique_paths(paths)


def write_combined_requirements(paths: list[Path], out_path: Path) -> Path | None:
    requirements: list[dict[str, Any]] = []
    for path in paths:
        requirements.extend(load_requirements_payload(path))
    if not requirements:
        return None
    out_path.write_text(json.dumps({"requirements": requirements}, indent=2, ensure_ascii=False) + "\n")
    return out_path


def compare_snapshots(
    args: argparse.Namespace,
    spec: CaseSpec,
    before_dir: Path,
    after_dir: Path,
    case_dir: Path,
    default_compare_files: list[str],
) -> tuple[Path, Path, dict[str, Any]]:
    compare_json = case_dir / "compare.json"
    compare_md = case_dir / "compare.md"
    requirement_paths = case_requirement_paths(args, spec)
    combined_requirements = write_combined_requirements(requirement_paths, case_dir / "requirements.combined.json")

    if args.compare_file:
        files = list(dict.fromkeys(Path(name).name for name in args.compare_file))
    elif args.compare_files_from_target and default_compare_files:
        available = {path.name for path in before_dir.glob("*.gcov")} | {path.name for path in after_dir.glob("*.gcov")}
        files = [name for name in default_compare_files if name in available]
    else:
        files = sorted({path.name for path in before_dir.glob("*.gcov")} | {path.name for path in after_dir.glob("*.gcov")})
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "compare_gcov_snapshots.py"),
        "--before-dir",
        str(before_dir),
        "--after-dir",
        str(after_dir),
        "--target",
        str(args.target),
        "--json-out",
        str(compare_json),
        "--markdown-out",
        str(compare_md),
        "--key-mode",
        args.key_mode,
        "--limit",
        str(args.compare_limit),
    ]
    if args.missing_before_zero:
        cmd.append("--missing-before-zero")
    for name in files:
        cmd.extend(["--file", name])
    for focus in args.focus:
        cmd.extend(["--focus", focus])
    if combined_requirements:
        cmd.extend(["--requirements-json", str(combined_requirements)])
    for event in args.require_event:
        cmd.extend(["--require-event", event])

    completed = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.stdout or completed.stderr:
        compare_md.with_suffix(".log").write_text(
            (completed.stdout or "") + (completed.stderr or ""),
            encoding="utf-8",
            errors="replace",
        )
    if not compare_json.exists():
        compare_json.write_text(
            json.dumps(
                {
                    "error": "compare_gcov_snapshots.py did not produce json",
                    "returncode": completed.returncode,
                    "command": cmd,
                },
                indent=2,
            )
            + "\n"
        )
    payload = json.loads(compare_json.read_text(encoding="utf-8", errors="replace"))
    return compare_json, compare_md, payload


def count_invalid_evidence(compare_payload: dict[str, Any]) -> int:
    summary = compare_payload.get("summary", {})
    status_counts = summary.get("status_counts", {})
    file_counts = summary.get("file_status_counts", {})
    invalid_statuses = [
        "decreased-or-reset",
        "missing-after-event",
        "not-comparable-counter-format",
        "missing-before-event",
    ]
    return sum(int(status_counts.get(name, 0)) for name in invalid_statuses) + sum(
        int(file_counts.get(name, 0)) for name in ("missing-before-file", "missing-after-file")
    )


def summarize_case_compare(compare_payload: dict[str, Any]) -> tuple[dict[str, int], dict[str, int], int, int]:
    summary = compare_payload.get("summary", {})
    status_counts = {str(k): int(v) for k, v in summary.get("status_counts", {}).items()}
    file_status_counts = {str(k): int(v) for k, v in summary.get("file_status_counts", {}).items()}
    changed = int(status_counts.get("newly-covered", 0)) + int(status_counts.get("increased", 0))
    invalid = count_invalid_evidence(compare_payload)
    return status_counts, file_status_counts, changed, invalid


def summarize_top_files(
    compare_payload: dict[str, Any],
    statuses: set[str],
    priority_files: list[str] | None = None,
    include_files: set[str] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    priority_rank = {Path(name).name: index for index, name in enumerate(priority_files or [])}
    by_file: dict[str, dict[str, Any]] = {}
    for delta in compare_payload.get("deltas", []):
        if not isinstance(delta, dict):
            continue
        status = str(delta.get("status", ""))
        if status not in statuses:
            continue
        file_name = str(delta.get("file", ""))
        if not file_name:
            continue
        if include_files is not None and file_name not in include_files:
            continue
        item = by_file.setdefault(
            file_name,
            {
                "file": file_name,
                "target_priority_rank": priority_rank.get(file_name),
                "total_events": 0,
                "line": 0,
                "branch": 0,
                "call": 0,
                "statuses": {},
                "max_delta": 0,
            },
        )
        item["total_events"] += 1
        kind = str(delta.get("kind", ""))
        if kind in ("line", "branch", "call"):
            item[kind] += 1
        item["statuses"][status] = int(item["statuses"].get(status, 0)) + 1
        try:
            item["max_delta"] = max(int(item["max_delta"]), int(delta.get("delta") or 0))
        except (TypeError, ValueError):
            pass

    return sorted(
        by_file.values(),
        key=lambda item: (
            item.get("target_priority_rank") is None,
            item.get("target_priority_rank") if item.get("target_priority_rank") is not None else 10**9,
            -int(item["total_events"]),
            str(item["file"]),
        ),
    )[:limit]


def summarize_entry_files(
    compare_payload: dict[str, Any],
    statuses: set[str],
    priority_files: list[str] | None = None,
    case_name: str = "",
    limit: int = 8,
) -> list[dict[str, Any]]:
    entry_candidates: list[str] = []
    lower_case_name = case_name.lower()
    matched: list[str] = []
    unmatched: list[str] = []
    for file_name in priority_files or []:
        name = Path(file_name).name
        if name.endswith(".h.gcov") and name not in {
            "mmu.h.gcov",
            "trap.h.gcov",
            "bloom_filter.h.gcov",
            "memtracer.h.gcov",
            "v_ext_macros.h.gcov",
        }:
            stem = name[:-7] if name.endswith(".h.gcov") else Path(name).stem
            if stem in lower_case_name:
                matched.append(name)
            else:
                unmatched.append(name)
    entry_candidates = matched + unmatched
    return summarize_top_files(
        compare_payload,
        statuses,
        priority_files=entry_candidates,
        limit=limit,
        include_files=set(entry_candidates),
    )


def snapshot_to_dict(snapshot: GcovSnapshot) -> dict[str, Any]:
    return {
        "out_dir": str(snapshot.out_dir),
        "generated_files": snapshot.generated_files,
        "failed_commands": snapshot.failed_commands,
        "log_path": str(snapshot.stdout_stderr_log),
        "commands": snapshot.commands,
        "returncodes": snapshot.returncodes,
    }


def runner_to_dict(runner: RunnerResult) -> dict[str, Any]:
    return {
        "status": runner.status,
        "command": runner.command,
        "returncode": runner.returncode,
        "timed_out": runner.timed_out,
        "missing_required": runner.missing_required,
        "found_forbidden": runner.found_forbidden,
        "scope_warnings": runner.scope_warnings,
        "setup_notes": runner.setup_notes,
        "issue_summary": summarize_runner_issue(runner),
        "log_path": str(runner.log_path),
    }


def runner_execution_attempted(status: str) -> bool:
    return status not in {"MISSING_ELF", "RUNNER_ERROR"}


def evidence_use_for_case(
    status: str,
    changed_counter_count: int,
    invalid_evidence_count: int,
    has_scope_warnings: bool,
) -> str:
    if status in {"MISSING_ELF", "RUNNER_ERROR"}:
        return "no-execution-evidence"
    if status != "PASS":
        if changed_counter_count:
            return "diagnostic-only-nonpass-counter-movement"
        return "diagnostic-only-nonpass-no-counter-movement"
    if invalid_evidence_count:
        return "pass-but-invalid-counter-evidence"
    if has_scope_warnings and changed_counter_count:
        return "pass-counter-evidence-scope-review-required"
    if has_scope_warnings:
        return "pass-scope-review-required-no-target-counter-movement"
    if changed_counter_count:
        return "pass-counter-evidence-needs-source-pc-review"
    return "pass-no-target-counter-movement"


def summarize_runner_issue(runner: RunnerResult, max_items: int = 8) -> list[str]:
    if runner.status == "PASS":
        return []

    notes: list[str] = []
    if runner.timed_out:
        notes.append("timed out")
    if runner.returncode not in (0, None):
        notes.append(f"nonzero exit {runner.returncode}")
    if runner.missing_required:
        notes.append("missing required marker(s): " + ", ".join(runner.missing_required))
    if runner.found_forbidden:
        notes.append("found forbidden marker(s): " + ", ".join(runner.found_forbidden))
    if runner.scope_warnings:
        notes.extend(runner.scope_warnings[: max_items])
    if runner.setup_notes:
        notes.extend(runner.setup_notes[: max_items])

    try:
        lines = runner.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return notes[:max_items]

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line == "FAILED":
            notes.append("overall FAILED")
        elif line.startswith(("assert_site:", "assert_expr:", "excpt:", "TIMEOUT:", "runner setup failed:", "ERROR:")):
            notes.append(line)
        elif "untested exception" in line:
            notes.append(line)
        if len(notes) >= max_items:
            break
    return notes[:max_items]


def run_matrix(
    args: argparse.Namespace,
    cases: list[CaseSpec],
    gcno_paths: list[Path],
    default_compare_files: list[str],
    target: dict[str, Any],
) -> list[CaseMatrixResult]:
    env = make_runner_env(args.spike_bin)
    scope_warning_patterns = scope_warning_patterns_from_target(target)
    results: list[CaseMatrixResult] = []
    total = len(cases)
    case_root = args.out_dir / "cases"
    case_root.mkdir(parents=True, exist_ok=True)

    for index, spec in enumerate(cases, start=1):
        case_dir = case_root / f"{index:04d}_{spec.run_name}"
        case_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{index}/{total}] {spec.name}: reset={args.reset_scope}")
        deleted = reset_gcda(args.build_dir, gcno_paths, args.reset_scope)
        (case_dir / "reset_before.txt").write_text("\n".join(deleted) + ("\n" if deleted else ""), encoding="utf-8")

        before_snapshot: GcovSnapshot | None = None
        after_snapshot: GcovSnapshot | None = None
        compare_json: Path | None = None
        compare_md: Path | None = None
        compare_payload: dict[str, Any] | None = None
        status_counts: dict[str, int] = {}
        file_status_counts: dict[str, int] = {}
        gcda_after: dict[str, bool] = {}
        missing_gcda: list[str] = []
        compared_files: list[str] = []
        top_changed_files: list[dict[str, Any]] = []
        top_still_zero_files: list[dict[str, Any]] = []
        entry_changed_files: list[dict[str, Any]] = []
        entry_still_zero_files: list[dict[str, Any]] = []
        changed = 0
        invalid = 0

        if not args.skip_gcov and spec.elf_path.exists():
            before_snapshot = generate_gcov_snapshot(args.gcov_tool, args.build_dir, gcno_paths, case_dir / "before_gcov")

        runner = run_case(spec, args, env, case_dir, scope_warning_patterns)
        print(f"[{index}/{total}] {spec.name}: runner={runner.status}")
        if not args.skip_gcov:
            gcda_after = gcda_presence(gcno_paths)

        if not args.skip_gcov and before_snapshot and runner_execution_attempted(runner.status):
            after_snapshot = generate_gcov_snapshot(args.gcov_tool, args.build_dir, gcno_paths, case_dir / "after_gcov")
            missing_gcda = missing_gcda_after_run(gcno_paths, after_snapshot.generated_files)
            compare_json, compare_md, compare_payload = compare_snapshots(
                args,
                spec,
                before_snapshot.out_dir,
                after_snapshot.out_dir,
                case_dir,
                default_compare_files,
            )
            compared_files = compare_payload.get("files", [])
            status_counts, file_status_counts, changed, invalid = summarize_case_compare(compare_payload)
            top_changed_files = summarize_top_files(
                compare_payload,
                {"newly-covered", "increased"},
                priority_files=default_compare_files,
            )
            top_still_zero_files = summarize_top_files(
                compare_payload,
                {"still-zero"},
                priority_files=default_compare_files,
            )
            entry_changed_files = summarize_entry_files(
                compare_payload,
                {"newly-covered", "increased"},
                priority_files=default_compare_files,
                case_name=spec.name,
            )
            entry_still_zero_files = summarize_entry_files(
                compare_payload,
                {"still-zero"},
                priority_files=default_compare_files,
                case_name=spec.name,
            )
            print(
                f"[{index}/{total}] {spec.name}: changed={changed} invalid_evidence={invalid} "
                f"missing_gcda={len(missing_gcda)} "
                f"req_all={compare_payload.get('requirements', {}).get('all_required_passed')}"
            )

        requirements = compare_payload.get("requirements") if compare_payload else None
        results.append(
            CaseMatrixResult(
                index=index,
                case_name=spec.name,
                run_name=spec.run_name,
                elf_path=str(spec.elf_path),
                suggestions=spec.suggestions,
                status=runner.status,
                runner=runner_to_dict(runner),
                before_snapshot=snapshot_to_dict(before_snapshot) if before_snapshot else None,
                after_snapshot=snapshot_to_dict(after_snapshot) if after_snapshot else None,
                compare_json=str(compare_json) if compare_json else None,
                compare_markdown=str(compare_md) if compare_md else None,
                requirements=requirements,
                coverage_status_counts=status_counts,
                file_status_counts=file_status_counts,
                gcda_after_run=gcda_after,
                gcda_missing_after_run=missing_gcda,
                compared_files=compared_files,
                top_changed_files=top_changed_files,
                top_still_zero_files=top_still_zero_files,
                entry_changed_files=entry_changed_files,
                entry_still_zero_files=entry_still_zero_files,
                changed_counter_count=changed,
                invalid_evidence_count=invalid,
                evidence_use=evidence_use_for_case(runner.status, changed, invalid, bool(runner.scope_warnings)),
                case_dir=str(case_dir),
            )
        )

    return results


def count_by(items: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


def aggregate_coverage_counts(results: list[CaseMatrixResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        for status, count in result.coverage_status_counts.items():
            counts[status] = counts.get(status, 0) + int(count)
    return counts


def cases_with_scope_warnings(results: list[CaseMatrixResult]) -> list[str]:
    names: list[str] = []
    for result in results:
        runner = result.runner or {}
        if runner.get("scope_warnings"):
            names.append(result.case_name)
    return names


def build_summary_payload(
    args: argparse.Namespace,
    cases: list[CaseSpec],
    source_desc: str,
    gcno_paths: list[Path],
    unresolved_gcno: list[str],
    target_tokens: list[str],
    default_compare_files: list[str],
    results: list[CaseMatrixResult],
    dry_run: bool,
) -> dict[str, Any]:
    requirement_cases = [result for result in results if result.requirements]
    all_required_passed = [
        result.case_name
        for result in requirement_cases
        if result.requirements and result.requirements.get("all_required_passed")
    ]
    nonpass_counter_movement_cases = [
        result.case_name
        for result in results
        if result.status != "PASS" and result.changed_counter_count > 0
    ]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "hyptest_repo": str(args.hyptest_repo),
        "elf_dir": str(args.elf_dir),
        "target": str(args.target),
        "build_dir": str(args.build_dir),
        "out_dir": str(args.out_dir),
        "case_source": source_desc,
        "selected_case_count": len(cases),
        "selected_cases": [asdict(case) | {"elf_path": str(case.elf_path)} for case in cases],
        "gcno_count": len(gcno_paths),
        "gcno_paths": [str(path) for path in gcno_paths],
        "gcno_tokens_from_target": target_tokens,
        "unresolved_gcno_tokens": unresolved_gcno,
        "default_compare_files": default_compare_files,
        "reset_scope": args.reset_scope,
        "skip_gcov": args.skip_gcov,
        "runner_status_counts": count_by(result.status for result in results),
        "coverage_status_counts": aggregate_coverage_counts(results),
        "cases_with_counter_changes": [
            result.case_name for result in results if result.changed_counter_count > 0
        ],
        "pass_cases_with_counter_changes": [
            result.case_name for result in results if result.status == "PASS" and result.changed_counter_count > 0
        ],
        "nonpass_cases_with_counter_changes": nonpass_counter_movement_cases,
        "cases_with_invalid_evidence": [
            result.case_name for result in results if result.invalid_evidence_count > 0
        ],
        "cases_with_no_execution_evidence": [
            result.case_name for result in results if result.evidence_use == "no-execution-evidence"
        ],
        "cases_with_missing_target_gcda": [
            result.case_name
            for result in results
            if result.status == "PASS" and result.gcda_missing_after_run
        ],
        "nonpass_cases_with_missing_target_gcda": [
            result.case_name
            for result in results
            if result.status != "PASS" and result.gcda_missing_after_run
        ],
        "cases_with_scope_warnings": cases_with_scope_warnings(results),
        "cases_with_all_required_passed": all_required_passed,
        "results": [asdict(result) for result in results],
        "interpretation_rule": (
            "This matrix is single-case counter evidence. A changed counter means the isolated run moved "
            "a line/branch/call counter. It becomes path evidence only after the agent checks the Spike "
            "source, required evidence points, runner log/PC evidence, and target scope. Invalid evidence "
            "statuses such as decreased-or-reset, missing events/files, or not-comparable counter format "
            "must be explained before positive path claims."
        ),
    }


def md_table_escape(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def format_top_files(items: list[dict[str, Any]], limit: int = 8) -> str:
    if not items:
        return "-"
    parts: list[str] = []
    for item in items[:limit]:
        counts = []
        for kind in ("line", "branch", "call"):
            count = int(item.get(kind, 0))
            if count:
                counts.append(f"{kind[0]}={count}")
        counts_text = ",".join(counts) if counts else f"events={item.get('total_events', 0)}"
        parts.append(f"{item.get('file')}({counts_text})")
    if len(items) > limit:
        parts.append(f"+{len(items) - limit} files")
    return "; ".join(parts)


def format_runner_issue(result: dict[str, Any], limit: int = 3) -> str:
    runner = result.get("runner") or {}
    notes = runner.get("issue_summary") or []
    if not notes:
        return "-"
    text = "; ".join(str(item) for item in notes[:limit])
    if len(notes) > limit:
        text += f"; +{len(notes) - limit} more"
    return text


def format_suggestions(result: dict[str, Any], limit: int = 4) -> str:
    suggestions = result.get("suggestions") or []
    if not suggestions:
        runner = result.get("runner") or {}
        setup_notes = runner.get("setup_notes") or []
        suggestions = [
            str(note).split("similar case: ", 1)[1]
            for note in setup_notes
            if str(note).startswith("similar case: ")
        ]
    if not suggestions:
        return "-"
    text = ", ".join(f"`{item}`" for item in suggestions[:limit])
    if len(suggestions) > limit:
        text += f", +{len(suggestions) - limit} more"
    return text


def write_markdown_report(payload: dict[str, Any], path: Path) -> None:
    lines: list[str] = []
    lines.append("# Spike per-case coverage matrix")
    lines.append("")
    lines.append("## Conclusion")
    lines.append("")
    status_counts = payload.get("runner_status_counts", {})
    status_text = ", ".join(f"{status}={count}" for status, count in sorted(status_counts.items())) or "no cases executed"
    cov_counts = payload.get("coverage_status_counts", {})
    changed = int(cov_counts.get("newly-covered", 0)) + int(cov_counts.get("increased", 0))
    still_zero = int(cov_counts.get("still-zero", 0))
    lines.append(f"- Runner status: {status_text}.")
    lines.append(f"- Coverage movement: changed counters={changed}, still-zero events={still_zero}.")
    lines.append(
        f"- Positive evidence candidates: PASS counter-movement cases={len(payload.get('pass_cases_with_counter_changes', []))}; "
        f"non-PASS counter-movement cases={len(payload.get('nonpass_cases_with_counter_changes', []))}; "
        f"no-execution cases={len(payload.get('cases_with_no_execution_evidence', []))}; "
        f"scope-warning cases={len(payload.get('cases_with_scope_warnings', []))}."
    )
    lines.append("- Use this report as evidence. Final missing-scenario/test-point conclusions require source review and target-scope checks.")
    lines.append("")
    lines.append("## Data")
    lines.append("")
    lines.append(f"- selected_case_count: {payload.get('selected_case_count')}")
    lines.append(f"- gcno_count: {payload.get('gcno_count')}")
    lines.append(f"- default_compare_file_count: {len(payload.get('default_compare_files', []))}")
    lines.append(f"- reset_scope: `{payload.get('reset_scope')}`")
    lines.append(f"- dry_run: `{payload.get('dry_run')}`")
    lines.append("")
    lines.append("## Limits / Next steps")
    lines.append("")
    lines.append("- Per-case counter movement is evidence, not final path proof.")
    lines.append("- Use only PASS and in-scope counter movement as positive coverage leads; non-PASS movement is diagnostic-only.")
    lines.append("- Inspect per-case `compare.md`, run logs, and Spike source before writing test-point cards.")
    lines.append("- Use requirements or path markers when a same instruction/access flow must be proven.")
    lines.append("")
    lines.append("## Evidence")
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    for key in ("hyptest_repo", "elf_dir", "target", "build_dir", "out_dir", "case_source"):
        lines.append(f"- {key}: `{payload.get(key)}`")
    lines.append(f"- selected_case_count: {payload.get('selected_case_count')}")
    lines.append(f"- gcno_count: {payload.get('gcno_count')}")
    lines.append(f"- default_compare_file_count: {len(payload.get('default_compare_files', []))}")
    lines.append(f"- reset_scope: `{payload.get('reset_scope')}`")
    lines.append(f"- dry_run: `{payload.get('dry_run')}`")
    lines.append("")

    if payload.get("unresolved_gcno_tokens"):
        lines.append("## Unresolved gcno hints")
        lines.append("")
        lines.append(
            "These target hints did not resolve to a standalone `.gcno`. "
            "Header `.gcov` files may still be generated by another selected object such as `mmu.gcno`."
        )
        lines.append("")
        for token in payload["unresolved_gcno_tokens"][:80]:
            lines.append(f"- `{token}`")
        if len(payload["unresolved_gcno_tokens"]) > 80:
            lines.append(f"- ... (+{len(payload['unresolved_gcno_tokens']) - 80})")
        lines.append("")

    lines.append("## Selected cases")
    lines.append("")
    if payload.get("selected_cases"):
        lines.append("| # | Case | ELF | Suggestions |")
        lines.append("|---:|---|---|---|")
        for idx, case in enumerate(payload["selected_cases"][:120], start=1):
            suggestions = case.get("suggestions") or []
            suggestion_text = "-"
            if suggestions:
                suggestion_text = ", ".join(f"`{item}`" for item in suggestions[:4])
                if len(suggestions) > 4:
                    suggestion_text += f", +{len(suggestions) - 4} more"
            lines.append(
                f"| {idx} | `{md_table_escape(case.get('name'))}` | `{md_table_escape(case.get('elf_path'))}` | {md_table_escape(suggestion_text)} |"
            )
        if len(payload["selected_cases"]) > 120:
            lines.append(f"| ... | ... | +{len(payload['selected_cases']) - 120} more |")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("### Runner status")
    lines.append("")
    if payload.get("runner_status_counts"):
        for status, count in sorted(payload["runner_status_counts"].items()):
            lines.append(f"- {status}: {count}")
    else:
        lines.append("- no cases executed")
    lines.append("")

    lines.append("### Coverage movement")
    lines.append("")
    if payload.get("coverage_status_counts"):
        for status, count in sorted(payload["coverage_status_counts"].items()):
            lines.append(f"- {status}: {count}")
    else:
        lines.append("- no gcov comparison data")
    lines.append("")
    lines.append(f"- cases_with_counter_changes: {len(payload.get('cases_with_counter_changes', []))}")
    lines.append(f"- pass_cases_with_counter_changes: {len(payload.get('pass_cases_with_counter_changes', []))}")
    lines.append(f"- nonpass_cases_with_counter_changes: {len(payload.get('nonpass_cases_with_counter_changes', []))}")
    lines.append(f"- cases_with_invalid_evidence: {len(payload.get('cases_with_invalid_evidence', []))}")
    lines.append(f"- cases_with_no_execution_evidence: {len(payload.get('cases_with_no_execution_evidence', []))}")
    lines.append(f"- cases_with_missing_target_gcda: {len(payload.get('cases_with_missing_target_gcda', []))}")
    lines.append(f"- cases_with_scope_warnings: {len(payload.get('cases_with_scope_warnings', []))}")
    lines.append(f"- cases_with_all_required_passed: {len(payload.get('cases_with_all_required_passed', []))}")
    lines.append("")

    missing_elf_results = [
        result
        for result in payload.get("results", [])
        if result.get("status") == "MISSING_ELF"
    ]
    if missing_elf_results:
        lines.append("## Missing ELF diagnostics")
        lines.append("")
        lines.append(
            "These cases did not execute Spike. They are selection/setup issues, not coverage evidence. "
            "Fix the case name, artifact map, or ELF path before using them in path analysis."
        )
        lines.append("")
        for result in missing_elf_results:
            lines.append(
                f"- `{result.get('case_name')}`: `{result.get('elf_path')}`; suggestions: {format_suggestions(result)}"
            )
        lines.append("")

    if payload.get("cases_with_missing_target_gcda"):
        lines.append("## Cases with missing target gcda after run")
        lines.append("")
        lines.append(
            "These PASS cases executed Spike, but at least one selected target object generated `.gcov` "
            "from a missing `.gcda`. That usually means the case did not execute that Spike object, "
            "or the selected case is outside the intended target area."
        )
        lines.append("")
        for result in payload.get("results", []):
            missing = result.get("gcda_missing_after_run") or []
            if not missing:
                continue
            if result.get("status") != "PASS":
                continue
            preview = ", ".join(missing[:12])
            if len(missing) > 12:
                preview += f", ... (+{len(missing) - 12})"
            lines.append(f"- `{result.get('case_name')}`: {preview}")
        lines.append("")

    if payload.get("nonpass_cases_with_counter_changes"):
        lines.append("## Non-PASS cases with counter movement")
        lines.append("")
        lines.append(
            "These cases moved coverage counters but did not pass the runner markers. Treat their deltas "
            "as diagnostic breadcrumbs only, not positive same-flow/path proof."
        )
        lines.append("")
        for result in payload.get("results", []):
            if result.get("status") == "PASS" or not result.get("changed_counter_count"):
                continue
            lines.append(
                f"- `{result.get('case_name')}`: status={result.get('status')}, "
                f"counter_changes={result.get('changed_counter_count')}, evidence_use=`{result.get('evidence_use')}`"
            )
        lines.append("")

    if payload.get("cases_with_all_required_passed"):
        lines.append("## Cases with all required evidence points passed")
        lines.append("")
        for name in payload["cases_with_all_required_passed"]:
            lines.append(f"- `{name}`")
        lines.append("")

    if payload.get("cases_with_scope_warnings"):
        lines.append("## Target scope warnings")
        lines.append("")
        lines.append(
            "These cases passed the runner, but their logs match target `scope_out` language. "
            "Do not use them as in-scope positive evidence until the target/profile decision is checked."
        )
        lines.append("")
        for result in payload.get("results", []):
            runner = result.get("runner") or {}
            warnings = runner.get("scope_warnings") or []
            if not warnings:
                continue
            preview = "; ".join(warnings[:4])
            if len(warnings) > 4:
                preview += f"; +{len(warnings) - 4} more"
            lines.append(f"- `{result.get('case_name')}`: {md_table_escape(preview)}")
        lines.append("")

    non_pass_results = [
        result
        for result in payload.get("results", [])
        if result.get("status") not in (None, "PASS")
    ]
    if non_pass_results:
        lines.append("## Runner issues")
        lines.append("")
        lines.append(
            "These are runner/log issues only. Coverage counters may still move, but do not use a failed "
            "case for positive path proof until the log issue is understood."
        )
        lines.append("")
        for result in non_pass_results:
            lines.append(f"- `{result.get('case_name')}`: {format_runner_issue(result, limit=5)}")
        lines.append("")

    if payload.get("results") and not payload.get("skip_gcov"):
        lines.append("## Per-case coverage highlights")
        lines.append("")
        lines.append(
            "| # | Case | Evidence use | Newly covered / increased top files | Entry/header movement | Still-zero entry/header | Still-zero top files |"
        )
        lines.append("|---:|---|---|---|---|---|---|")
        for result in payload.get("results", []):
            lines.append(
                "| {idx} | `{case}` | `{evidence_use}` | {changed} | {entry_changed} | {entry_zero} | {zero} |".format(
                    idx=result.get("index"),
                    case=md_table_escape(result.get("case_name")),
                    evidence_use=md_table_escape(result.get("evidence_use", "-")),
                    changed=md_table_escape(format_top_files(result.get("top_changed_files") or [])),
                    entry_changed=md_table_escape(format_top_files(result.get("entry_changed_files") or [])),
                    entry_zero=md_table_escape(format_top_files(result.get("entry_still_zero_files") or [])),
                    zero=md_table_escape(format_top_files(result.get("top_still_zero_files") or [])),
                )
            )
        lines.append("")

    lines.append("## Per-case matrix")
    lines.append("")
    lines.append(
        "| # | Case | Runner | Evidence use | Req passed | Counter changes | Missing gcda | Invalid evidence | Compare | Run log |"
    )
    lines.append("|---:|---|---|---|---|---:|---:|---:|---|---|")
    for result in payload.get("results", []):
        req = result.get("requirements") or {}
        req_text = "-"
        if req.get("requirement_count"):
            req_text = (
                f"{req.get('all_required_passed')} "
                f"({req.get('passed')}/{req.get('requirement_count')}, "
                f"failed={req.get('failed')}, missing={req.get('missing')})"
            )
        runner = result.get("runner") or {}
        run_log = runner.get("log_path") or "-"
        compare = result.get("compare_markdown") or "-"
        lines.append(
            "| {idx} | `{case}` | {status} | `{evidence_use}` | {req} | {changed} | {missing_gcda} | {invalid} | `{compare}` | `{run_log}` |".format(
                idx=result.get("index"),
                case=md_table_escape(result.get("case_name")),
                status=md_table_escape(result.get("status")),
                evidence_use=md_table_escape(result.get("evidence_use", "-")),
                req=md_table_escape(req_text),
                changed=result.get("changed_counter_count", 0),
                missing_gcda=len(result.get("gcda_missing_after_run") or []),
                invalid=result.get("invalid_evidence_count", 0),
                compare=md_table_escape(compare),
                run_log=md_table_escape(run_log),
            )
        )
    lines.append("")

    lines.append("## Agent interpretation checklist")
    lines.append("")
    lines.append("- Treat this report as evidence, not as a final test-point recommendation.")
    lines.append("- For a positive same-flow claim, inspect the case log/PC evidence and the exact must-pass source events.")
    lines.append("- If all relevant edges moved but correlation is unclear, mark `counter-increment-observed` or `edge-covered-path-unknown`.")
    lines.append("- If any required event is missing, still zero, decreased/reset, or not comparable, do not claim the path was covered.")
    lines.append("- Use the selected target file to decide scope, manual/special-run status, and exclusions.")
    lines.append("")
    lines.append("## Interpretation rule")
    lines.append("")
    lines.append(payload.get("interpretation_rule", ""))
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_dry_run_report(payload: dict[str, Any], args: argparse.Namespace) -> None:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_json = args.out_dir / "summary.json"
    summary_md = args.out_dir / "summary.md"
    summary_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown_report(payload, summary_md)
    print(f"dry_run=true")
    print(f"selected_case_count={payload['selected_case_count']}")
    print(f"gcno_count={payload['gcno_count']}")
    print(f"summary_json={summary_json}")
    print(f"summary_md={summary_md}")
    if payload.get("unresolved_gcno_tokens"):
        print(f"unresolved_gcno_tokens={len(payload['unresolved_gcno_tokens'])}")


def main() -> int:
    args = parse_args()
    args.hyptest_repo = resolve_path(args.hyptest_repo)
    args.build_dir = resolve_path(args.build_dir)
    args.target = resolve_path(args.target, SKILL_ROOT) if args.target else None
    args.elf_dir = resolve_path(args.elf_dir, args.hyptest_repo) if args.elf_dir else args.hyptest_repo / "case_elf_asm" / "spike"
    args.out_dir = resolve_path(args.out_dir) if args.out_dir else Path(f"/tmp/spike_cov_case_matrix_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    args.spike_bin = resolve_path(args.spike_bin) if args.spike_bin else None

    if not args.case and not args.elf and not args.case_list and not args.all_elves:
        print("error: select cases with --case, --case-list, --elf, or --all-elves", file=sys.stderr)
        return 2
    if args.limit < 0:
        print("error: --limit must be >= 0", file=sys.stderr)
        return 2
    if not args.dry_run and not args.skip_gcov and not args.build_dir.exists():
        print(f"error: build dir not found: {args.build_dir}", file=sys.stderr)
        return 2
    if not args.elf_dir.exists() and not args.elf:
        print(f"error: elf dir not found: {args.elf_dir}", file=sys.stderr)
        return 2

    target = load_target(args.target) if args.target and args.target.exists() else {}
    artifact_map = load_artifact_map(args.elf_dir)
    cases, source_desc = select_cases(args, args.elf_dir, artifact_map)
    if not cases:
        print("error: no cases selected", file=sys.stderr)
        return 2

    gcno_paths, unresolved_gcno, target_tokens = resolve_gcno_paths(args, target)
    default_compare_files = target_compare_file_names(target, args.dimension)
    if not args.skip_gcov and not args.dry_run and not gcno_paths:
        print(
            "error: no .gcno files selected; use --gcno, --gcno-list, or --gcno-from-target",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        payload = build_summary_payload(
            args,
            cases,
            source_desc,
            gcno_paths,
            unresolved_gcno,
            target_tokens,
            default_compare_files,
            [],
            dry_run=True,
        )
        write_dry_run_report(payload, args)
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    results = run_matrix(args, cases, gcno_paths, default_compare_files, target)
    payload = build_summary_payload(
        args,
        cases,
        source_desc,
        gcno_paths,
        unresolved_gcno,
        target_tokens,
        default_compare_files,
        results,
        dry_run=False,
    )
    summary_json = args.out_dir / "summary.json"
    summary_md = args.out_dir / "summary.md"
    summary_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown_report(payload, summary_md)
    print(f"summary_json={summary_json}")
    print(f"summary_md={summary_md}")

    if args.fail_on_case_fail and any(result.status != "PASS" for result in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
