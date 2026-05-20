# Coverage Target Files

Target files are the single place to define what the Spike coverage analysis is
about. Keep concrete scope, spec assumptions, exclusions, and dimensions here,
not in `SKILL.md` and not hardcoded in scripts.

## Fields

- `name`, `title`, `description`: identify the target in script output.
- `spec`: the target-specific spec/profile assumptions. Put the user's
  "我要测什么，规格是什么" content here. This is still coverage-analysis
  scope; hyptest implementation must do its own `hyptest-workflow` profile
  checks before writing cases.
- `scope_in`: what belongs to this analysis. The agent uses this when deciding
  whether an uncovered path is relevant.
- `scope_out`: what is intentionally excluded. The agent must not propose test
  points for these areas unless the user changes the target.
- `summary_include_regex`: keep only matching normalized gcov summary entries.
  Default usage is usually `^riscv/`.
- `summary_exclude_prefixes`: exclude files whose basename stem starts with one
  of these prefixes.
- `summary_exclude_regex`: exclude normalized summary entries matching these
  regexes.
- `line_exclude_regex`: optional evidence filter for `inspect_gcov_lines.py`.
  It excludes matching functions by function name, excludes matching events by
  source/evidence text, and masks matching source-context lines in markdown.
  Use it only for clear target exclusions; the agent still owns final judgment.
- `line_priority_regex`: optional ranking hints for `inspect_gcov_lines.py`.
  Matching functions are printed earlier, without hiding non-matching evidence.
- `dimensions`: coverage groups used by `analyze_spike_gcov.py`.
- `analysis_notes`: optional target-specific interpretation guidance for the
  agent. Keep spec assumptions here, alongside the rest of the target.
- `source_priority`: source files the agent should inspect first when turning
  raw coverage evidence into scenarios.
- `inspection_hints`: maps a dimension name to suggested `.gcov` files for the
  line-level inspection pass. The summary script prints these hints in the
  ranked evidence table.
- `duplicate_search_terms`: optional terms the agent should use when checking
  existing hyptest coverage before proposing implementation.
- `handoff_defaults`: default suggested locations and gate note for the
  hyptest-workflow handoff packet. It is advisory only; hyptest-workflow still
  performs its own profile/gate checks.

`build_handoff_packet.py` also reports `missing_inspection_files` when the
summary recommends `.gcov` files that were not included in the line-level
inspection JSON. Treat those as next files to inspect before finalizing a
test-point card.

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
python3 /nfs/home/wuyuanlong/.agents/skills/spike-coverage-testpoint/scripts/validate_target.py \
  /path/to/target.json
```

This checks structure, regex syntax, dimension item format, inspection hints,
and handoff defaults. It cannot prove the architecture scope is correct; the
agent still has to judge that from the user's goal and source review.
