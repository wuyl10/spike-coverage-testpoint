# Reporting Contract

Use this file when the user asks for a final analysis report, test-point plan,
handoff packet, or reproducible coverage output. Keep `SKILL.md` focused on the
workflow and use this reference for durable output details.

## Required Markdown Sections

Every coverage task must leave a Markdown artifact on disk, not only terminal
text. For script-driven work, use `--markdown-out <path>` when available; for
per-case matrix work, `run_case_coverage_matrix.py` writes `summary.md` and
per-case `compare.md` under `--out-dir`. If the user asks for final analysis,
also save an agent-authored `.md` report in the same output directory or at the
explicit user path.

Put these sections near the top of every final report:

```text
结论：当前覆盖率证据指向哪些 cross 执行场景缺口
数据：target、输入路径、case 数、覆盖计数、runner 状态等
证据：具体文件/函数/源码行/branch/call/case log/compare 文件
限制与下一步：当前证据不能证明什么，下一步要 inspect、单 case 增量还是 path marker
```

Write human-readable report headings and explanatory prose in Chinese. JSON keys
and stable evidence field names may stay in English.

## Output Paths

If the user gives an explicit output path, use it exactly. If the user only asks
for analysis, reports, or "run and analyze" without a path, choose a stable path
automatically instead of asking.

Use this default structure:

```text
Spike coverage repo:
  <spike_cov_repo>

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
example `<YYYYMMDD>_current`, `<YYYYMMDD>_all_cases`,
`<YYYYMMDD>_after_new_mem_cases`, or `<YYYYMMDD>_path_marker_trial`. Avoid writing
analysis outputs inside the skill directory; the skill directory is tool source,
not a result store.

## Test-Point Card Fields

The deliverable is a ranked set of scenario-coverage-backed test-point cards.
Each card should answer:

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

Never stop at "file X is 0%". Always translate coverage into a self-checkable
scenario, or explicitly mark it as not currently worth writing.

## Default Report Shape

Use this structure by default:

```markdown
## 覆盖率输入
- Spike repo:
- coverage summary:
- project spec:
- target file:
- coverage focus/profile:
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
```

## Handoff Packet Skeleton

Use this packet only when the user asks what to implement next, asks for a
handoff, or plans to write cases. For method/risk/explanation-only questions, a
full handoff packet is optional.

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

Final user-facing answers must not contain raw `TODO(agent)` placeholders. If a
field cannot be resolved, write `needs source confirmation: <specific reason>`
or `needs profile decision: <specific reason>`.

## Quality Bar

A high-quality scenario-coverage-driven test point should normally include:

- A precise cross execution scenario, not just an instruction mnemonic or a
  source line.
- An observable oracle: memory bytes, register value, trap cause/tval, CSR bit,
  vector element result, or deterministic side effect.
- At least one meaningful corner path when useful: fault, mask skip, partial
  progress, permission denied, reservation failure, trigger timing, boundary
  split, stale translation/cache state, or unsupported access.
- A clear reason the supporting Spike entry/line/branch/call/path-marker
  evidence implies a missing scenario.
- A path confidence label. Do not call something covered as a full path if you
  only have aggregate branch coverage.
- Source/gcov evidence for at least the top candidates, unless the user only
  asks for a coarse first pass.
- A duplicate-check plan against existing hyptest tests.

Avoid proposing:

- Pure smoke tests that only execute an instruction once.
- Tests whose only oracle is "coverage improved".
- Out-of-scope targets from the selected target file.
- Default-gate tests that require special simulator/device/logging knobs.
