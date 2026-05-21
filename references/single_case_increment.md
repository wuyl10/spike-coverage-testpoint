# Single-Case Incremental Coverage Reference

Use this when the user asks whether one specific scenario/execution flow ran.
The goal is to compare `.gcov` counters before and after running one tiny case.

## What It Can Prove

Strong evidence:

- A required line/branch/call moved from zero to nonzero.
- A required line/branch/call increased during an isolated run.
- Spike log, commit log, target PC, or equivalent run evidence confirms the
  target guest instruction executed.

Limits:

- It is not full path coverage if the case executes many similar instructions.
- It cannot prove internal same-flow correlation when several dynamic
  instructions could have contributed different counter increments.
- It cannot prove a path through logic that has no gcov-visible counter unless
  path markers are added.
- It cannot support positive confirmation if required events disappear from the
  after snapshot, counters decrease/reset, or required files are missing.

## Preferred Workflow

1. Build a path signature:

```text
target instruction or entry:
shared source function path:
must-pass source line/branch/call evidence:
source-proven condition under test:
architectural observable:
remaining uncertainty:
```

2. Identify must-pass evidence points from source/gcov:

```text
file:
function:
source line:
kind: line | branch | call
why required:
```

3. Create a baseline `.gcov` snapshot.

The exact gcov command depends on the Spike build layout. Keep the snapshot
under a run-specific directory, for example:

```bash
mkdir -p /tmp/spike_cov_one_case/before
# Generate or copy baseline .gcov files into /tmp/spike_cov_one_case/before.
```

4. Run one tiny case.

Prefer a case with one target memory/vector/atomic instruction plus minimal
setup and checks. Use a temporary environment variable when hyptest invokes
Spike:

```bash
HYPTEST_SPIKE_BIN=/path/to/build-cov/spike \
python3 get_result.py --platform spike --elf-path /path/to/case.ELF --jobs 1
```

For direct Spike runs, use logs when useful:

```bash
/path/to/build-cov/spike -l --log-commits --log=/tmp/spike_cov_one_case/spike.log /path/to/case.ELF
```

5. Generate the post-run `.gcov` snapshot.

```bash
mkdir -p /tmp/spike_cov_one_case/after
# Regenerate or copy post-run .gcov files into /tmp/spike_cov_one_case/after.
```

6. Compare snapshots:

```bash
python3 scripts/compare_gcov_snapshots.py \
  --before-dir /tmp/spike_cov_one_case/before \
  --after-dir /tmp/spike_cov_one_case/after \
  --target targets/memblock_non_h.json \
  --file mmu.cc.gcov \
  --file mmu.h.gcov \
  --file v_ext_macros.h.gcov \
  --markdown
```

## Interpretation

- `confirmed-not-executed`: any must-pass point is `still-zero`.
- `counter-increment-observed`: required points are `newly-covered` or
  `increased`, but the run is not isolated enough, target PC/instruction
  evidence is missing, profile evidence is incomplete, or not all required
  points were checked.
- `single-case-increment-confirmed`: all must-pass points are `newly-covered`
  or `increased` in a tiny single-purpose run, Spike log/PC evidence confirms
  the target instruction, and no required point/file is missing or
  `decreased-or-reset`.
- `edge-covered-path-unknown`: counters are covered in aggregate, but no
  controlled single-case increment or marker log proves same-flow correlation.
- `needs-path-instrumentation`: the desired path cannot be correlated with
  gcov counters and logs; use path markers.

Invalid for positive path confirmation until explained:

- `decreased-or-reset`
- `missing-after-event`
- unresolved `missing-before-event`
- `missing-before-file`
- `missing-after-file`

## Good Final Evidence

For each confirmed path, report:

```text
case:
spike command/log:
before snapshot:
after snapshot:
required evidence points:
  - file/kind/line/branch-or-call ordinal: before -> after
path confidence:
observable:
remaining uncertainty:
```
