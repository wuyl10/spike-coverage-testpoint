---
name: spike-coverage-testpoint
description: Analyze official/community Spike coverage evidence from gcov/gcovr/.gcov/.gcda/.gcno/coverage HTML to find missing architecture-visible cross execution scenarios, then convert those gaps into evidence-backed hyptest test-point plans. Must use whenever the user asks to inspect Spike coverage gaps, scenario/cross/path coverage, low line/branch/call counters as evidence, path-sensitive MemBlock coverage, single-case incremental coverage, path-marker instrumentation, or what riscv-hyp-tests/hyptest tests should be added from Spike coverage. Always use a target file under targets/*.json, or create one from targets/TEMPLATE.json, so concrete scope/spec/exclusions/scenario axes/path evidence policy stay outside the skill body. The bundled scripts only extract and rank counter/source/path evidence; the agent must judge which cross execution scenario is missing, whether it is worth testing, and how to design the test point. If the user wants to add or modify ai_test_cases/manual_test_cases/test_point/test_register.c, also use hyptest-workflow for implementation.
---

# Spike Coverage Testpoint

这个技能把 Spike 覆盖率证据从“数字”翻译成“哪些架构可见 cross 执行场景还没有覆盖，以及该补哪些高质量测试点”。它也支持 path-aware 分析：区分单个 branch/call 有没有覆盖、一个单 case 是否让必经计数增加、以及一条完整执行流是否需要 path marker 才能确认。默认输出测试点规划，不直接写 hyptest case；当用户明确要求落 case、改 `test_point/**/*.md` 或改 `test_register.c` 时，继续使用 `$hyptest-workflow`。

核心边界，任何任务都按这个执行：

```text
脚本负责：快速找哪些 counter/source/path 证据缺失，包括函数/行/分支/call、单 case 前后 .gcov 计数增量、可选 path-marker 日志。
agent负责：把证据映射成未覆盖的 cross 执行场景/路径签名，判断值不值得补，怎么设计测试点，以及当前证据能否证明同一条动态路径真的跑过。
```

## Scenario/Cross Coverage First

本技能的核心目的不是追求行覆盖、代码覆盖、分支覆盖或调用覆盖数字，而是找出 **哪些架构可见 cross 执行场景没有覆盖到**。gcov 的 line/branch/call 只是一层证据，用来定位可能缺失的场景；最终测试点必须回到场景、条件组合和可观测行为。

这里的 cross 执行场景通常包含这些轴的一个有意义组合：

- instruction/access class：fetch、scalar load/store、FP memory、vector load/store、LR/SC、AMO/AMOCAS、CBO/CMO、fence/sfence 等。
- privilege/profile/gate：M/S/U、ISA/profile 是否启用、默认 gate 还是 manual/special-run。
- address/translation/protection/device condition：bare/stage1、TLB hit/miss/walk、边界/对齐、PMP/PMA/PBMT、MMIO/device/responder。
- exception/fault/trigger/cache/vector/atomic subcondition：page/access/misaligned fault、trigger timing、cache/NMI、mask/vstart/fault-only-first/indexed/whole、reservation/CAS 成败等。
- architectural observable：寄存器、内存、trap cause/tval、CSR、vector element、device side effect 或确定的 pass/fail 行为。

每个最终候选都必须回答：

```text
Scenario coverage gap: 缺的是哪个 cross 执行场景，而不是“哪一行没覆盖”
Cross scenario signature: 这个场景的关键轴和值，哪些来自源码/gcov/path-marker 证据，哪些仍不确定
Coverage evidence role: line/branch/call/entry/case counter 只是 supporting evidence
Same-flow confidence: 证据是否证明这些条件发生在同一条动态指令/访问路径里
```

不要从 target 里的轴盲目枚举笛卡尔积。只从 target scope、Spike 源码、`.gcov`、单 case 增量或 path-marker 记录反推有证据支撑的 cross 场景；证据不足时标 `edge-covered-path-unknown`、`needs-path-instrumentation` 或 `needs source confirmation`。

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
- `scenario_coverage`: 可选。目标级 cross 场景覆盖说明，包括场景轴、证据策略和优先场景提示。它是 checklist，不是完整组合矩阵。
- `path_analysis`: 可选。路径敏感分析用的证据策略、报告字段 checklist、置信度、单 case 增量规则、path marker 词表。它不是完整路径矩阵，不允许 agent 从这里脑补组合。
- `special_run_scope` / `manual_only_dimensions` / `dimension_metadata`: target 级 gate 约束。脚本会把它们带到 candidate/handoff；agent 不得把 manual-only 维度推荐成 default gate。
- `analysis_notes` / `duplicate_search_terms`: agent 做场景解释和查重时使用的目标专用信息。

如果用户说“我要分析 X，不包含 Y”，先检查是否已有合适 target；没有就复制模板新建 target。后续脚本、报告、交接包都引用这个 target。

## When Triggered

Use this skill for:

- 分析 official/community Spike 覆盖率、`gcov`、`gcovr`、`.gcov/.gcda/.gcno`、coverage HTML。
- 根据低覆盖/0 覆盖证据找未覆盖的 cross 执行场景和应该补的 hyptest 测试点。
- 用户指定某个目标，比如 MemBlock、访存、vector load/store、atomic、trigger、exception、MMIO、TLB/page table、某个扩展或某组 Spike 文件。
- 用户要求“只看某类覆盖率”“排除某扩展/某模式”“根据覆盖率补测试点”。
- 用户要求判断“某个 cross 执行场景/执行流有没有跑过”“所有分支分别覆盖但同一条指令流可能没覆盖”“单 case 增量覆盖确认”“路径标记插桩”。

Do not use this skill for pure hyptest failure triage; use `$hyptest-failure-triage` for FAILED/timeout/stuck/mismatch logs. Do not use this skill alone to implement cases; pair it with `$hyptest-workflow`.

## Output Contract

Every coverage task must leave a Markdown artifact on disk, not only terminal text. For script-driven work, use `--markdown-out <path>` when available; for per-case matrix work, `run_case_coverage_matrix.py` always writes `summary.md` and per-case `compare.md` under `--out-dir`. If the user asks for a final analysis, also save an agent-authored `.md` report in the same output directory or an explicit user path.

Every Markdown report must include these sections near the top:

```text
结论：当前覆盖率证据指向哪些 cross 执行场景缺口
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

The deliverable is a ranked set of **scenario-coverage-backed test-point cards**. Each card should answer:

```text
Scenario coverage gap: which architecture-visible cross execution scenario is missing
Cross scenario signature: instruction/access + profile/gate + address/translation/protection/device + exception/trigger/cache/vector/atomic subcondition + observable, with unknowns marked
Coverage evidence role: supporting evidence only; which file/dimension/counter suggests the gap
Coverage evidence: which file/dimension is low, with entry/line/branch/call evidence
Path evidence: confirmed-not-executed | counter-increment-observed | single-case-increment-confirmed | edge-covered-path-unknown | needs-path-instrumentation | out-of-scope
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
- For path-sensitive or cross-scenario work, build a **scenario/path signature from source/gcov evidence** before proposing a case. Use `scenario_coverage.scenario_axes` and `path_analysis.path_signature_fields` only as reporting checklists; do not treat them as a complete architecture matrix.
- Apply `scenario_coverage.evidence_policy`, `path_analysis.evidence_policy`, and `path_analysis.path_markers` from the selected target when present. Do not invent path combinations from target JSON; derive them from Spike source, `.gcov`, single-case deltas, or path-marker records.
- Prefer tiny single-purpose cases for increment confirmation. If one case contains loops or many similar memory instructions, mark confidence lower because counter deltas may come from different dynamic instructions.
- Path-marker instrumentation is for coverage Spike only. Keep it gated by a build flag, runtime option, or environment variable, and do not require it for normal Spike or default hyptest gates.
- Treat `marker-sequence-observed` from JSONL path markers as marker evidence, not as final architecture proof by itself. Strong marker records need pc+insn, seq, or access_id correlation fields. Validate marker placement, per-instruction/access correlation, and expected observable before upgrading path confidence. Treat `json-marker-sequence-observed-weak` and `text-marker-sequence-observed-weak` as weak evidence only.

## Script And Agent Boundary

Keep this boundary strict:

| Role | Responsibility |
|---|---|
| Target file | Defines spec assumptions, scope, exclusions, dimensions, scenario axes, and target-specific guidance. |
| Scripts | Quickly find supporting evidence: files, dimensions, functions, source lines, branches, calls, 0% entries, low branch/call coverage; compare single-case gcov snapshots; parse optional path-marker logs. |
| Agent | Decide which cross execution scenario the evidence implies, whether it is a full path or only an edge, whether it is worth testing/in scope, whether it needs special run flags or instrumentation, and how to design a self-checkable test point. |
| hyptest-workflow | Only when implementation is requested: duplicate check, profile/gate decision, write test_point/case, register, compile, run. |

Do not let script output become the final answer by itself. Script output is evidence. The final test-point recommendation must come from target reading, source/gcov review, and architecture reasoning.

## Ground Rules

- Treat coverage as evidence, not as the test intent. A 0% file suggests a missing entry, but a high-quality test point must still name a cross execution scenario and an architectural observable: register/memory result, trap cause/tval, privilege/CSR state, vector result, or deterministic pass/fail behavior.
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
   - List a scenario/path signature from evidence, using `scenario_coverage.scenario_axes` and `path_signature_fields` only as checklists:
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
   - Lead with the scenario gap: target, missing cross scenario signature, and exact supporting file/coverage/line/branch/call evidence.
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

Use scripts by purpose; detailed examples and reproduction commands live in `README.md`.

| Need | Tool | Required output habit |
|---|---|---|
| Validate or create target | `scripts/validate_target.py <target.json>` | Run after every target edit; fix errors before analysis. |
| First-pass summary from gcov text | `scripts/analyze_spike_gcov.py --summary ... --target ...` | Save `summary.json` and `summary.md`; treat ranking as evidence only. |
| Source/gcov miss inspection | `scripts/inspect_gcov_lines.py --gcov-dir ... --target ... --file ...` | Save `line.json` and `line.md`; translate misses to scenarios in agent analysis. |
| Handoff skeleton | `scripts/build_handoff_packet.py --summary-json ... --inspect-json ...` | Fill `scenario_coverage_gap`, `cross_scenario_signature`, `target_semantic`, `expected_observable`, `profile_gate`, and `gate_note`; skeleton fields are not final. |
| Single-case counter delta | `scripts/compare_gcov_snapshots.py --before-dir ... --after-dir ...` | Use numeric branch/call counts and must-pass requirements; downgrade if evidence is incomplete. |
| Sequential per-case matrix | `scripts/run_case_coverage_matrix.py` | Run sequentially because `.gcda` counters are shared; treat counter movement as evidence, not proof of a scenario. |
| Path marker logs | `scripts/analyze_path_markers.py --log ... --require ...` | Strong records need pc+insn, seq, or access_id; marker sequence is evidence, not final proof. |
| Hygiene check | `scripts/check_handoff_final.py --strict-handoff/--strict-final-report ...` | Use before final handoff/report to catch raw skeleton fields and unsupported default gates. |

When a task asks how to run or interpret single-case increments, read `references/single_case_increment.md`. When designing or reviewing marker instrumentation, read `references/path_marker_instrumentation.md`. Keep target-specific marker names and scenario axes in the target file.

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

## 高优先级 cross 场景缺口
| Rank | Scenario coverage gap | Cross scenario signature | Supporting coverage evidence | Path confidence | Test idea | Observable/assertion | Hyptest location | Gate note |
|---:|---|---|---|---|---|---|---|

## 行级证据
| Candidate | Source/gcov evidence | Interpreted missing scenario/path |
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
    scenario_coverage_gap:
    cross_scenario_signature:
      instruction_or_access_class:
      privilege_profile_or_gate:
      address_translation_protection_device_condition:
      exception_trigger_cache_vector_atomic_condition:
      architectural_observable:
      evidence_status:
      remaining_uncertainty:
    coverage_evidence_role:
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

A high-quality scenario-coverage-driven test point should normally include:

- A precise cross execution scenario, not just an instruction mnemonic or a source line.
- An observable oracle: memory bytes, register value, trap cause/tval, CSR bit, vector element result, or deterministic side effect.
- At least one meaningful corner path when useful: fault, mask skip, partial progress, permission denied, reservation failure, trigger timing, boundary split, stale translation/cache state, or unsupported access.
- A clear reason the supporting Spike entry/line/branch/call/path-marker evidence implies a missing scenario.
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
