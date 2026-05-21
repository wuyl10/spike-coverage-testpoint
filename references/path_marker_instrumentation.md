# Path Marker Instrumentation Reference

This reference is for coverage Spike builds only. It describes a lightweight
way to prove that a full execution flow occurred when gcov branch/call counters
are not enough.

## Goal

Emit one correlated path-marker record per guest instruction or memory access:

```json
{"pc":"0x80001000","insn":"lw","markers":["mem.access.scalar_load","mem.translate.tlb_miss_walk","mem.fault.page"]}
```

This preserves same-flow correlation. A plain counter saying each marker
appeared somewhere is weaker and should be treated like edge evidence.

## Requirements

- Keep instrumentation disabled in normal Spike.
- Enable only in coverage/debug builds with a compile flag, runtime flag, or
  environment variable such as `SPIKE_MEM_PATH_COV`.
- Do not change architectural behavior, exception priority, timing model, or
  return values.
- Prefer one record per dynamic guest instruction/access over scattered logs.
- Marker names should come from the selected target file's
  `path_analysis.path_markers`.

## Minimal C++ Shape

This is a template, not a required exact implementation:

```cpp
#ifdef SPIKE_MEM_PATH_COV
struct mem_path_cov_t {
  bool enabled = false;
  reg_t pc = 0;
  std::vector<const char*> markers;

  void begin(reg_t current_pc) {
    if (!enabled) return;
    pc = current_pc;
    markers.clear();
  }

  void mark(const char* marker) {
    if (!enabled) return;
    markers.push_back(marker);
  }

  void end(const char* insn_name) {
    if (!enabled || markers.empty()) return;
    // Emit JSONL to the configured stream/file.
  }
};
#define MEM_PATH_BEGIN(pc) do { mem_path_cov.begin(pc); } while (0)
#define MEM_PATH_MARK(name) do { mem_path_cov.mark(name); } while (0)
#define MEM_PATH_END(name) do { mem_path_cov.end(name); } while (0)
#else
#define MEM_PATH_BEGIN(pc) do {} while (0)
#define MEM_PATH_MARK(name) do {} while (0)
#define MEM_PATH_END(name) do {} while (0)
#endif
```

## Suggested MemBlock Marker Points

Use target-specific marker names from `targets/memblock_non_h.json`.

- `mem.access.scalar_load`: scalar/FP load enters `mmu_t::load` or
  `load_slow_path`.
- `mem.access.scalar_store`: scalar/FP store enters `mmu_t::store` or
  `store_slow_path`.
- `mem.access.amo`: AMO/LR/SC/AMOCAS enters the atomic path.
- `mem.translate.tlb_hit`: access uses fast translation/cache path.
- `mem.translate.tlb_miss_walk`: access walks/refills translation state.
- `mem.protect.pmp_deny`: PMP/PMA/PBMT rejects access.
- `mem.addr.misaligned`: access takes address-misaligned path.
- `mem.addr.cross_page`: access spans boundary/page and uses split handling.
- `mem.fault.page`: page-fault exception path.
- `mem.fault.access`: access-fault exception path.
- `mem.trigger.match`: memory trigger matched.
- `vec.mask.skip`: vector memory lane skipped by mask.
- `vec.vstart.nonzero`: vector memory resumes from nonzero vstart.
- `vec.fault.partial`: vector memory has partial progress before fault.

## Workflow

1. Define the path signature from the target's `combination_axes`.
2. Choose required markers from `path_markers`.
3. Run one tiny case with coverage Spike path markers enabled.
4. Analyze the log:

```bash
python3 scripts/analyze_path_markers.py \
  --log /tmp/spike_mem_path_cov.jsonl \
  --require mem.access.scalar_load \
  --require mem.translate.tlb_miss_walk \
  --require mem.fault.page \
  --ordered \
  --markdown
```

5. Interpret:
   - Required marker sequence appears in one record:
     `single-case-increment-confirmed` or marker-confirmed path evidence.
   - Individual markers appear only in separate records:
     `edge-covered-path-unknown`.
   - Required marker never appears:
     `confirmed-not-executed` for that marker requirement, or
     `needs-path-instrumentation` if the marker was not implemented.

## Common Mistakes

- Emitting only global marker counters and claiming full path coverage.
- Logging markers from helper calls without a per-instruction/access record.
- Letting marker output perturb exception behavior or commit ordering.
- Adding target-specific marker names to `SKILL.md` instead of the target file.
