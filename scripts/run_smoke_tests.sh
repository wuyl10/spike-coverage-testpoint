#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="${HYPTEST_SPIKE_COV_SMOKE_OUT:-${TMPDIR:-/tmp}/spike_cov_skill_smoke}"
EXTERNAL_SMOKE="${HYPTEST_SPIKE_COV_EXTERNAL_SMOKE:-0}"
SUMMARY="${SPIKE_COV_SUMMARY:-}"
GCOV_RAW="${SPIKE_GCOV_RAW:-}"
SOURCE_ROOT="${SPIKE_SOURCE_ROOT:-}"
if [[ -n "${HYPTEST_SPIKE_COV:-}" ]]; then
  GCOV_RAW="${GCOV_RAW:-$HYPTEST_SPIKE_COV/cov_doc/gcov_raw}"
  SOURCE_ROOT="${SOURCE_ROOT:-$HYPTEST_SPIKE_COV}"
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

require_report_sections() {
  local report="$1"
  grep -q "## 结论" "$report"
  grep -q "## 数据" "$report"
  grep -q "## 证据" "$report"
  grep -q "## 限制与下一步" "$report"
}

python3 scripts/validate_target.py targets/TEMPLATE.json
python3 scripts/validate_target.py targets/memblock_non_h.json
python3 -m py_compile scripts/*.py
python3 -m json.tool specs/TEMPLATE.json >/dev/null
python3 -m json.tool specs/nanhu_v5_1_ap.json >/dev/null
python3 -m json.tool targets/TEMPLATE.json >/dev/null
python3 -m json.tool targets/memblock_non_h.json >/dev/null
python3 -m json.tool evals/evals.json >/dev/null

cat > "$OUT_DIR/memblock_portable_summary.txt" <<'EOF'
File 'riscv/mmu.cc'
Lines executed:5.00% of 100
Branches executed:0.00% of 20
Calls executed:0.00% of 5
Creating 'mmu.cc.gcov'
File 'riscv/mmu.h'
Lines executed:15.00% of 40
Branches executed:5.00% of 10
Calls executed:0.00% of 2
Creating 'mmu.h.gcov'
File 'riscv/insns/lw.h'
Lines executed:0.00% of 4
Branches executed:0.00% of 1
Calls executed:0.00% of 1
Creating 'lw.h.gcov'
EOF
python3 scripts/analyze_spike_gcov.py \
  --summary "$OUT_DIR/memblock_portable_summary.txt" \
  --target targets/memblock_non_h.json \
  --top 3 \
  --json-out "$OUT_DIR/summary.json" \
  --markdown-out "$OUT_DIR/summary.md"
grep -q "入口/共享路径混合缺口排序" "$OUT_DIR/summary.md"
grep -q "cross 场景证据缺口" "$OUT_DIR/summary.md"
grep -q "待解析 cross 场景" "$OUT_DIR/summary.md"
grep -q "cross 场景轴 checklist" "$OUT_DIR/summary.md"
grep -q "类型原因" "$OUT_DIR/summary.md"
grep -q "低调用覆盖入口" "$OUT_DIR/summary.md"
require_report_sections "$OUT_DIR/summary.md"

cat > "$OUT_DIR/synthetic_target.json" <<'EOF'
{
  "name": "synthetic",
  "title": "Synthetic coverage target",
  "description": "Smoke fixture for focus/gate/call gaps",
  "project_spec": "specs/nanhu_v5_1_ap.json",
  "coverage_focus": {
    "profile": "synthetic",
    "purpose": "Smoke fixture coverage slice",
    "included_features": [],
    "excluded_features": []
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
  "scenario_coverage": {
    "purpose": "Smoke fixture for cross scenario evidence fields",
    "scenario_axes": [
      "instruction/access class",
      "privilege/profile/gate",
      "address/translation/protection/device condition",
      "exception/fault/trigger/cache/vector/atomic subcondition",
      "architectural observable"
    ],
    "evidence_policy": [
      "Line/branch/call coverage is supporting evidence, not the scenario itself.",
      "Do not generate a blind Cartesian product."
    ],
    "priority_scenarios": []
  },
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
  --markdown-out "$OUT_DIR/synth_summary.md"
grep -q "manual device path" "$OUT_DIR/synth_summary.md"
grep -q "低调用覆盖入口" "$OUT_DIR/synth_summary.md"
grep -q "manual/special-run synthetic gate" "$OUT_DIR/synth_summary.md"
grep -q "target 中存在但快照缺失的入口" "$OUT_DIR/synth_summary.md"
python3 scripts/inspect_gcov_lines.py \
  --gcov-dir "$OUT_DIR" \
  --source-root "$OUT_DIR" \
  --target "$OUT_DIR/synthetic_target.json" \
  --file mmu.cc.gcov \
  --json-out "$OUT_DIR/synth_line.json" \
  --markdown-out "$OUT_DIR/synth_line.md"
grep -q "ordinals=branch-taken-0:2, call-never:0" "$OUT_DIR/synth_line.md"
require_report_sections "$OUT_DIR/synth_line.md"
python3 scripts/build_handoff_packet.py \
  --summary-json "$OUT_DIR/synth_summary.json" \
  --inspect-json "$OUT_DIR/synth_line.json" \
  --select nmi \
  --top 1 \
  --markdown-out "$OUT_DIR/synth_handoff.md"
grep -q "dimension_gate" "$OUT_DIR/synth_handoff.md"
grep -q "scenario_coverage_gap" "$OUT_DIR/synth_handoff.md"
grep -q "cross_scenario_signature" "$OUT_DIR/synth_handoff.md"
grep -q "coverage_evidence_role" "$OUT_DIR/synth_handoff.md"
grep -q "target_scenario_axes" "$OUT_DIR/synth_handoff.md"
grep -q "default_gate_eligible: no - target dimension is manual/special-run" "$OUT_DIR/synth_handoff.md"
grep -q "low_call_entries" "$OUT_DIR/synth_handoff.md"
grep -q "same_flow_evidence" "$OUT_DIR/synth_handoff.md"
grep -q "aggregate-only" "$OUT_DIR/synth_handoff.md"
grep -q "basis: summary-low-branch-or-call" "$OUT_DIR/synth_handoff.md"
grep -q "missing_entries" "$OUT_DIR/synth_handoff.md"
require_report_sections "$OUT_DIR/synth_handoff.md"

if [[ "$EXTERNAL_SMOKE" == "1" ]]; then
  : "${SUMMARY:?set SPIKE_COV_SUMMARY to a concrete target summary file when HYPTEST_SPIKE_COV_EXTERNAL_SMOKE=1}"
  : "${GCOV_RAW:?set HYPTEST_SPIKE_COV or SPIKE_GCOV_RAW when HYPTEST_SPIKE_COV_EXTERNAL_SMOKE=1}"
  : "${SOURCE_ROOT:?set HYPTEST_SPIKE_COV or SPIKE_SOURCE_ROOT when HYPTEST_SPIKE_COV_EXTERNAL_SMOKE=1}"

  python3 scripts/analyze_spike_gcov.py \
    --summary "$SUMMARY" \
    --target targets/memblock_non_h.json \
    --top 3 \
    --json-out "$OUT_DIR/external_summary.json" \
    --markdown-out "$OUT_DIR/external_summary.md"
  require_report_sections "$OUT_DIR/external_summary.md"

  python3 scripts/inspect_gcov_lines.py \
    --gcov-dir "$GCOV_RAW" \
    --source-root "$SOURCE_ROOT" \
    --target targets/memblock_non_h.json \
    --file mmu.cc.gcov \
    --context 2 \
    --max-functions 2 \
    --json-out "$OUT_DIR/external_line.json" \
    --markdown-out "$OUT_DIR/external_line.md"
  require_report_sections "$OUT_DIR/external_line.md"

  python3 scripts/build_handoff_packet.py \
    --summary-json "$OUT_DIR/external_summary.json" \
    --inspect-json "$OUT_DIR/external_line.json" \
    --top 1 \
    --markdown-out "$OUT_DIR/external_handoff.md"
  require_report_sections "$OUT_DIR/external_handoff.md"
  python3 scripts/check_handoff_final.py --strict-handoff "$OUT_DIR/external_handoff.md"
fi

cat > "$OUT_DIR/bad_default_gate.md" <<'EOF'
evidence_class: shared-path
scenario_coverage_gap: in-scope scalar load PMP deny
cross_scenario_signature:
  instruction_or_access_class: scalar load
coverage_evidence_role: supporting evidence only
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
scenario_coverage_gap: in-scope scalar load PMP deny
cross_scenario_signature:
  instruction_or_access_class: scalar load
coverage_evidence_role: supporting evidence only
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
scenario_coverage_gap: needs source confirmation: map coverage evidence to the missing architecture-visible cross execution scenario
cross_scenario_signature:
  instruction_or_access_class: needs source confirmation: derive from coverage dimension, representative entries, and inspected Spike source
coverage_evidence_role: supporting evidence only
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
scenario_coverage_gap: in-scope scalar load PMP deny
cross_scenario_signature:
  instruction_or_access_class: scalar load
coverage_evidence_role: supporting evidence only
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
  --markdown-out "$OUT_DIR/marker_strong.md"
grep -q "marker-sequence-observed" "$OUT_DIR/marker_strong.md"
require_report_sections "$OUT_DIR/marker_strong.md"

cat > "$OUT_DIR/marker_weak.jsonl" <<'EOF'
{"markers":["mem.access.scalar_load","mem.translate.tlb_miss_walk","mem.fault.page"]}
EOF
python3 scripts/analyze_path_markers.py \
  --log "$OUT_DIR/marker_weak.jsonl" \
  --require mem.access.scalar_load \
  --require mem.translate.tlb_miss_walk \
  --require mem.fault.page \
  --ordered \
  --markdown-out "$OUT_DIR/marker_weak.md"
grep -q "json-marker-sequence-observed-weak" "$OUT_DIR/marker_weak.md"
grep -q "弱 JSON" "$OUT_DIR/marker_weak.md"
require_report_sections "$OUT_DIR/marker_weak.md"
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
  --markdown-out "$OUT_DIR/marker_grouped.md"
grep -q "grouped-by-access_id-ordered-subsequence" "$OUT_DIR/marker_grouped.md"
grep -q "marker-sequence-observed" "$OUT_DIR/marker_grouped.md"
require_report_sections "$OUT_DIR/marker_grouped.md"

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
  --markdown-out "$OUT_DIR/compare.md" \
  --limit 20
grep -q "key_mode: \`stable-line\`" "$OUT_DIR/compare.md"
grep -q "decreased-or-reset" "$OUT_DIR/compare.md"
grep -q "missing-after-event" "$OUT_DIR/compare.md"
grep -q "counter 格式" "$OUT_DIR/compare.md"
grep -q "必需证据点" "$OUT_DIR/compare.md"
grep -q "all_required_passed: False" "$OUT_DIR/compare.md"
require_report_sections "$OUT_DIR/compare.md"

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
  --markdown-out "$OUT_DIR/compare_percent.md" \
  --limit 20
grep -q "not-comparable-counter-format" "$OUT_DIR/compare_percent.md"
grep -q "percent->percent" "$OUT_DIR/compare_percent.md"
require_report_sections "$OUT_DIR/compare_percent.md"

mkdir -p "$OUT_DIR/fake_hyptest/case_elf_asm/spike" "$OUT_DIR/fake_build"
touch "$OUT_DIR/fake_hyptest/case_elf_asm/spike/ai_probe_a.ELF"
touch "$OUT_DIR/fake_hyptest/case_elf_asm/spike/ai_probe_b.ELF"
python3 scripts/run_case_coverage_matrix.py \
  --hyptest-home "$OUT_DIR/fake_hyptest" \
  --target targets/memblock_non_h.json \
  --build-dir "$OUT_DIR/fake_build" \
  --all-elves \
  --limit 1 \
  --skip-gcov \
  --command-template "bash -lc 'echo PASSED {case_name}'" \
  --out-dir "$OUT_DIR/case_matrix_fake" > "$OUT_DIR/case_matrix_fake.stdout"
grep -q "runner=PASS" "$OUT_DIR/case_matrix_fake.stdout"
grep -q "Runner 状态" "$OUT_DIR/case_matrix_fake/summary.md"
grep -q 'command_template: `bash -lc' "$OUT_DIR/case_matrix_fake/summary.md"
grep -q 'command_template_source: `arg:--command-template`' "$OUT_DIR/case_matrix_fake/summary.md"
grep -q "ai_probe_a" "$OUT_DIR/case_matrix_fake/summary.md"
require_report_sections "$OUT_DIR/case_matrix_fake/summary.md"
python3 scripts/run_case_coverage_matrix.py \
  --hyptest-home "$OUT_DIR/fake_hyptest" \
  --target targets/memblock_non_h.json \
  --build-dir "$OUT_DIR/fake_build" \
  --all-elves \
  --limit 1 \
  --gcno-from-target \
  --dry-run \
  --out-dir "$OUT_DIR/case_matrix_dry" > "$OUT_DIR/case_matrix_dry.stdout"
grep -q "dry_run=true" "$OUT_DIR/case_matrix_dry.stdout"
grep -q "selected_case_count=1" "$OUT_DIR/case_matrix_dry.stdout"
grep -q "未解析的 gcno hint" "$OUT_DIR/case_matrix_dry/summary.md"
require_report_sections "$OUT_DIR/case_matrix_dry/summary.md"

cat > "$OUT_DIR/fake_spike.sh" <<'EOF'
#!/usr/bin/env bash
printf 'PASSED fake_spike %s\n' "$*"
EOF
chmod +x "$OUT_DIR/fake_spike.sh"
HYPTEST_SPIKE_COV_BIN="$OUT_DIR/fake_spike.sh" python3 scripts/run_case_coverage_matrix.py \
  --hyptest-home "$OUT_DIR/fake_hyptest" \
  --target targets/memblock_non_h.json \
  --build-dir "$OUT_DIR/fake_build" \
  --all-elves \
  --case-regex probe_b \
  --limit 1 \
  --skip-gcov \
  --out-dir "$OUT_DIR/case_matrix_default_runner" > "$OUT_DIR/case_matrix_default_runner.stdout"
grep -q "runner=PASS" "$OUT_DIR/case_matrix_default_runner.stdout"
grep -q "ai_probe_b" "$OUT_DIR/case_matrix_default_runner/summary.md"
grep -q 'command_template_source: `project_spec:coverage_spike.default_args`' "$OUT_DIR/case_matrix_default_runner/summary.md"
grep -q 'command_template: `{spike_bin} --isa=rv64imafdcv_' "$OUT_DIR/case_matrix_default_runner/summary.md"
if ! grep -q -- "--isa=rv64imafdcv_" "$OUT_DIR/case_matrix_default_runner/cases/0001_ai_probe_b/run.log"; then
  echo "default runner did not use project spec --isa" >&2
  exit 1
fi
grep -q -- "--priv=MSU" "$OUT_DIR/case_matrix_default_runner/cases/0001_ai_probe_b/run.log"
grep -q "fake_spike .*ai_probe_b.ELF" "$OUT_DIR/case_matrix_default_runner/cases/0001_ai_probe_b/run.log"
require_report_sections "$OUT_DIR/case_matrix_default_runner/summary.md"

echo "smoke tests ok: $OUT_DIR"
