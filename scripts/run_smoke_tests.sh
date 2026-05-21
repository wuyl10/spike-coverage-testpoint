#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SUMMARY="${SPIKE_COV_SUMMARY:-/nfs/home/wuyuanlong/workspace/offical-spike-coverage/cov_doc/gcov_raw/gcov_memblock_non_h_summary.txt}"
GCOV_RAW="${SPIKE_GCOV_RAW:-/nfs/home/wuyuanlong/workspace/offical-spike-coverage/cov_doc/gcov_raw}"
SOURCE_ROOT="${SPIKE_SOURCE_ROOT:-/nfs/home/wuyuanlong/workspace/offical-spike-coverage}"
OUT_DIR="${SPIKE_COV_SKILL_SMOKE_OUT:-/tmp/spike_cov_skill_smoke}"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

python3 scripts/validate_target.py targets/TEMPLATE.json
python3 scripts/validate_target.py targets/memblock_non_h.json
python3 -m py_compile scripts/*.py
python3 -m json.tool targets/TEMPLATE.json >/dev/null
python3 -m json.tool targets/memblock_non_h.json >/dev/null
python3 -m json.tool evals/evals.json >/dev/null

python3 scripts/analyze_spike_gcov.py \
  --summary "$SUMMARY" \
  --target targets/memblock_non_h.json \
  --top 3 \
  --json-out "$OUT_DIR/summary.json" \
  --markdown > "$OUT_DIR/summary.md"
grep -q "Ranked mixed entry/shared-review gaps" "$OUT_DIR/summary.md"
grep -q "Class reason" "$OUT_DIR/summary.md"
grep -q "low-call entries" "$OUT_DIR/summary.md"

cat > "$OUT_DIR/synthetic_target.json" <<'EOF'
{
  "name": "synthetic",
  "title": "Synthetic coverage target",
  "description": "Smoke fixture for focus/gate/call gaps",
  "spec": {
    "profile": "synthetic",
    "source_of_truth": "smoke",
    "included_extensions_or_features": [],
    "excluded_extensions_or_features": []
  },
  "scope_in": ["synthetic"],
  "scope_out": ["not part of synthetic smoke"],
  "summary_include_regex": ["^riscv/"],
  "summary_exclude_prefixes": [],
  "summary_exclude_regex": [],
  "line_exclude_regex": [],
  "line_priority_regex": ["cache_error"],
  "coverage_thresholds": {
    "low_line_pct": 20.0,
    "low_branch_pct": 10.0,
    "low_call_pct": 10.0
  },
  "source_priority": ["riscv/mmu.cc"],
  "dimensions": {
    "manual device path": ["riscv/mmu.cc", "insn:not_in_summary"],
    "ordinary path": ["riscv/ordinary.cc"]
  },
  "analysis_notes": [],
  "path_analysis": {
    "confidence_levels": [
      "confirmed-not-executed",
      "counter-increment-observed",
      "single-case-increment-confirmed",
      "edge-covered-path-unknown",
      "needs-path-instrumentation",
      "out-of-scope"
    ],
    "evidence_policy": ["derive path signatures from source/gcov evidence"],
    "path_signature_fields": ["target instruction or entry", "architectural observable"],
    "path_markers": {},
    "single_case_increment": {
      "interpretation": ["downgrade to counter-increment-observed when isolation is incomplete"]
    }
  },
  "inspection_hints": {
    "manual device path": ["mmu.cc.gcov"],
    "ordinary path": ["ordinary.cc.gcov"]
  },
  "duplicate_search_terms": {
    "manual device path": ["XSError", "cache error", "NMI"]
  },
  "duplicate_search_aliases": {
    "manual device path": ["xserror", "nmi"]
  },
  "handoff_defaults": {
    "suggested_test_point_area": "test_point/synthetic",
    "suggested_case_area": "ai_test_cases/synthetic",
    "default_gate_note": "needs profile decision",
    "implementation_owner": "hyptest-workflow"
  },
  "special_run_scope": ["manual device path"],
  "manual_only_dimensions": ["manual device path"],
  "dimension_metadata": {
    "manual device path": {
      "default_gate_allowed": false,
      "requires_runtime_option": true,
      "gate_note": "manual/special-run synthetic gate"
    }
  }
}
EOF
cat > "$OUT_DIR/synthetic_summary.txt" <<'EOF'
File 'riscv/mmu.cc'
Lines executed:90.00% of 10
Branches executed:90.00% of 10
Calls executed:0.00% of 4
Creating 'mmu.cc.gcov'
File 'riscv/ordinary.cc'
Lines executed:100.00% of 10
Branches executed:100.00% of 10
Calls executed:100.00% of 4
Creating 'ordinary.cc.gcov'
EOF
cat > "$OUT_DIR/mmu.cc.gcov" <<'EOF'
        -:    0:Source:riscv/mmu.cc
function _Z11cache_errorv called 1 returned 100% blocks executed 80%
       10:   42:void cache_error() { notify_xserror(); }
call    0 never executed
branch  2 taken 0 (fallthrough)
EOF
python3 scripts/validate_target.py "$OUT_DIR/synthetic_target.json"
python3 scripts/analyze_spike_gcov.py \
  --summary "$OUT_DIR/synthetic_summary.txt" \
  --target "$OUT_DIR/synthetic_target.json" \
  --focus XSError \
  --json-out "$OUT_DIR/synth_summary.json" \
  --markdown > "$OUT_DIR/synth_summary.md"
grep -q "manual device path" "$OUT_DIR/synth_summary.md"
grep -q "low-call entries" "$OUT_DIR/synth_summary.md"
grep -q "manual/special-run synthetic gate" "$OUT_DIR/synth_summary.md"
grep -q "Missing target entries" "$OUT_DIR/synth_summary.md"
python3 scripts/inspect_gcov_lines.py \
  --gcov-dir "$OUT_DIR" \
  --source-root "$OUT_DIR" \
  --target "$OUT_DIR/synthetic_target.json" \
  --file mmu.cc.gcov \
  --json-out "$OUT_DIR/synth_line.json" \
  --markdown > "$OUT_DIR/synth_line.md"
grep -q "ordinals=branch-taken-0:2, call-never:0" "$OUT_DIR/synth_line.md"
python3 scripts/build_handoff_packet.py \
  --summary-json "$OUT_DIR/synth_summary.json" \
  --inspect-json "$OUT_DIR/synth_line.json" \
  --select nmi \
  --top 1 \
  --markdown > "$OUT_DIR/synth_handoff.md"
grep -q "dimension_gate" "$OUT_DIR/synth_handoff.md"
grep -q "default_gate_eligible: no - target dimension is manual/special-run" "$OUT_DIR/synth_handoff.md"
grep -q "low_call_entries" "$OUT_DIR/synth_handoff.md"
grep -q "same_flow_evidence" "$OUT_DIR/synth_handoff.md"
grep -q "aggregate-only" "$OUT_DIR/synth_handoff.md"
grep -q "basis: summary-low-branch-or-call" "$OUT_DIR/synth_handoff.md"
grep -q "missing_entries" "$OUT_DIR/synth_handoff.md"

python3 scripts/inspect_gcov_lines.py \
  --gcov-dir "$GCOV_RAW" \
  --source-root "$SOURCE_ROOT" \
  --target targets/memblock_non_h.json \
  --file mmu.cc.gcov \
  --context 2 \
  --max-functions 2 \
  --json-out "$OUT_DIR/line.json" \
  --markdown > "$OUT_DIR/line.md"
grep -q "excluded by filters" "$OUT_DIR/line.md"

python3 scripts/build_handoff_packet.py \
  --summary-json "$OUT_DIR/summary.json" \
  --inspect-json "$OUT_DIR/line.json" \
  --top 1 \
  --markdown > "$OUT_DIR/handoff.md"
grep -q "line_evidence_status" "$OUT_DIR/handoff.md"
grep -q "inspection-hint-weak" "$OUT_DIR/handoff.md"
grep -q "profile_gate" "$OUT_DIR/handoff.md"
grep -q "same_flow_evidence" "$OUT_DIR/handoff.md"
python3 scripts/check_handoff_final.py --strict-handoff "$OUT_DIR/handoff.md"

cat > "$OUT_DIR/bad_default_gate.md" <<'EOF'
evidence_class: shared-path
line_evidence_status: exact-shared-source-evidence
same_flow_evidence:
  status: aggregate-only
path_confidence: confirmed-not-executed
profile_gate:
  default_gate_eligible: needs source confirmation: yes/no/unknown after review
expected_observable: memory result
gate_note: default
EOF
if python3 scripts/check_handoff_final.py --strict-handoff "$OUT_DIR/bad_default_gate.md" >/dev/null 2>&1; then
  echo "strict handoff accepted an unresolved default gate" >&2
  exit 1
fi

cat > "$OUT_DIR/good_default_gate.md" <<'EOF'
evidence_class: shared-path
line_evidence_status: exact-shared-source-evidence
same_flow_evidence:
  status: single-case-increment-confirmed
path_confidence: confirmed-not-executed
profile_gate:
  default_gate_eligible: yes
expected_observable: memory result
gate_note: default
EOF
python3 scripts/check_handoff_final.py --strict-handoff "$OUT_DIR/good_default_gate.md" >/dev/null

cat > "$OUT_DIR/generic_skeleton.md" <<'EOF'
evidence_class: shared-path
line_evidence_status: exact-shared-source-evidence
same_flow_evidence:
  status: aggregate-only
path_confidence: needs source confirmation: choose one after evidence review
profile_gate:
  default_gate_eligible: no
expected_observable: needs source confirmation: register/memory/trap/CSR/vector observable
EOF
if python3 scripts/check_handoff_final.py --strict-final-report "$OUT_DIR/generic_skeleton.md" >/dev/null 2>&1; then
  echo "strict final report accepted generic skeleton fields" >&2
  exit 1
fi
cat > "$OUT_DIR/generic_profile_skeleton.md" <<'EOF'
evidence_class: shared-path
line_evidence_status: exact-shared-source-evidence
same_flow_evidence:
  status: aggregate-only
path_confidence: counter-increment-observed
profile_gate:
  extension_required: needs source confirmation: infer required ISA/profile feature from source and representative entries
  default_gate_eligible: needs source confirmation: yes/no/unknown after confirming feature availability and deterministic observable
expected_observable: memory result
EOF
if python3 scripts/check_handoff_final.py --strict-final-report "$OUT_DIR/generic_profile_skeleton.md" >/dev/null 2>&1; then
  echo "strict final report accepted generic profile skeleton fields" >&2
  exit 1
fi

cat > "$OUT_DIR/marker_strong.jsonl" <<'EOF'
{"pc":"0x80001000","insn":"lw","markers":["mem.access.scalar_load","mem.translate.tlb_miss_walk","mem.fault.page"]}
EOF
python3 scripts/analyze_path_markers.py \
  --log "$OUT_DIR/marker_strong.jsonl" \
  --require mem.access.scalar_load \
  --require mem.translate.tlb_miss_walk \
  --require mem.fault.page \
  --ordered \
  --markdown > "$OUT_DIR/marker_strong.md"
grep -q "marker-sequence-observed" "$OUT_DIR/marker_strong.md"

cat > "$OUT_DIR/marker_weak.jsonl" <<'EOF'
{"markers":["mem.access.scalar_load","mem.translate.tlb_miss_walk","mem.fault.page"]}
EOF
python3 scripts/analyze_path_markers.py \
  --log "$OUT_DIR/marker_weak.jsonl" \
  --require mem.access.scalar_load \
  --require mem.translate.tlb_miss_walk \
  --require mem.fault.page \
  --ordered \
  --markdown > "$OUT_DIR/marker_weak.md"
grep -q "json-marker-sequence-observed-weak" "$OUT_DIR/marker_weak.md"
grep -q "Weak JSON" "$OUT_DIR/marker_weak.md"
cat > "$OUT_DIR/marker_grouped.jsonl" <<'EOF'
{"access_id":"a1","seq":1,"markers":["mem.access.scalar_load"]}
{"access_id":"a1","seq":2,"markers":["mem.translate.tlb_miss_walk"]}
{"access_id":"a1","seq":3,"markers":["mem.fault.page"]}
EOF
python3 scripts/analyze_path_markers.py \
  --log "$OUT_DIR/marker_grouped.jsonl" \
  --require mem.access.scalar_load \
  --require mem.translate.tlb_miss_walk \
  --require mem.fault.page \
  --ordered \
  --group-by access_id \
  --markdown > "$OUT_DIR/marker_grouped.md"
grep -q "grouped-by-access_id-ordered-subsequence" "$OUT_DIR/marker_grouped.md"
grep -q "marker-sequence-observed" "$OUT_DIR/marker_grouped.md"

mkdir -p "$OUT_DIR/cmp_before" "$OUT_DIR/cmp_after"
cat > "$OUT_DIR/cmp_before/synth.gcov" <<'EOF'
function _Z4testv called 1 returned 100% blocks executed 100%
        5:   10:int test() { return callee(); }
branch  0 taken 3 (fallthrough)
call    0 returned 2
       10:   11:int keep() { return 1; }
branch  0 taken 1 (fallthrough)
EOF
cat > "$OUT_DIR/cmp_after/synth.gcov" <<'EOF'
function _Z4testv called 1 returned 100% blocks executed 100%
        4:   10:int test() { return callee(); }
branch  0 taken 1 (fallthrough)
call    0 never executed
EOF
python3 scripts/compare_gcov_snapshots.py \
  --before-dir "$OUT_DIR/cmp_before" \
  --after-dir "$OUT_DIR/cmp_after" \
  --file synth.gcov \
  --require-event synth.gcov:branch:10:0 \
  --markdown \
  --limit 20 > "$OUT_DIR/compare.md"
grep -q "key_mode: \`stable-line\`" "$OUT_DIR/compare.md"
grep -q "decreased-or-reset" "$OUT_DIR/compare.md"
grep -q "missing-after-event" "$OUT_DIR/compare.md"
grep -q "counter formats" "$OUT_DIR/compare.md"
grep -q "Required evidence points" "$OUT_DIR/compare.md"
grep -q "all_required_passed: False" "$OUT_DIR/compare.md"

cat > "$OUT_DIR/cmp_before/percent.gcov" <<'EOF'
function _Z7percentv called 1 returned 100% blocks executed 100%
        1:   20:int percent() { return flag ? 1 : 0; }
branch  0 taken 50% (fallthrough)
EOF
cat > "$OUT_DIR/cmp_after/percent.gcov" <<'EOF'
function _Z7percentv called 1 returned 100% blocks executed 100%
        2:   20:int percent() { return flag ? 1 : 0; }
branch  0 taken 75% (fallthrough)
EOF
python3 scripts/compare_gcov_snapshots.py \
  --before-dir "$OUT_DIR/cmp_before" \
  --after-dir "$OUT_DIR/cmp_after" \
  --file percent.gcov \
  --markdown \
  --limit 20 > "$OUT_DIR/compare_percent.md"
grep -q "not-comparable-counter-format" "$OUT_DIR/compare_percent.md"
grep -q "percent->percent" "$OUT_DIR/compare_percent.md"

mkdir -p "$OUT_DIR/fake_hyptest/case_elf_asm/spike" "$OUT_DIR/fake_build"
touch "$OUT_DIR/fake_hyptest/case_elf_asm/spike/ai_probe_a.ELF"
touch "$OUT_DIR/fake_hyptest/case_elf_asm/spike/ai_probe_b.ELF"
python3 scripts/run_case_coverage_matrix.py \
  --hyptest-repo "$OUT_DIR/fake_hyptest" \
  --target targets/memblock_non_h.json \
  --build-dir "$OUT_DIR/fake_build" \
  --all-elves \
  --limit 1 \
  --skip-gcov \
  --command-template "bash -lc 'echo PASSED {case_name}'" \
  --out-dir "$OUT_DIR/case_matrix_fake" > "$OUT_DIR/case_matrix_fake.stdout"
grep -q "runner=PASS" "$OUT_DIR/case_matrix_fake.stdout"
grep -q "Runner status" "$OUT_DIR/case_matrix_fake/summary.md"
grep -q "ai_probe_a" "$OUT_DIR/case_matrix_fake/summary.md"
python3 scripts/run_case_coverage_matrix.py \
  --hyptest-repo "$OUT_DIR/fake_hyptest" \
  --target targets/memblock_non_h.json \
  --build-dir "$OUT_DIR/fake_build" \
  --all-elves \
  --limit 1 \
  --gcno-from-target \
  --dry-run \
  --out-dir "$OUT_DIR/case_matrix_dry" > "$OUT_DIR/case_matrix_dry.stdout"
grep -q "dry_run=true" "$OUT_DIR/case_matrix_dry.stdout"
grep -q "selected_case_count=1" "$OUT_DIR/case_matrix_dry.stdout"
grep -q "Unresolved gcno hints" "$OUT_DIR/case_matrix_dry/summary.md"

cat > "$OUT_DIR/fake_spike.sh" <<'EOF'
#!/usr/bin/env bash
printf 'PASSED fake_spike %s\n' "$*"
EOF
chmod +x "$OUT_DIR/fake_spike.sh"
HYPTEST_SPIKE_BIN="$OUT_DIR/fake_spike.sh" python3 scripts/run_case_coverage_matrix.py \
  --hyptest-repo "$OUT_DIR/fake_hyptest" \
  --target targets/memblock_non_h.json \
  --build-dir "$OUT_DIR/fake_build" \
  --all-elves \
  --case-regex probe_b \
  --limit 1 \
  --skip-gcov \
  --out-dir "$OUT_DIR/case_matrix_default_runner" > "$OUT_DIR/case_matrix_default_runner.stdout"
grep -q "runner=PASS" "$OUT_DIR/case_matrix_default_runner.stdout"
grep -q "ai_probe_b" "$OUT_DIR/case_matrix_default_runner/summary.md"
grep -q "fake_spike --isa=" "$OUT_DIR/case_matrix_default_runner/cases/0001_ai_probe_b/run.log"

echo "smoke tests ok: $OUT_DIR"
