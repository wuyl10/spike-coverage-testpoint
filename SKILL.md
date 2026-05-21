---
name: spike-coverage-testpoint
description: Analyze official/community Spike coverage from gcov/gcovr/.gcov/.gcda/.gcno/coverage HTML and convert low or zero coverage into evidence-backed, high-quality hyptest test-point plans. Must use whenever the user asks to inspect Spike coverage, coverage gaps, low line/branch/call coverage, path-sensitive MemBlock coverage, single-case incremental coverage, path-marker instrumentation, or what riscv-hyp-tests/hyptest tests should be added from Spike coverage. Always use a target file under targets/*.json, or create one from targets/TEMPLATE.json, so concrete scope/spec/exclusions/path evidence policy stay outside the skill body. The bundled scripts only extract and rank coverage evidence; the agent must judge what architecture scenario/path the uncovered code represents, whether it is worth testing, and how to design the test point. If the user wants to add or modify ai_test_cases/manual_test_cases/test_point/test_register.c, also use hyptest-workflow for implementation.
---

# Spike Coverage Testpoint

这个技能把 Spike 覆盖率从“数字”翻译成“该补哪些高质量测试点”。它也支持 path-aware 分析：区分单个 branch/call 有没有覆盖、一个单 case 是否让必经计数增加、以及一条完整执行流是否需要 path marker 才能确认。默认输出测试点规划，不直接写 hyptest case；当用户明确要求落 case、改 `test_point/**/*.md` 或改 `test_register.c` 时，继续使用 `$hyptest-workflow`。

核心边界，任何任务都按这个执行：

```text
脚本负责：快速找哪里没覆盖、哪些函数/行/分支/call 没跑到；对单 case 前后 .gcov 快照做计数增量对比；解析可选 path-marker 日志。
agent负责：判断这些没覆盖代码对应什么架构场景/执行流，值不值得补，怎么设计测试点，以及当前证据能否证明同一条路径真的跑过。
```

## Target Files First

每次分析必须先选一个 target 文件，或从 `targets/TEMPLATE.json` 新建一个。target 文件是统一管理“我要测什么、规格是什么、排除什么、覆盖维度怎么分”的地方。

不要把具体规格写死在 `SKILL.md` 或脚本里。当前已有目标文件放在 `targets/`，新目标从 `targets/TEMPLATE.json` 复制后填写。

target 文件负责：

- `spec`: 本次目标的规格/feature/profile 假设；用户说“我要测什么，规格是什么”时填这里。
- `scope_in`: 本次要分析的架构范围、组件范围、指令类别、行为类别。
- `scope_out`: 本次明确不分析的范围。
- `summary_include_regex` / `summary_exclude_prefixes` / `summary_exclude_regex`: summary 级别证据过滤。
- `line_exclude_regex`: `.gcov` 行级证据过滤。
- `coverage_thresholds`: 可选。summary 低覆盖阈值，默认 line<20%、branch<10%、call<10%；不同目标需要不同阈值时只改 target。
- `dimensions`: 脚本分组用的覆盖维度。
- `path_analysis`: 可选。路径敏感分析用的证据策略、报告字段 checklist、置信度、单 case 增量规则、path marker 词表。它不是完整路径矩阵，不允许 agent 从这里脑补组合。
- `special_run_scope` / `manual_only_dimensions` / `dimension_metadata`: target 级 gate 约束。脚本会把它们带到 candidate/handoff；agent 不得把 manual-only 维度推荐成 default gate。
- `analysis_notes` / `duplicate_search_terms`: agent 做场景解释和查重时使用的目标专用信息。

如果用户说“我要分析 X，不包含 Y”，先检查是否已有合适 target；没有就复制模板新建 target。后续脚本、报告、交接包都引用这个 target。

## When Triggered

Use this skill for:

- 分析 official/community Spike 覆盖率、`gcov`、`gcovr`、`.gcov/.gcda/.gcno`、coverage HTML。
- 根据低覆盖/0 覆盖找应该补的 hyptest 测试点。
- 用户指定某个目标，比如 MemBlock、访存、vector load/store、atomic、trigger、exception、MMIO、TLB/page table、某个扩展或某组 Spike 文件。
- 用户要求“只看某类覆盖率”“排除某扩展/某模式”“根据覆盖率补测试点”。
- 用户要求判断“某个执行场景/执行流有没有跑过”“所有分支分别覆盖但同一条指令流可能没覆盖”“单 case 增量覆盖确认”“路径标记插桩”。

Do not use this skill for pure hyptest failure triage; use `$hyptest-failure-triage` for FAILED/timeout/stuck/mismatch logs. Do not use this skill alone to implement cases; pair it with `$hyptest-workflow`.

## Output Contract

Every coverage task must leave a Markdown artifact on disk, not only terminal text. For script-driven work, use `--markdown-out <path>` when available; for per-case matrix work, `run_case_coverage_matrix.py` always writes `summary.md` and per-case `compare.md` under `--out-dir`. If the user asks for a final analysis, also save an agent-authored `.md` report in the same output directory or an explicit user path.

Every Markdown report must include these sections near the top:

```text
结论：当前覆盖率情况说明了什么
数据：target、输入路径、case 数、覆盖计数、runner 状态等
证据：具体文件/函数/源码行/branch/call/case log/compare 文件
限制与下一步：当前证据不能证明什么，下一步要 inspect、单 case 增量还是 path marker
```

When a bundled script supports both `--markdown` and `--markdown-out`, prefer
`--markdown-out` for durable reports. Use `--markdown` only when the user also
wants terminal output. In the final response, mention the exact `.md` path that
contains the conclusion, evidence, and data.

Write human-readable Markdown report headings and explanatory prose in Chinese.
Machine-readable JSON keys and stable evidence field names may remain English.

## Output Path Policy

If the user gives an explicit output path, use it exactly. If the user only asks
for analysis, reports, or "run and analyze" without a path, choose a stable path
automatically instead of asking.

Use this default structure:

```text
Official Spike coverage repo:
  /nfs/home/wuyuanlong/workspace/offical-spike-coverage

Human-readable Markdown reports:
  <coverage_repo>/cov_doc/reports/<target_name>/<run_tag>/

Machine/raw run evidence:
  <coverage_repo>/cov_runs/<target_name>/<run_tag>/

Temporary trial runs only:
  /tmp/spike_cov_<target_name>_<purpose>/
```

Default report filenames:

```text
summary.md          First-pass coverage ranking and conclusion
line.md             Line/branch/call inspection evidence
compare.md          Single-case before/after gcov delta evidence
path_markers.md     Path-marker sequence evidence
handoff.md          hyptest-workflow handoff skeleton/evidence packet
testpoint_plan.md   Agent-authored final test-point analysis
```

For one-click per-case matrix runs, put the full run directory under
`cov_runs/<target_name>/<run_tag>/`. Its `summary.md`, per-case `compare.md`,
JSON, logs, and before/after snapshots stay together there. If the user also
wants a polished final analysis, save `testpoint_plan.md` under
`cov_doc/reports/<target_name>/<run_tag>/` and link back to the matrix run dir in
the `数据` / `证据` section.

Choose `<target_name>` from the target JSON `name` field, such as
`memblock_non_h`. Choose `<run_tag>` from the current date plus purpose, for
example `20260521_current`, `20260521_all_cases`,
`20260521_after_new_mem_cases`, or `20260521_path_marker_trial`. Avoid writing
analysis outputs inside the skill directory; the skill directory is tool source,
not a result store.

The deliverable is a ranked set of **coverage-backed test-point cards**. Each card should answer:

```text
Coverage evidence: which file/dimension is low, with line/branch/call evidence
Path evidence: confirmed-not-executed | counter-increment-observed | single-case-increment-confirmed | edge-covered-path-unknown | needs-path-instrumentation | out-of-scope
Missing scenario: the architectural behavior missing from tests
Why high value: why it should improve Spike coverage and RTL confidence
Test idea: concrete setup/action
Observable: register/memory/trap/CSR/vector result to assert
Existing coverage check: what to search in hyptest before writing
Suggested location: likely ai_test_cases/manual_test_cases/test_point area
Gate note: default, manual/special-run, blocked, or needs profile decision
Handoff: exact fields to pass to hyptest-workflow if implementation is requested
```

Never stop at "file X is 0%". Always translate coverage into a self-checkable scenario, or explicitly mark it as not currently worth writing.

## Path-Aware Coverage Rules

Use these rules whenever the user cares about execution paths, combinations, or whether a full scenario ran:

- gcov line/branch/call coverage is edge/counter evidence, not full path coverage. If branch A and branch B are each covered in aggregate, do not claim the path A -> B was covered unless a single-case increment or path marker proves correlation.
- Classify path confidence explicitly:
  - `confirmed-not-executed`: a must-pass entry/line/branch/call for the proposed path is zero or never executed.
  - `counter-increment-observed`: required counters increased, but the run is not isolated enough, Spike log/profile evidence is missing, some required point is not checked, or missing/decreased events make final path confirmation unsafe.
  - `single-case-increment-confirmed`: one tiny single-purpose run executed the target guest instruction, Spike log or equivalent target PC/instruction evidence confirms that instruction, every must-pass line/branch/call counter increased in the before/after `.gcov` comparison, and no required point is `decreased-or-reset` or missing.
  - `edge-covered-path-unknown`: relevant edges have aggregate coverage, but no evidence proves they occurred in the same instruction/access flow.
  - `needs-path-instrumentation`: internal path correlation cannot be proven from gcov plus Spike logs; propose target-defined path markers.
  - `out-of-scope`: the path belongs to `scope_out`.
- Do not overuse `single-case-increment-confirmed`. It requires all of these:
  - isolated one-case evidence, not a suite run or a loop-heavy case;
  - target guest PC/instruction evidence from Spike log, commit log, or an equivalent run artifact;
  - all must-pass counters increase;
  - branch/call snapshots use numeric count format, not percentage-only format;
  - no required `decreased-or-reset`, `missing-after-event`, `not-comparable-counter-format`, unresolved `missing-before-event`, `missing-before-file`, or `missing-after-file`.
  If any item is missing, downgrade to `counter-increment-observed` or `edge-covered-path-unknown`.
- For path-sensitive work, build a **path signature from source/gcov evidence** before proposing a case. Use `path_analysis.path_signature_fields` only as a reporting checklist; do not treat it as a complete architecture matrix.
- Apply `path_analysis.evidence_policy` and `path_analysis.path_markers` from the selected target when present. Do not invent path combinations from target JSON; derive them from Spike source, `.gcov`, single-case deltas, or path-marker records.
- Prefer tiny single-purpose cases for increment confirmation. If one case contains loops or many similar memory instructions, mark confidence lower because counter deltas may come from different dynamic instructions.
- Path-marker instrumentation is for coverage Spike only. Keep it gated by a build flag, runtime option, or environment variable, and do not require it for normal Spike or default hyptest gates.
- Treat `marker-sequence-observed` from JSONL path markers as marker evidence, not as final architecture proof by itself. Strong marker records need pc+insn, seq, or access_id correlation fields. Validate marker placement, per-instruction/access correlation, and expected observable before upgrading path confidence. Treat `json-marker-sequence-observed-weak` and `text-marker-sequence-observed-weak` as weak evidence only.

## Script And Agent Boundary

Keep this boundary strict:

| Role | Responsibility |
|---|---|
| Target file | Defines spec assumptions, scope, exclusions, dimensions, and target-specific guidance. |
| Scripts | Quickly find where coverage is missing: files, dimensions, functions, source lines, branches, calls, 0% entries, low branch/call coverage; compare single-case gcov snapshots; parse optional path-marker logs. |
| Agent | Decide what the uncovered code means architecturally, whether it is a full path or only an edge, whether it is worth testing/in scope, whether it needs special run flags or instrumentation, and how to design a self-checkable test point. |
| hyptest-workflow | Only when implementation is requested: duplicate check, profile/gate decision, write test_point/case, register, compile, run. |

Do not let script output become the final answer by itself. Script output is evidence. The final test-point recommendation must come from target reading, source/gcov review, and architecture reasoning.

## Ground Rules

- Treat coverage as evidence, not as the test intent. A 0% file suggests a missing entry, but a high-quality test point must still have an architectural observable: register/memory result, trap cause/tval, privilege/CSR state, vector result, or deterministic pass/fail behavior.
- Respect the selected target exactly. If an uncovered path matches `scope_out`, mark it out of scope instead of proposing a test. If the target does not say whether a path is in scope, mark it `needs target decision`.
- Do not edit `~/.bashrc`. If rerunning hyptest with a coverage Spike, use temporary environment variables in the command/process only.
- When a proposed point requires special Spike runtime options, label it `manual/special-run` instead of pretending it is a normal default gate.
- If the target has `special_run_scope`, `manual_only_dimensions`, or `dimension_metadata`, apply those before suggesting a default gate.
- Treat `dimension_gate.manual_only` or `default_gate_allowed: false` from script output as a hard downgrade to `manual/special-run` unless the user explicitly changes the target/profile decision.
- Separate **entry coverage** from **semantic coverage**:
  - `insns/*.h` line coverage only proves the instruction entry executed.
  - Shared-path branch/call coverage proves whether the interesting MMU/vector/atomic/trigger/fault logic executed.
  - `analyze_spike_gcov.py` labels candidates as `entry`, `shared-path`, or `mixed` and prints a class reason. Use that label as triage only; final semantic value still requires source/gcov review.
- Separate **edge coverage** from **path coverage**:
  - Aggregate branch coverage does not prove a branch sequence happened in the same dynamic instruction/access.
  - Single-case counter deltas plus Spike logs can strongly confirm a tiny case's required path points.
  - Path markers are required when internal correlation matters and gcov cannot prove it.
- Prefer test points that cover a reusable semantic class rather than one smoke instruction.
- Do not propose a default-gate point unless the expected behavior is stable in official Spike and the current hyptest platform can observe it.
- Before recommending a default-gate case for a 0% entry, make a profile/gate decision: required extension/profile, evidence that the current target includes it, whether default hyptest can run it, and why it is not blocked/manual-only.
- Final user-facing answers must not contain raw `TODO(agent)` placeholders. If a field cannot be resolved, write `needs source confirmation: <specific reason>` or `needs profile decision: <specific reason>`.

## Inputs To Locate

Prefer explicit paths from the user. Otherwise look for these common paths on this machine:

```text
Spike coverage repo     /nfs/home/wuyuanlong/workspace/offical-spike-coverage
Spike build dir         <spike_cov_repo>/build-cov
Coverage docs           <spike_cov_repo>/cov_doc
Raw gcov summaries      <spike_cov_repo>/cov_doc/gcov_raw/*.txt
Hyptest repo            /nfs/home/wuyuanlong/workspace/riscv-hyp-tests-nhv5.1
Coverage Spike binary   <spike_cov_repo>/build-cov/spike
Skill targets           /nfs/home/wuyuanlong/.agents/skills/spike-coverage-testpoint/targets/*.json
```

If the user provides different paths, use those.

## Workflow

1. **Select or create target**
   - If the user gives a target file, use it.
   - If the user names an existing target, use `targets/<name>.json`.
   - If no target exists, create one from `targets/TEMPLATE.json` and fill `spec`, `scope_in`, `scope_out`, and `dimensions` from the user’s purpose.
   - Read `analysis_notes` and `duplicate_search_terms` from the target; do not look for target-specific spec in `SKILL.md`.
   - If the user has not provided enough detail to fill a safe target, ask for the missing target decision before analyzing.
   - After creating or editing a target, run `scripts/validate_target.py <target.json>` and fix errors before analysis.

2. **Collect coverage artifacts**
   - Prefer existing summaries under `cov_doc/gcov_raw/*.txt`.
   - Prefer existing `.gcov` files under `cov_doc/gcov_raw/` or other coverage output dirs for line-level inspection.
   - If no useful summary exists but `build-cov/*.gcno` and `*.gcda` exist, run `gcov -b -c -o <build-dir> <files...>` and save output under a coverage doc/raw directory.
   - If `gcovr` is broken or unavailable, use system `gcov`. State that choice.
   - When rerunning hyptest with a coverage Spike, set `HYPTEST_SPIKE_BIN` only for that process. If a wrapper invokes `bash -lc` and shell startup files override it, use a temporary process environment rather than editing `.bashrc`.

3. **Parse coverage robustly**
   - Track each `File '...'` block independently.
   - Stop associating totals with a file once `Creating 'x.gcov'` or `Removing 'x.gcov'` appears; gcov may print a final total line that otherwise contaminates the last file.
   - Record line, branch, call coverage separately.
   - Filter using the target file only. Do not add hidden exclusions in the script.

4. **Rank coverage evidence**
   - First pass: use `scripts/analyze_spike_gcov.py --target <target.json> --top <N> --markdown-out <out>/summary.md --json-out <out>/summary.json`.
   - Treat the score as a triage hint only. It is based on 0% entries and low line/branch/call coverage; it is not a semantic test quality score.
   - Read `evidence_class`, `evidence_class_reason`, `classification_confidence`, `entry_selection_reason`, and `dimension_gate`. Prefer `shared-path` when the user's goal is semantic/path coverage. Treat `mixed` as "entry evidence that needs shared source review"; treat `entry` as profile-gated entry evidence until source review shows value.
   - Do not turn this ranking directly into test points without source/gcov inspection and agent reasoning.
   - If a high-ranked gap is only an instruction entry, inspect shared paths or mark it as `entry-only evidence`.

5. **Inspect exact uncovered code before proposing detailed tests**
   - For top gaps, run `inspect_gcov_lines.py` on the relevant `.gcov` files with the same `--target`, using both `--json-out <out>/lines.json` and `--markdown-out <out>/lines.md`.
   - Report `excluded by filters` counts when filters hide evidence; if many functions/events are excluded, mention that filtered evidence could affect ranking or candidate completeness.
   - Then open `.gcov` and source around the most important misses when needed.
   - Look for `#####`, never-executed branches, and never-executed calls.
   - Group misses by function before explaining them; the function often tells the scenario better than an isolated line.
   - Translate code branches into test intent. Do not say “cover line N” when the real point is an architectural condition.
   - If source inspection is not possible, mark the candidate as `needs source confirmation`.

6. **For path-sensitive questions, build and verify a path signature**
   - Read `path_analysis` from the target when present.
   - List a path signature from evidence, using `path_signature_fields` only as a checklist:
     - target instruction/entry
     - shared source function path
     - required line/branch/call events
     - source-proven condition under test
     - expected architectural observable
     - remaining uncertainty
   - If any must-pass event is zero in the suite `.gcov`, mark `confirmed-not-executed`.
   - If all events have aggregate coverage but no same-flow proof, mark `edge-covered-path-unknown`.
   - To confirm a specific tiny case, take before/after `.gcov` snapshots with numeric branch/call counts, then run `compare_gcov_snapshots.py` with `--requirements-json` or repeated `--require-event file:kind:line[:ordinal]` for the must-pass line/branch/call points. Use Spike `-l --log-commits --log=<file>` when useful. Use default `--key-mode stable-line` unless you intentionally want function-aware matching. If `all_required_passed` is false, or the compare output has `decreased-or-reset`, `not-comparable-counter-format`, missing files, possible key drift, or missing required events, do not use it for positive path confirmation.
   - If the user wants to run many cases one by one, use `run_case_coverage_matrix.py`. Keep it sequential unless the task is explicitly logs-only; gcov `.gcda` counters are shared and parallel execution corrupts per-case deltas. Use `--limit` for “选中多少 case 跑”, `--case/--case-list/--elf` for selected cases, and `--all-elves` for a full ELF directory pass.
   - If the path depends on internal correlation that gcov cannot tie together, propose target-defined path markers and mark `needs-path-instrumentation`. If markers are emitted as one marker per JSON record, use `analyze_path_markers.py --group-by access_id` or `--group-by seq` to prove an ordered sequence for one dynamic access/instruction.

7. **Check existing hyptest coverage**
   - Search existing `test_point/**/*.md`, `ai_test_cases/**/*.c`, `manual_test_cases/**/*.c`, and `test_register.c`.
   - Search by semantic terms, not only instruction names.
   - For planning-only tasks, do a lightweight duplicate-search plan or spot check when useful.
   - If the task will implement cases, stop treating this skill as the owner and hand the selected cards to `$hyptest-workflow` for repo-level duplicate checks, quality gates, case writing, compile/run, and registration.

8. **Output an actionable plan**
   - Give evidence first: target, file/coverage/line/branch/call and exact gap.
   - Save the final agent-authored analysis as Markdown when the task asks for an analysis result beyond raw script evidence. Use a clear path such as `<out_dir>/testpoint_plan.md`, `<out_dir>/final_report.md`, or the user-provided path.
   - Include path confidence and explain whether the evidence is an entry, edge, single-case increment, or marker-sequence proof.
   - Include `line_evidence_status` and do not finalize candidates marked `weak-inspection-hint-only`, `no-line-evidence-from-requested-files`, or `unreviewed-missing-files` without more source/gcov review.
   - Include `same_flow_evidence`. If it says `aggregate-only`, do not claim a same instruction/access flow was covered; require single-case increment or correlated path markers.
   - Treat `same_flow_evidence.status: suite-summary-gap` as a prompt to inspect source and fill must-pass evidence; do not call it path proof by itself.
   - Include profile/gate fields before recommending default-gate cases: `extension_required`, `current_profile_evidence`, `default_gate_eligible`, and `profile_gate_note`.
   - Then give proposed test point: setup, action, expected observation, and likely hyptest location.
   - Mark `default`, `manual/special-run`, `blocked`, `out-of-scope`, or `needs profile decision` when obvious.
   - Use `build_handoff_packet.py` when summary/line JSON is available, then replace any unresolved skeleton fields with agent reasoning or `needs source confirmation: <reason>`.
   - Include a compact `hyptest-workflow handoff packet` when the user asks what to implement next, asks for handoff, or plans to write cases. For method/risk/explanation-only questions, a full handoff packet is optional.

## Bundled Tools

Use `analyze_spike_gcov.py` for the first pass when a gcov summary is available:

```bash
REPORT_DIR=/nfs/home/wuyuanlong/workspace/offical-spike-coverage/cov_doc/reports/<target_name>/<run_tag>
RUN_DIR=/nfs/home/wuyuanlong/workspace/offical-spike-coverage/cov_runs/<target_name>/<run_tag>
mkdir -p "$REPORT_DIR" "$RUN_DIR"

python3 /nfs/home/wuyuanlong/.agents/skills/spike-coverage-testpoint/scripts/analyze_spike_gcov.py \
  --summary /path/to/gcov_summary.txt \
  --target /path/to/target.json \
  --top 12 \
  --json-out "$RUN_DIR/summary.json" \
  --markdown-out "$REPORT_DIR/summary.md"
```

Useful options:

```text
--focus vector        Only rank dimensions/entries containing "vector"
--focus amocas        Only rank dimensions/entries containing "amocas"
--top 20             Show more evidence rows
--json-out path       Save machine-readable summary for later comparison
--markdown-out path   Save Markdown report with conclusion/data/evidence
```

The script is an aid, not a substitute for source review. Use it to identify dimensions and 0% entries, then inspect source/gcov around the highest-value gaps.

Use `validate_target.py` after editing a target:

```bash
python3 /nfs/home/wuyuanlong/.agents/skills/spike-coverage-testpoint/scripts/validate_target.py \
  /path/to/target.json
```

Use `inspect_gcov_lines.py` for line-level source/branch/call evidence:

```bash
python3 /nfs/home/wuyuanlong/.agents/skills/spike-coverage-testpoint/scripts/inspect_gcov_lines.py \
  --gcov-dir /path/to/gcov_raw \
  --source-root /path/to/spike/source \
  --target /path/to/target.json \
  --file mmu.cc.gcov \
  --file v_ext_macros.h.gcov \
  --context 6 \
  --max-functions 10 \
  --json-out "$RUN_DIR/lines.json" \
  --markdown-out "$REPORT_DIR/lines.md"
```

Optional evidence-only filtering can be added with repeated `--exclude-regex`, but prefer target-file filters for stable scope:

```text
--exclude-regex '<regex>'
```

This script extracts:

- uncovered source lines (`#####`)
- never-executed branches
- never-executed calls
- enclosing gcov function block
- source context around the first miss in each function

Use its output as evidence. The agent then translates important misses into architecture-visible scenarios and marks low-value defensive, special-run, or out-of-scope paths.

Use `build_handoff_packet.py` after summary and line-level JSON are available:

```bash
python3 /nfs/home/wuyuanlong/.agents/skills/spike-coverage-testpoint/scripts/build_handoff_packet.py \
  --summary-json /path/to/summary.json \
  --inspect-json /path/to/inspect.json \
  --top 5 \
  --markdown-out "$REPORT_DIR/handoff.md"
```

This only builds a packet skeleton. The agent must fill `target_semantic`, `scope_status`, `expected_observable`, `profile_gate`, and final `gate_note` from source review and architecture reasoning.
If the packet lists `missing_inspection_files`, inspect those `.gcov` files before treating the candidate as fully reviewed, or mark the candidate `needs source confirmation`.

Use `compare_gcov_snapshots.py` for single-case incremental coverage confirmation:

```bash
python3 /nfs/home/wuyuanlong/.agents/skills/spike-coverage-testpoint/scripts/compare_gcov_snapshots.py \
  --before-dir /path/to/before_gcov \
  --after-dir /path/to/after_gcov \
  --target /path/to/target.json \
  --file mmu.cc.gcov \
  --file mmu.h.gcov \
  --file v_ext_macros.h.gcov \
  --markdown-out "$REPORT_DIR/compare.md"
```

Interpretation:

- `newly-covered` or `increased` on all must-pass points supports `counter-increment-observed` first.
- Upgrade to `single-case-increment-confirmed` only if the run is tiny/single-purpose, target PC/instruction evidence exists, and no required event/file is missing or decreased.
- `still-zero` on any must-pass point means `confirmed-not-executed`.
- `not-comparable-counter-format` means a branch/call event was only available as a percentage/unknown format. Regenerate snapshots with numeric counts such as `gcov -b -c` before using it for increment proof.
- `decreased-or-reset`, `missing-after-event`, `not-comparable-counter-format`, unresolved `missing-before-event`, `missing-before-file`, or `missing-after-file` are invalid for positive path confirmation until explained.
- `possible_key_drift` means before/after matching may be unstable; inspect the affected source line/function before deciding.
- Aggregate counters without a controlled single-case run mean `edge-covered-path-unknown`.

When the user asks how to run or interpret a single-case increment check, read
`references/single_case_increment.md`.

Use `run_case_coverage_matrix.py` when the user wants one-click all-case or selected-case sequential runs with a final report:

```bash
HYPTEST_SPIKE_BIN=/path/to/build-cov/spike \
python3 /nfs/home/wuyuanlong/.agents/skills/spike-coverage-testpoint/scripts/run_case_coverage_matrix.py \
  --hyptest-repo /path/to/riscv-hyp-tests-nhv5.1 \
  --target /path/to/targets/memblock_non_h.json \
  --build-dir /path/to/offical-spike-coverage/build-cov \
  --elf-dir /path/to/riscv-hyp-tests-nhv5.1/case_elf_asm/spike \
  --all-elves \
  --limit 20 \
  --gcno-from-target \
  --out-dir "$RUN_DIR/case_matrix"
```

Useful selectors:

```text
--case ai_name        Select one case; repeatable
--case-list file      Read case names or ELF paths
--elf file.ELF        Run an explicit ELF
--all-elves           Run mapped ELFs under --elf-dir
--case-regex REGEX    Filter selected case names before --limit
--limit N             Only run the first N selected cases
--dimension vector    Restrict --gcno-from-target to matching target dimensions
--dry-run             Show selected cases/gcno files without running Spike
```

`--command-template` supports `{spike_bin}`, `{elf}`, `{elf_name}`, `{elf_dir}`, `{case_name}`, `{run_name}`, and `{case_dir}`. The default template directly executes `{spike_bin}` instead of `bash -lc`, so shell startup files cannot override the temporary coverage Spike setting. For path-sensitive confirmation, prefer a template that saves Spike logs under `{case_dir}` so the agent can inspect guest PC/instruction evidence.

The matrix output is evidence only:

- `summary.md` / `summary.json`: final per-case matrix.
- `cases/<idx>_<case>/run.log`: Spike output.
- `before_gcov` / `after_gcov`: isolated snapshots for that case.
- `compare.md` / `compare.json`: counter movement and requirements result.

Interpret `cases_with_counter_changes` as “this case moved some selected counters”, not as proof of a high-quality path. Upgrade to a path-confidence claim only after source review, target scope review, and must-pass requirement checks. If `cases_with_invalid_evidence` is nonempty, inspect the per-case compare before using it.

Use `analyze_path_markers.py` when a coverage Spike has emitted path-marker JSONL/text logs:

```bash
python3 /nfs/home/wuyuanlong/.agents/skills/spike-coverage-testpoint/scripts/analyze_path_markers.py \
  --log /tmp/spike_mem_path_cov.jsonl \
  --require mem.access.scalar_load \
  --require mem.translate.tlb_miss_walk \
  --require mem.fault.page \
  --ordered \
  --markdown-out "$REPORT_DIR/path_markers.md"
```

Preferred marker log format:

```json
{"pc":"0x80001000","insn":"lw","markers":["mem.access.scalar_load","mem.translate.tlb_miss_walk","mem.fault.page"]}
```

Only JSON marker records that preserve per-instruction/access correlation can support same-flow path evidence. Strong records should include pc+insn, seq, or access_id. JSON records without correlation fields and plain text fallback are weaker and should be treated as edge evidence unless independently proven to be one dynamic instruction/access record. The script status `marker-sequence-observed` means the marker sequence appeared; the agent still must validate marker placement and observable behavior.

When the user asks to design or review path-marker instrumentation, read
`references/path_marker_instrumentation.md`. Keep target-specific marker names
in the target file; use the reference only for the generic instrumentation
shape, JSONL format, and interpretation rules.

## Report Format

Use this structure by default:

```markdown
## 覆盖率输入
- Spike repo:
- coverage summary:
- target file:
- target spec/profile:
- target scope:
- target exclusions:

## 高优先级测试点候选
| Rank | Coverage evidence | Path confidence | Missing scenario/path signature | Test idea | Observable/assertion | Hyptest location | Gate note |
|---:|---|---|---|---|---|---|---|

## 行级证据
| Candidate | Source/gcov evidence | Interpreted missing path |
|---|---|---|

## 次级缺口
...

## 不建议现在补
- ...

## hyptest-workflow handoff packet
Only use this packet for implementation when the user explicitly asks to write cases.

```yaml
target_file:
target_name:
selected_candidates:
  - candidate_name:
    coverage_dimension:
    coverage_evidence:
    line_evidence_status:
    source_or_gcov_evidence:
    do_not_finalize_without:
    dimension_gate:
    same_flow_evidence:
    evidence_class: entry | shared-path | mixed
    evidence_class_reason:
    classification_confidence:
    path_confidence: confirmed-not-executed | counter-increment-observed | single-case-increment-confirmed | edge-covered-path-unknown | needs-path-instrumentation | out-of-scope
    path_signature:
      target_instruction_or_entry:
      shared_source_function_path:
      must_pass_source_evidence:
      source_proven_condition_under_test:
      architectural_observable:
      remaining_uncertainty:
    required_evidence_points:
      - file:
        kind: line | branch | call | path-marker
        source_line:
        marker:
        status:
    target_semantic:
    scope_status: in-scope | out-of-scope | needs target decision
    expected_observable:
    profile_gate:
      extension_required:
      extension_required_inferred:
      inference_basis:
      needs_agent_profile_confirmation:
      current_profile_evidence:
      default_gate_eligible:
      profile_gate_note:
    duplicate_search_terms:
    suggested_test_point_area:
    suggested_case_area:
    gate_note: default | manual/special-run | blocked | needs profile decision
    profile_questions:
    implementation_owner: hyptest-workflow
```
```

Keep the final answer practical: identify what to write next, why it matters, and what evidence supports it.

## Quality Bar For Proposed Test Points

A high-quality coverage-driven test point should normally include:

- A precise architecture condition, not just an instruction mnemonic.
- An observable oracle: memory bytes, register value, trap cause/tval, CSR bit, vector element result, or deterministic side effect.
- At least one meaningful corner path when useful: fault, mask skip, partial progress, permission denied, reservation failure, trigger timing, boundary split, stale translation/cache state, or unsupported access.
- A clear reason it covers a Spike branch/call gap.
- A path confidence label. Do not call something covered as a full path if you only have aggregate branch coverage.
- Source/gcov evidence for at least the top candidates, unless the user only asks for a coarse first pass.
- A duplicate-check plan against existing hyptest tests.

Avoid proposing:

- Pure smoke tests that only execute an instruction once.
- Tests whose only oracle is “coverage improved”.
- Out-of-scope targets from the selected target file.
- Default-gate tests that require special simulator/device/logging knobs.

## Target-Specific Guidance

Use only the selected target file for target-specific scope, exclusions, dimensions, interpretation notes, and duplicate-search terms. The skill body stays generic so the same workflow can analyze MemBlock today and a different Spike area tomorrow.

## Handoff To hyptest-workflow

This skill may prepare the packet, but it does not write hyptest files by itself. Trigger `$hyptest-workflow` only when the user asks to implement, write, register, compile, run, update `test_point/**/*.md`, update `ai_test_cases`/`manual_test_cases`, or update `test_register.c`.

When handing off, include the packet plus the exact coverage artifacts used. `hyptest-workflow` must still perform its own duplicate checks, spec profile checks, case quality gates, registration, compile, and run.
