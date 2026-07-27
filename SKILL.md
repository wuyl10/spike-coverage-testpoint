---
name: spike-coverage-testpoint
description: Analyze official/community Spike coverage evidence from gcov/gcovr/.gcov/.gcda/.gcno/coverage HTML to find missing architecture-visible cross execution scenarios, then convert those gaps into evidence-backed hyptest test-point plans. Must use whenever the user asks to inspect Spike coverage gaps, scenario/cross/path coverage, low line/branch/call counters as evidence, path-sensitive MemBlock coverage, single-case incremental coverage, path-marker instrumentation, or what riscv-hyp-tests/hyptest tests should be added from Spike coverage. Always use a project spec under specs/*.json plus a target file under targets/*.json, or create them from specs/TEMPLATE.json and targets/TEMPLATE.json, so the current project implementation stays separate from the concrete coverage slice/scope/exclusions/scenario axes/path evidence policy. The bundled scripts only extract and rank counter/source/path evidence; the agent must judge which cross execution scenario is missing, whether it is worth testing, and how to design the test point. If the user wants to add or modify ai_test_cases/manual_test_cases/test_point/test_register.c, also use hyptest-workflow for implementation.
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

- instruction/access class：fetch、scalar load/store、FP memory、vector load/store、LR/SC、AMO、project spec 支持 Zacas 时的 AMOCAS、CBO/CMO、fence/sfence 等。
- privilege/profile/gate：M/S/U、ISA/profile 是否启用、默认 gate 还是 manual/special-run。
- address/translation/protection/device condition：bare/stage1、TLB hit/miss/walk、边界/对齐、PMP/PMA/PBMT、MMIO/device/responder。
- exception/fault/trigger/cache/vector/atomic subcondition：page/access/misaligned fault、trigger timing、cache/NMI、mask/vstart/fault-only-first/indexed/whole、reservation、project spec 支持时的 CAS 成败等。
- architectural observable：寄存器、内存、trap cause/tval、CSR、vector element、device side effect 或确定的 pass/fail 行为。

每个最终候选都必须回答：

```text
Scenario coverage gap: 缺的是哪个 cross 执行场景，而不是“哪一行没覆盖”
Cross scenario signature: 这个场景的关键轴和值，哪些来自源码/gcov/path-marker 证据，哪些仍不确定
Coverage evidence role: line/branch/call/entry/case counter 只是 supporting evidence
Same-flow confidence: 证据是否证明这些条件发生在同一条动态指令/访问路径里
```

不要从 target 里的轴盲目枚举笛卡尔积。只从 target scope、Spike 源码、`.gcov`、单 case 增量或 path-marker 记录反推有证据支撑的 cross 场景；证据不足时标 `edge-covered-path-unknown`、`needs-path-instrumentation` 或 `needs source confirmation`。

## Spec And Target Files First

每次分析必须先选一个 project spec 和一个 target。两层不要混：

- `specs/*.json`: 当前项目实现。描述 coverage Spike/hyptest ELF 的运行边界、环境变量接口、源码/覆盖率证据来源、项目里有哪些实现面可被 target 选择。
- `targets/*.json`: 当前项目实现下要看哪一块覆盖率。描述本次 coverage slice 的 `coverage_focus`、`scope_in/out`、过滤规则、维度、场景 checklist、path/gate 策略。

不要把项目实现写进 target，也不要把具体 target 范围写进 spec，更不要写死在 `SKILL.md` 或脚本里。已有项目规格放在 `specs/`，已有分析目标放在 `targets/`。

project spec 文件负责：

- `environment`: 稳定环境变量接口和默认派生路径，例如 `HYPTEST_SPIKE_COV`、`HYPTEST_HOME`、coverage Spike bin。
- `implementation_model`: 覆盖率 Spike 怎么跑、不能和什么 runner/编译流程混用、证据从哪里来。
- `available_implementation_features`: 当前项目实现里可供 target 选择的实现面。
- `unsupported_feature_rules`: 对 support matrix 中 `NO` 的实现面提供 tokens、summary/line 过滤正则和 runner scope warning 正则；脚本会自动把这些规则合并到 target 的有效过滤/告警里。
- `target_policy`: target 如何在该项目实现下选择具体覆盖率切片。

target 文件负责：

- `project_spec`: 指向一个 `specs/*.json`。
- `coverage_focus`: 本次要看的覆盖率切片/profile/包含与排除特性；用户说“我想看哪个模块/不含哪个扩展”时填这里。
- `scope_in`: 本次要分析的架构范围、组件范围、指令类别、行为类别。
- `scope_out`: 本次明确不分析的范围。
- `summary_include_regex` / `summary_exclude_prefixes` / `summary_exclude_regex`: summary 级别证据过滤；这里只放 target 额外规则，project spec 中 `NO` 特性的过滤由脚本自动合并。
- `line_exclude_regex`: `.gcov` 行级证据过滤；这里只放 target 额外规则，project spec 中 `NO` 特性的过滤由脚本自动合并。
- `coverage_thresholds`: 可选。summary 低覆盖阈值，默认 line<20%、branch<10%、call<10%；不同目标需要不同阈值时只改 target。
- `dimensions`: 脚本分组用的覆盖维度。
- `scenario_coverage`: 可选。目标级 cross 场景覆盖说明，包括场景轴、证据策略和优先场景提示。它是 checklist，不是完整组合矩阵。
- `path_analysis`: 可选。路径敏感分析用的证据策略、报告字段 checklist、置信度、单 case 增量规则、path marker 词表。它不是完整路径矩阵，不允许 agent 从这里脑补组合。
- `special_run_scope` / `manual_only_dimensions` / `dimension_metadata`: target 级 gate 约束。脚本会把它们带到 candidate/handoff；agent 不得把 manual-only 维度推荐成 default gate。
- `analysis_notes` / `duplicate_search_terms`: agent 做场景解释和查重时使用的目标专用信息。

如果用户说“我要分析 X，不包含 Y”，先检查是否已有合适 project spec 和 target；项目实现没有就从 `specs/TEMPLATE.json` 新建，覆盖率切片没有就从 `targets/TEMPLATE.json` 新建。后续脚本、报告、交接包都引用这个 target，target 再引用 project spec。

## When Triggered

Use this skill for:

- 分析 official/community Spike 覆盖率、`gcov`、`gcovr`、`.gcov/.gcda/.gcno`、coverage HTML。
- 根据低覆盖/0 覆盖证据找未覆盖的 cross 执行场景和应该补的 hyptest 测试点。
- 用户指定某个目标，比如 MemBlock、访存、vector load/store、atomic、trigger、exception、MMIO、TLB/page table、某个扩展或某组 Spike 文件。
- 用户要求“只看某类覆盖率”“排除某扩展/某模式”“根据覆盖率补测试点”。
- 用户要求判断“某个 cross 执行场景/执行流有没有跑过”“所有分支分别覆盖但同一条指令流可能没覆盖”“单 case 增量覆盖确认”“路径标记插桩”。

Do not use this skill for pure hyptest failure triage; use `$hyptest-failure-triage` for FAILED/timeout/stuck/mismatch logs. Do not use this skill alone to implement cases; pair it with `$hyptest-workflow`.

## Output Contract

Every coverage task must leave a durable Markdown artifact on disk, not only
terminal text. Prefer `--markdown-out <path>` when a script supports it; for
per-case matrix work, `run_case_coverage_matrix.py` always writes `summary.md`
and per-case `compare.md` under `--out-dir`. If the user asks for final
analysis, also save an agent-authored `.md` report and mention its exact path in
the final response.

Every final report must lead with `结论` / `数据` / `证据` / `限制与下一步`,
and the deliverable must be scenario-coverage-backed test-point cards, not raw
"file X is 0%" notes. Use `references/reporting_contract.md` for output paths,
report template, card fields, handoff packet skeleton, and quality bar.

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
| Project spec | Defines current project implementation, coverage runner boundary, stable environment variables, and available implementation surfaces. |
| Target file | Defines the concrete coverage slice under a project spec: focus/profile, scope, exclusions, dimensions, scenario axes, and target-specific guidance. |
| Scripts | Quickly find supporting evidence: files, dimensions, functions, source lines, branches, calls, 0% entries, low branch/call coverage; compare single-case gcov snapshots; parse optional path-marker logs. |
| Agent | Decide which cross execution scenario the evidence implies, whether it is a full path or only an edge, whether it is worth testing/in scope, whether it needs special run flags or instrumentation, and how to design a self-checkable test point. |
| hyptest-workflow | Only when implementation is requested: duplicate check, profile/gate decision, write test_point/case, register, compile, run. |

Do not let script output become the final answer by itself. Script output is evidence. The final test-point recommendation must come from target reading, source/gcov review, and architecture reasoning.

## Ground Rules

- Treat coverage as evidence, not as the test intent. A 0% file suggests a missing entry, but a high-quality test point must still name a cross execution scenario and an architectural observable: register/memory result, trap cause/tval, privilege/CSR state, vector result, or deterministic pass/fail behavior.
- Respect the selected target exactly. If an uncovered path matches `scope_out`, mark it out of scope instead of proposing a test. If the target does not say whether a path is in scope, mark it `needs target decision`.
- Do not edit a user's `~/.bashrc` automatically. This skill exposes a stable
  environment-variable interface; users may put those exports in their own
  shell profile, and the skill/scripts should reference the variables instead
  of embedding private absolute paths.
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

Prefer the shared environment-variable interface. Do not assume the author's
private workspace paths. Users are expected to set these variables in their
shell profile, such as `~/.bashrc`, and skill examples should reference the
variables instead of hardcoding absolute paths.

```text
Required minimum for normal layout:
  HYPTEST_SPIKE_COV  Spike coverage repo root
  HYPTEST_HOME       Hyptest repo root

Derived defaults:
  SPIKE_BUILD_DIR   $HYPTEST_SPIKE_COV/build
  SPIKE_GCOV_RAW    $HYPTEST_SPIKE_COV/cov_doc/gcov_raw
  SPIKE_SOURCE_ROOT $HYPTEST_SPIKE_COV
  HYPTEST_ELF_DIR   $HYPTEST_HOME/case_elf_asm/spike
  HYPTEST_SPIKE_COV_BIN $HYPTEST_SPIKE_COV/build/spike

Optional overrides for non-standard layouts:
  SPIKE_BUILD_DIR, SPIKE_GCOV_RAW, SPIKE_SOURCE_ROOT,
  HYPTEST_ELF_DIR, HYPTEST_SPIKE_COV_BIN
```

Do not define a generic summary-file environment variable. A summary file is
target/module-specific evidence, not a portable repo-level interface. Use an
explicit `--summary <summary.txt>` or choose/generate the concrete summary from
the selected target and run.

If the user provides different paths, use those.

## Workflow

1. **Select or create target**
   - If the user gives a target file, use it.
   - If the user names an existing target, use `targets/<name>.json`.
   - Read the target's `project_spec`; if it is missing or invalid, fix/create the project spec before analyzing.
   - If no target exists, create one from `targets/TEMPLATE.json` and fill `project_spec`, `coverage_focus`, `scope_in`, `scope_out`, and `dimensions` from the user’s purpose.
   - Read `analysis_notes` and `duplicate_search_terms` from the target; read project implementation details from `specs/*.json`, not from `SKILL.md`.
   - If the user has not provided enough detail to fill a safe target, ask for the missing target decision before analyzing.
   - After creating or editing a project spec, run `scripts/validate_spec.py <spec.json>` and fix errors before target analysis.
   - After creating or editing a target, run `scripts/validate_target.py <target.json>` and fix errors before analysis.

2. **Collect coverage artifacts**
   - Prefer existing summaries under `cov_doc/gcov_raw/*.txt`.
   - Prefer existing `.gcov` files under `cov_doc/gcov_raw/` or other coverage output dirs for line-level inspection.
   - Do not guess a target-specific summary filename from environment defaults.
     If the user did not provide a summary path, choose from actual files only
     when the selected target/run makes it unambiguous; otherwise ask for the
     concrete `summary.txt` input or generate a new summary from coverage data.
   - If no useful summary exists but the coverage build has `*.gcno` and `*.gcda`, run `gcov -b -c -o <build-dir> <files...>` and save output under a coverage doc/raw directory.
   - If `gcovr` is broken or unavailable, use system `gcov`. State that choice.
   - Do not mix the coverage Spike with hyptest compile/default-run Spike. The
     coverage matrix consumes existing ELF files from `HYPTEST_ELF_DIR` and runs
     them directly with `HYPTEST_SPIKE_COV_BIN` (default
     `$HYPTEST_SPIKE_COV/build/spike`); hyptest compilation and ordinary
     `HYPTEST_SPIKE_BIN` usage belong to `hyptest-workflow`.
   - `run_case_coverage_matrix.py` must not carry a script-owned hidden
     ISA/profile. When `--command-template` is omitted, it reads the selected
     target's project spec `coverage_spike.default_args` and builds
     `{spike_bin} <spec args> {elf}`. For NanHu-V5.1 AP this supplies the
     project-owned `--isa=...` and `--priv=MSU` automatically. Pass an explicit
     `--command-template` only for a special run that needs to override the
     project default, such as adding commit logs or trying a temporary Spike
     flag.

3. **Parse coverage robustly**
   - Track each `File '...'` block independently.
   - Stop associating totals with a file once `Creating 'x.gcov'` or `Removing 'x.gcov'` appears; gcov may print a final total line that otherwise contaminates the last file.
   - Record line, branch, call coverage separately.
   - Filter using explicit config only: target rules plus project spec `NO`-feature rules. Do not add hidden exclusions in the script.

4. **Rank coverage evidence**
   - First pass: use `scripts/analyze_spike_gcov.py --summary <summary.txt> --target <target.json> --top <N> --markdown-out <out>/summary.md --json-out <out>/summary.json`.
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
| Validate project spec | `scripts/validate_spec.py <spec.json>` | Run after every spec edit; catches runner defaults and unsupported-feature rule gaps. |
| Validate or create target | `scripts/validate_target.py <target.json>` | Run after every target edit; fix errors before analysis. |
| First-pass summary from gcov text | `scripts/analyze_spike_gcov.py --summary ... --target ...` | Save `summary.json` and `summary.md`; treat ranking as evidence only. |
| Source/gcov miss inspection | `scripts/inspect_gcov_lines.py --gcov-dir ... --target ... --file ...` | Save `line.json` and `line.md`; translate misses to scenarios in agent analysis. |
| Handoff skeleton | `scripts/build_handoff_packet.py --summary-json ... --inspect-json ...` | Fill `scenario_coverage_gap`, `cross_scenario_signature`, `target_semantic`, `expected_observable`, `profile_gate`, and `gate_note`; skeleton fields are not final. |
| Single-case counter delta | `scripts/compare_gcov_snapshots.py --before-dir ... --after-dir ...` | Use numeric branch/call counts and must-pass requirements; downgrade if evidence is incomplete. |
| Sequential per-case matrix | `scripts/run_case_coverage_matrix.py` | Run sequentially because `.gcda` counters are shared; treat counter movement as evidence, not proof of a scenario. |
| Path marker logs | `scripts/analyze_path_markers.py --log ... --require ...` | Strong records need pc+insn, seq, or access_id; marker sequence is evidence, not final proof. |
| Hygiene check | `scripts/check_handoff_final.py --strict-handoff/--strict-final-report ...` | Use before final handoff/report to catch raw skeleton fields and unsupported default gates. |

When a task asks how to run or interpret single-case increments, read `references/single_case_increment.md`. When designing or reviewing marker instrumentation, read `references/path_marker_instrumentation.md`. Keep target-specific marker names and scenario axes in the target file.

## Reporting Reference

When writing final reports, test-point cards, or handoff packets, read
`references/reporting_contract.md`. Keep the final answer practical: identify
what to write next, why it matters, and which coverage/source/path evidence
supports it.

## Target-Specific Guidance

Use only the selected target file for target-specific scope, exclusions, dimensions, interpretation notes, and duplicate-search terms. The skill body stays generic so the same workflow can analyze MemBlock today and a different Spike area tomorrow.

## Handoff To hyptest-workflow

This skill may prepare the packet, but it does not write hyptest files by itself. Trigger `$hyptest-workflow` only when the user asks to implement, write, register, compile, run, update `test_point/**/*.md`, update `ai_test_cases`/`manual_test_cases`, or update `test_register.c`.

When handing off, include the packet plus the exact coverage artifacts used. `hyptest-workflow` must still perform its own duplicate checks, spec profile checks, case quality gates, registration, compile, and run.
