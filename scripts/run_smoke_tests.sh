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
python3 scripts/check_handoff_final.py --strict-handoff "$OUT_DIR/handoff.md"

cat > "$OUT_DIR/bad_default_gate.md" <<'EOF'
evidence_class: shared-path
line_evidence_status: exact-entry-evidence
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
line_evidence_status: exact-entry-evidence
path_confidence: confirmed-not-executed
profile_gate:
  default_gate_eligible: yes
expected_observable: memory result
gate_note: default
EOF
python3 scripts/check_handoff_final.py --strict-handoff "$OUT_DIR/good_default_gate.md" >/dev/null

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
  --markdown \
  --limit 20 > "$OUT_DIR/compare.md"
grep -q "key_mode: \`stable-line\`" "$OUT_DIR/compare.md"
grep -q "decreased-or-reset" "$OUT_DIR/compare.md"
grep -q "missing-after-event" "$OUT_DIR/compare.md"
grep -q "counter formats" "$OUT_DIR/compare.md"

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

echo "smoke tests ok: $OUT_DIR"
