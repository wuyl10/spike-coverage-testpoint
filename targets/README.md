# Coverage Target Files

Target files define one concrete coverage-analysis slice under a project spec.
Keep target scope, focus, exclusions, scenario axes, gate policy, and dimensions
here, not in `SKILL.md` and not hardcoded in scripts. Keep project
implementation details in `../specs/*.json`.

## Fields

- `name`, `title`, `description`: identify the target in script output.
- `project_spec`: path to the project implementation spec, usually a file under
  `specs/*.json`. It describes the coverage Spike runner, environment-variable
  interface, source root, and implementation surfaces this target selects from.
- `coverage_focus`: the target-specific coverage slice/profile. Put the user's
  "我要看哪部分覆盖率、包含/排除哪些 feature" content here. This is still
  coverage-analysis scope; hyptest implementation must do its own
  `hyptest-workflow` profile checks before writing cases.
- `scope_in`: what belongs to this analysis. The agent uses this when deciding
  whether an uncovered path is relevant.
- `scope_out`: what is intentionally excluded. The agent must not propose test
  points for these areas unless the user changes the target.
- `summary_include_regex`: keep only matching normalized gcov summary entries.
  Default usage is usually `^riscv/`.
- `summary_exclude_prefixes`: exclude files whose basename stem starts with one
  of these prefixes.
- `summary_exclude_regex`: target-specific extra exclusions for normalized
  summary entries. Scripts automatically append `summary_exclude_regex` from
  the selected project spec's `unsupported_feature_rules` for features marked
  `NO`, so targets do not need to duplicate project-unsupported feature
  filters.
- `line_exclude_regex`: optional evidence filter for `inspect_gcov_lines.py`.
  It excludes matching functions by function name, excludes matching events by
  source/evidence text, and masks matching source-context lines in markdown.
  Use it only for clear target-specific exclusions; scripts automatically append
  project-spec unsupported-feature line filters. The agent still owns final judgment.
  The line inspector reports excluded function/event counts; include those
  counts in analysis when filters may hide meaningful evidence.
- `line_priority_regex`: optional ranking hints for `inspect_gcov_lines.py`.
  Matching functions are printed earlier, without hiding non-matching evidence.
- `coverage_thresholds`: optional low-coverage thresholds used by
  `analyze_spike_gcov.py`. Supported keys are `low_line_pct`,
  `low_branch_pct`, and `low_call_pct`; defaults are 20/10/10.
- `dimensions`: evidence groups used by `analyze_spike_gcov.py`. These are not
  final test intents; the agent still maps evidence to cross execution
  scenarios.
- `scenario_coverage`: optional scenario-first guidance. Use it to name the
  cross-scenario axes that matter for this target and to state evidence policy.
  It is a reporting checklist, not a full scenario matrix.
- `path_analysis`: optional path-sensitive evidence policy. Use it for path
  confidence labels, reporting checklists, single-case increment rules, and
  path-marker names. It is not a complete path matrix or architecture spec.
- `analysis_notes`: optional target-specific interpretation guidance for the
  agent. Keep coverage-slice assumptions here, alongside the rest of the target.
- `source_priority`: source files the agent should inspect first when turning
  raw coverage evidence into scenarios.
- `inspection_hints`: maps a dimension name to suggested `.gcov` files for the
  line-level inspection pass. The summary script prints these hints in the
  ranked evidence table.
- `duplicate_search_terms`: optional terms the agent should use when checking
  existing hyptest coverage before proposing implementation. Prefer keys that
  match `dimensions`; validator warns on extra keys so aliases stay explicit.
- `duplicate_search_aliases`: optional aliases for dimension names. These also
  help focused summary searches find dimensions by semantic words that do not
  appear in source file names. Gate matching uses exact dimension names or
  these explicit aliases, not broad substring matching.
- `handoff_defaults`: default suggested locations and gate note for the
  hyptest-workflow handoff packet. It is advisory only; hyptest-workflow still
  performs its own profile/gate checks.
- `special_run_scope`: target areas that usually require non-default runtime,
  simulator, device, log, or instrumentation setup.
- `manual_only_dimensions`: dimensions that must not be recommended for default
  gate without an explicit target/profile decision.
- `dimension_metadata`: optional per-dimension metadata such as
  `default_gate_allowed`, `requires_runtime_option`, and a dimension-specific
  `gate_note`. Summary and handoff scripts propagate this into candidate
  `dimension_gate`; manual-only dimensions must not become default-gate
  recommendations without an explicit target/profile decision.

`build_handoff_packet.py` also reports `missing_inspection_files` when the
summary recommends `.gcov` files that were not included in the line-level
inspection JSON. Treat those as next files to inspect before finalizing a
test-point card.

`build_handoff_packet.py` reports `same_flow_evidence` separately from
line/branch/call coverage. Treat `aggregate-only` as "edges were seen somewhere
in the suite, but one dynamic instruction/access path is not proven"; upgrade
only with single-case increment evidence or correlated path markers.
Treat `suite-summary-gap` as a summary-level clue only; the agent must identify
the must-pass source events before calling a path confirmed-not-executed.

`analyze_spike_gcov.py` reports `missing_entries_by_dimension` when a target
entry does not appear in the selected gcov snapshot. This is not the same as 0%
coverage; it may mean a Spike version/profile/build did not emit that entry.

The scripts treat effective filters as `target rules + selected project spec
NO-feature rules`. Keep implementation unsupported-feature regexes in
`../specs/*.json` under `unsupported_feature_rules`; keep only this coverage
slice's extra choices in the target.

## Scenario Coverage

Use `scenario_coverage` when the target cares about which architecture-visible
cross execution scenarios were exercised, not about line/branch/call coverage
as an end in itself. The field is optional but recommended for new targets.

Recommended subfields:

- `purpose`: short target-specific statement of what scenario coverage means.
- `scenario_axes`: checklist axes for final reports, such as instruction/access
  class, privilege/profile/gate, address/translation/protection/device
  condition, exception/trigger/cache/vector/atomic subcondition, and
  architectural observable.
- `evidence_policy`: guardrails that keep coverage counters in the evidence
  layer. Include a reminder not to claim same-flow scenario coverage from
  aggregate counters alone.
- `priority_scenarios`: optional hints for especially valuable scenario
  families. Keep them high-level; do not use this as an exhaustive matrix.

Important boundary:

- Line, branch, call, entry, and case-counter movement are supporting evidence.
- The final recommendation must name the missing cross scenario and observable.
- Do not generate blind Cartesian products from `scenario_axes` or
  `priority_scenarios`; derive candidate signatures from target scope, Spike
  source, `.gcov`, single-case deltas, or path-marker records.

## Path Analysis

Use `path_analysis` when branch/call coverage is not enough to prove the same
dynamic instruction/access executed a full path. Keep it evidence-driven:
derive path signatures from Spike source and `.gcov`, not from a predeclared
Cartesian product.

Recommended subfields:

- `confidence_levels`: labels such as `confirmed-not-executed`,
  `counter-increment-observed`, `single-case-increment-confirmed`,
  `edge-covered-path-unknown`, `needs-path-instrumentation`, and
  `out-of-scope`.
- `evidence_policy`: guardrails that prevent over-inference from aggregate
  branch/call coverage.
- `path_signature_fields`: a reporting checklist for the agent. These fields
  guide how to describe a source-proven path; they are not enumerated values to
  combine blindly.
- `path_markers`: marker names plus meanings and suggested Spike source
  locations for coverage-only instrumentation.
- `marker_correlation_policy`: rules for deciding whether marker records prove
  same-flow correlation. Strong records should include pc+insn, seq, or access_id;
  JSON without correlation fields and text fallback are weak evidence.
- `single_case_increment`: how to interpret before/after `.gcov` snapshot
  deltas for one tiny case.

Important boundary:

- `.gcov` branch/call counters prove edge coverage, not full path coverage.
- A controlled single-case run plus counter increases first gives
  `counter-increment-observed`; upgrade to `single-case-increment-confirmed`
  only when the run is tiny/isolated, target PC/instruction evidence exists,
  every must-pass counter increased, and no required event/file is missing or
  decreased.
- A per-instruction/access path-marker log is the preferred proof when all
  edges are covered in aggregate but same-flow correlation matters.

## Dimension Items

- `riscv/mmu.cc`: direct normalized source path.
- `insn:lw`: expands to `riscv/insns/lw.h`.
- `glob:riscv/insns/amo*.h`: expands from entries present in the gcov summary.

## Boundary

The scripts use target files only to collect and group evidence. They should not
emit final semantic test ideas. The agent reads the same target file, inspects
source/gcov when needed, and then decides which uncovered code corresponds to a
valuable architecture scenario.

## Validation

After editing a target, run:

```bash
python3 scripts/validate_spec.py specs/<project_spec>.json
python3 scripts/validate_target.py /path/to/target.json
```

This checks structure, regex syntax, dimension item format, inspection hints,
handoff defaults, and the referenced project spec. `validate_spec.py` is useful
when the error belongs to project-owned runner/support-matrix configuration. The
checks cannot prove the architecture scope is correct; the agent still has to
judge that from the user's goal and source review.
