# Spike Coverage Testpoint Skill

把 Spike 的 gcov 覆盖率缺口转成 hyptest 测试点规划。

核心分工：

- 脚本负责快速找证据：哪些文件、函数、源码行、branch、call 没覆盖或覆盖少。
- agent 负责做判断：这些缺口对应什么架构场景，是否值得补，怎么设计可自检测试点。

## 目录

- `SKILL.md`: Codex skill 主说明。
- `targets/`: 覆盖率分析目标配置。具体规格、范围和排除项放这里。
- `scripts/analyze_spike_gcov.py`: 解析 `gcov -b -c` summary，按 target 维度排序覆盖缺口，并标出 `entry` / `shared-path` / `mixed` 证据类型。
- `scripts/inspect_gcov_lines.py`: 精查 `.gcov`，提取 `#####`、未执行 branch/call、源码上下文，并报告被过滤掉的函数/事件数量。
- `scripts/build_handoff_packet.py`: 根据 summary/line JSON 生成 hyptest-workflow 交接包骨架，包含 profile/gate 待确认字段。
- `scripts/compare_gcov_snapshots.py`: 比较单 case 前后 `.gcov` 快照，报告函数上下文、计数增加、计数下降、counter 格式、before/after 缺失文件和缺失事件。
- `scripts/run_case_coverage_matrix.py`: 按 `get_result.py` 类似方式选 ELF，一条条跑 coverage Spike，给每个 case 生成 before/after `.gcov`、compare 结果和最终矩阵报告。
- `scripts/analyze_path_markers.py`: 解析 coverage Spike path-marker 日志，报告 marker 序列是否出现；带 pc+insn、seq 或 access_id 的 JSONL 是强相关证据，弱 JSON/text fallback 会降级。
- `scripts/check_handoff_final.py`: 检查报告/交接包里是否残留裸 `TODO(agent)`，也可用 strict 模式检查 handoff 字段完整性。
- `scripts/run_smoke_tests.sh`: 改 skill 后的脚本级回归 smoke。
- `scripts/validate_target.py`: 校验 target JSON 结构和正则。
- `evals/`: skill 评估用例。

## 快速使用

### 什么情况用

当你想从 Spike 覆盖率反推“还应该补哪些 hyptest 测试点”时，用这个 skill。

典型场景：

- 看某次 Spike gcov 覆盖率哪里没跑到。
- 只分析某个目标，比如 MemBlock、frontend、AMO、vector load/store。
- 根据低 line/branch/call coverage 设计高质量测试点。
- 判断某个执行场景/执行流是否真的跑过，而不是只看每个分支是否分别覆盖。
- 做单 case 增量覆盖确认，或设计 coverage Spike 的路径标记插桩。
- 把覆盖率证据整理成交给 `hyptest-workflow` 的测试点计划。

不适合直接用它做的事：

- 分析 FAILED/timeout/mismatch 日志：用 failure triage。
- 直接写 hyptest case、改 `test_register.c`：分析完后再交给 `hyptest-workflow`。

### 怎么 prompt

最常用的方式是直接告诉 Codex：目标、覆盖率文件、是否要排除什么、输出要计划还是交接包。

通用模板：

```text
用 spike-coverage-testpoint 分析 Spike 覆盖率。
目标：<使用哪个 targets/*.json；如果没有就从 targets/TEMPLATE.json 新建>。
覆盖率输入：<gcov summary / .gcov 目录 / coverage HTML 路径>。
范围：<只看哪些模块/维度/文件/函数；要排除什么>。
输出：<测试点规划 / hyptest-workflow handoff packet / 只建 target>。
约束：<不要写 case / 不改 hyptest 文件 / 不包含 H 扩展 / 需要 path-aware 结论等>。
```

#### 1. 分析 MemBlock non-H 覆盖率

```text
用 spike-coverage-testpoint 分析 Spike 覆盖率。
目标用 /nfs/home/wuyuanlong/.agents/skills/spike-coverage-testpoint/targets/memblock_non_h.json。
coverage summary 用 /nfs/home/wuyuanlong/workspace/offical-spike-coverage/cov_doc/gcov_raw/gcov_memblock_non_h_summary.txt。
只要测试点规划，不要写 case。
重点看哪些 MemBlock 相关代码、函数、分支、call 没覆盖或覆盖少，并给出值得补的高质量 hyptest 测试点。
```

#### 2. 只看某一类缺口

```text
用 spike-coverage-testpoint 看 MemBlock non-H 覆盖率里 vector whole/mask 和 vector indexed 的缺口。
请读取 summary 和对应 .gcov，说明哪些 entry/branch/call 没覆盖，
再判断应该补哪些测试点、observable 是什么、是否需要特殊 profile。
不要写 case。
```

```text
用 spike-coverage-testpoint 只分析 AMO/AMOCAS 覆盖率缺口。
要区分 entry 覆盖和 MMU.amo / amo_compare_and_swap 语义覆盖。
最后给 hyptest-workflow handoff packet。
```

#### 3. 换一个分析目标

```text
我要分析 Spike frontend 覆盖率，不是 MemBlock。
请从 targets/TEMPLATE.json 新建一个 target，
把我要测的 scope/spec/exclusion/dimensions 都放 target 文件里，
不要写死进 SKILL.md 或脚本。
先只建 target 并解释怎么用，不要分析覆盖率。
```

#### 4. 已经有候选，准备交接

```text
根据刚才的 Spike 覆盖率候选，生成 hyptest-workflow 交接包。
每个候选要包含 coverage evidence、source/gcov evidence、target_semantic、
expected observable、duplicate search terms、gate note。
不要改任何 hyptest 文件。
```

#### 5. 判断某条执行流有没有跑过

```text
用 spike-coverage-testpoint 做 path-aware 分析。
目标用 targets/memblock_non_h.json。
场景是：<用自然语言写清目标执行流，不要先枚举组合矩阵>。
请先用 gcov/source 找这条路径的 must-pass line/branch/call evidence，
再判断是 confirmed-not-executed、counter-increment-observed、
single-case-increment-confirmed、edge-covered-path-unknown，还是 needs-path-instrumentation。
不要写 case。
```

#### 6. 单 case 增量覆盖确认

```text
用 spike-coverage-testpoint 对一个单 case 做增量覆盖确认。
before gcov 目录：<before_gcov_dir>。
after gcov 目录：<after_gcov_dir>。
目标用 targets/memblock_non_h.json。
重点文件：mmu.cc.gcov、mmu.h.gcov、v_ext_macros.h.gcov。
请判断目标执行流的必经 line/branch/call 有没有从 0 变非 0 或计数增加，
并给 path_confidence；如果缺少单 case 隔离证据或 Spike log/PC 证据，只能标 counter-increment-observed。
如果 branch/call 是百分比格式而不是 numeric count，请标 not-comparable-counter-format，不能正向确认路径。
```

#### 7. 一键逐条跑 case 并生成覆盖率矩阵

```text
用 spike-coverage-testpoint 一条条跑 MemBlock non-H 的 coverage Spike 覆盖率。
目标用 targets/memblock_non_h.json。
coverage Spike 用 /nfs/home/wuyuanlong/workspace/offical-spike-coverage/build-cov/spike。
hyptest repo 用 /nfs/home/wuyuanlong/workspace/riscv-hyp-tests-nhv5.1。
先跑 case_elf_asm/spike 里前 20 个 ELF，每个 case 独立 reset gcda、生成 before/after gcov、compare，并输出最终 summary。
跑完后请 agent 根据报告分析哪些 case 对目标路径有增量、哪些证据还不够，不要直接写 case。
```

跑完全部 ELF 后分析要补哪些测试场景：

```text
用 spike-coverage-testpoint 跑完 MemBlock non-H 全部 Spike ELF。
目标用 targets/memblock_non_h.json。
coverage Spike 用 /nfs/home/wuyuanlong/workspace/offical-spike-coverage/build-cov/spike。
hyptest repo 用 /nfs/home/wuyuanlong/workspace/riscv-hyp-tests-nhv5.1。
请顺序逐条跑 case_elf_asm/spike 下所有 mapped ELF，每个 case 独立 reset gcda、生成 before/after gcov、compare，输出 summary.md/summary.json。
跑完后请根据 summary.json、top still-zero、entry/header movement、runner issues、scope warnings 和 Spike 源码，归纳还需要补哪些高价值测试场景/测试点。
只做测试点规划和 hyptest-workflow handoff，不要直接写 case。
```

只跑选中的 case：

```text
用 spike-coverage-testpoint 逐条跑这些 case 的 coverage matrix：
ai_xxx、ai_yyy、ai_zzz。
目标用 targets/memblock_non_h.json，只收集证据和最终报告。
```

#### 8. 路径标记插桩设计或分析

```text
用 spike-coverage-testpoint 给 coverage Spike 设计 MemBlock path marker 插桩。
目标用 targets/memblock_non_h.json。
场景是：<具体执行流>。
请从 target 的 path_analysis.path_markers 里选 marker，
说明建议插在哪些 Spike 源码函数/分支，输出 JSONL marker 格式，
以及如何用 analyze_path_markers.py 判断 marker 序列有没有出现；带 pc+insn、seq 或 access_id 的强 JSONL 结果是 marker-sequence-observed，弱 JSON/text fallback 只能算弱证据。
不要改普通 Spike 行为。
```

#### 9. 要真正写 case

先用本 skill 得到测试点计划。然后再说：

```text
根据上面的 handoff packet，用 hyptest-workflow 写前 2 个 case，
做查重、选位置、更新 test_point/test_register.c、编译并跑 spike。
```

## 输出应该长什么样

所有分析任务都要有 `.md` 产物留档，不能只停在终端输出。脚本证据报告和 agent 最终分析报告都应该放在明确路径下。

每个 `.md` 至少要有：

- `Conclusion`: 当前覆盖率结论，哪些地方最缺，哪些证据能/不能用。
- `Data`: target、输入路径、case 数、runner 状态、覆盖计数等数据。
- `Evidence`: 具体 `.gcov`、函数、源码行、branch/call、case log、compare 文件。
- `Limits / Next steps`: 不能证明什么，下一步要 inspect、单 case 增量、path marker，还是交给 `hyptest-workflow`。

默认输出路径规则：

```text
正式 md 报告：
/nfs/home/wuyuanlong/workspace/offical-spike-coverage/cov_doc/reports/<target_name>/<run_tag>/

正式运行证据：
/nfs/home/wuyuanlong/workspace/offical-spike-coverage/cov_runs/<target_name>/<run_tag>/

临时试跑：
/tmp/spike_cov_<target_name>_<purpose>/
```

除非 prompt 明确指定固定输出路径，否则 agent 自己按上面规则选最佳路径。
`target_name` 来自 target JSON 的 `name` 字段，例如 `memblock_non_h`。
`run_tag` 用日期加目的，例如 `20260521_current`、`20260521_all_cases`、
`20260521_after_new_mem_cases`。不要把运行结果放在 skill 目录里；skill
目录只保存工具、target、reference 和 README。

推荐文件名：

```text
summary.md          总体覆盖率结论和排名
line.md             行/分支/call 证据
compare.md          单 case 增量覆盖证据
path_markers.md     path marker 序列证据
handoff.md          给 hyptest-workflow 的交接证据包
testpoint_plan.md   agent 最终测试点分析报告
```

一次好的分析应该至少包含：

- 覆盖率输入：target、summary、gcov 目录。
- 高优先级缺口：按维度排序，带 line/branch/call/0% entry 证据，包含 low-line/low-branch/low-call entry。
- target entry 完整性：`missing_entries_by_dimension` 用来区分“目标里写了但本次 gcov snapshot 没出现”和“出现了但 0%”。
- 行级证据：具体 `.gcov` 文件、源码行、函数、miss kind。
- 行级证据状态：`line_evidence_status`，特别注意 `exact-instruction-entry-evidence`、`weak-inspection-hint-only`、`no-line-evidence-from-requested-files`、`unreviewed-missing-files`。
- 证据类型：`entry`、`shared-path` 或 `mixed`；`mixed` 需要继续看共享源码，避免把指令入口覆盖当成共享语义路径覆盖。
- 同一执行流证据：`same_flow_evidence`。`aggregate-only` 只能说明套件里分别覆盖过边，不能说明一条指令/一次访问跑过完整路径。
- 单 case 矩阵证据用途：`evidence_use`。`no-execution-evidence` 不能当覆盖率证据；`diagnostic-only-nonpass-counter-movement` 只能辅助定位；`pass-counter-evidence-needs-source-pc-review` 仍需源码/PC/must-pass 复核；`pass-counter-evidence-scope-review-required` 先做 target scope 判断。
- 路径置信度：`confirmed-not-executed`、`counter-increment-observed`、`single-case-increment-confirmed`、`edge-covered-path-unknown`、`needs-path-instrumentation` 或 `out-of-scope`。
- 路径签名：从 Spike 源码和 `.gcov` 证据反推的目标入口、共享函数路径、must-pass 证据点、源码证明的条件、observable、剩余不确定性。
- 测试点候选：missing scenario、test idea、observable、gate note。
- profile/gate 判断：`extension_required`、`current_profile_evidence`、`default_gate_eligible`、`profile_gate_note`。
- 维度 gate 判断：`dimension_gate`，manual-only 或 `default_gate_allowed=false` 的维度只能作为 manual/special-run，除非先改 target/profile 决策。
- 查重提示：应该在 hyptest 里搜哪些关键词。
- handoff packet：后续交给 `hyptest-workflow` 写 case。

## 高级：手动跑脚本

通常不需要用户手动跑脚本，直接 prompt Codex 即可。需要复现或调试时可以这样跑。
如果不是临时试跑，先设定正式报告和运行证据目录：

```bash
REPORT_DIR=/nfs/home/wuyuanlong/workspace/offical-spike-coverage/cov_doc/reports/memblock_non_h/20260521_current
RUN_DIR=/nfs/home/wuyuanlong/workspace/offical-spike-coverage/cov_runs/memblock_non_h/20260521_current
mkdir -p "$REPORT_DIR" "$RUN_DIR"
```

校验 target：

```bash
python3 scripts/validate_target.py targets/memblock_non_h.json
```

跑 summary：

```bash
python3 scripts/analyze_spike_gcov.py \
  --summary /nfs/home/wuyuanlong/workspace/offical-spike-coverage/cov_doc/gcov_raw/gcov_memblock_non_h_summary.txt \
  --target targets/memblock_non_h.json \
  --top 18 \
  --json-out "$RUN_DIR/summary.json" \
  --markdown-out "$REPORT_DIR/summary.md"
```

精查 `.gcov`：

```bash
python3 scripts/inspect_gcov_lines.py \
  --gcov-dir /nfs/home/wuyuanlong/workspace/offical-spike-coverage/cov_doc/gcov_raw \
  --source-root /nfs/home/wuyuanlong/workspace/offical-spike-coverage \
  --target targets/memblock_non_h.json \
  --file mmu.cc.gcov \
  --file mmu.h.gcov \
  --file v_ext_macros.h.gcov \
  --context 4 \
  --json-out "$RUN_DIR/line.json" \
  --markdown-out "$REPORT_DIR/line.md"
```

生成交接包骨架：

```bash
python3 scripts/build_handoff_packet.py \
  --summary-json "$RUN_DIR/summary.json" \
  --inspect-json "$RUN_DIR/line.json" \
  --top 8 \
  --markdown-out "$REPORT_DIR/handoff.md"
```

最终回答前检查是否还残留裸 TODO：

```bash
python3 scripts/check_handoff_final.py --strict-handoff "$REPORT_DIR/handoff.md"
```

如果是最终要贴给用户的完成版报告，再加严格检查，避免保留通用 skeleton 字段：

```bash
python3 scripts/check_handoff_final.py --strict-final-report "$REPORT_DIR/final_report.md"
```

比较单 case 前后 `.gcov` 快照：

```bash
python3 scripts/compare_gcov_snapshots.py \
  --before-dir /tmp/before_gcov \
  --after-dir /tmp/after_gcov \
  --target targets/memblock_non_h.json \
  --file mmu.cc.gcov \
  --file mmu.h.gcov \
  --file v_ext_macros.h.gcov \
  --require-event mmu.cc.gcov:branch:1234:0 \
  --json-out "$RUN_DIR/compare.json" \
  --markdown-out "$REPORT_DIR/compare.md"
```

一键逐条跑 ELF 并生成最终 coverage matrix：

```bash
HYPTEST_SPIKE_BIN=/nfs/home/wuyuanlong/workspace/offical-spike-coverage/build-cov/spike \
python3 scripts/run_case_coverage_matrix.py \
  --hyptest-repo /nfs/home/wuyuanlong/workspace/riscv-hyp-tests-nhv5.1 \
  --target targets/memblock_non_h.json \
  --build-dir /nfs/home/wuyuanlong/workspace/offical-spike-coverage/build-cov \
  --elf-dir /nfs/home/wuyuanlong/workspace/riscv-hyp-tests-nhv5.1/case_elf_asm/spike \
  --all-elves \
  --limit 20 \
  --gcno-from-target \
  --out-dir "$RUN_DIR/case_matrix_20"
```

全量跑完所有 mapped ELF：

```bash
HYPTEST_SPIKE_BIN=/nfs/home/wuyuanlong/workspace/offical-spike-coverage/build-cov/spike \
python3 scripts/run_case_coverage_matrix.py \
  --hyptest-repo /nfs/home/wuyuanlong/workspace/riscv-hyp-tests-nhv5.1 \
  --target targets/memblock_non_h.json \
  --build-dir /nfs/home/wuyuanlong/workspace/offical-spike-coverage/build-cov \
  --elf-dir /nfs/home/wuyuanlong/workspace/riscv-hyp-tests-nhv5.1/case_elf_asm/spike \
  --all-elves \
  --gcno-from-target \
  --out-dir "$RUN_DIR/case_matrix_all"
```

只跑名字像 MemBlock/访存相关的 ELF，适合先收一版更聚焦的证据：

```bash
HYPTEST_SPIKE_BIN=/nfs/home/wuyuanlong/workspace/offical-spike-coverage/build-cov/spike \
python3 scripts/run_case_coverage_matrix.py \
  --hyptest-repo /nfs/home/wuyuanlong/workspace/riscv-hyp-tests-nhv5.1 \
  --target targets/memblock_non_h.json \
  --build-dir /nfs/home/wuyuanlong/workspace/offical-spike-coverage/build-cov \
  --elf-dir /nfs/home/wuyuanlong/workspace/riscv-hyp-tests-nhv5.1/case_elf_asm/spike \
  --all-elves \
  --case-regex 'memblock|pbmt|pte|pmp|pma|amo|lr|sc|load|store|vector|trigger|fault|unaligned|misalign' \
  --gcno-from-target \
  --out-dir "$RUN_DIR/case_matrix_filtered"
```

只跑指定 case：

```bash
HYPTEST_SPIKE_BIN=/nfs/home/wuyuanlong/workspace/offical-spike-coverage/build-cov/spike \
python3 scripts/run_case_coverage_matrix.py \
  --hyptest-repo /nfs/home/wuyuanlong/workspace/riscv-hyp-tests-nhv5.1 \
  --target targets/memblock_non_h.json \
  --build-dir /nfs/home/wuyuanlong/workspace/offical-spike-coverage/build-cov \
  --case ai_case_a \
  --case ai_case_b \
  --gcno-from-target \
  --out-dir "$RUN_DIR/case_matrix_selected"
```

常用选项：

- `--limit N`: 从已选 case 里只跑前 N 个，适合先试跑。
- `--case-regex REGEX`: 从已选 case 里再按名字过滤，例如 `--case-regex '^(addr_unaligned|ai_micro_memblock)'`，避免 `--all-elves --limit 3` 先跑到非目标 case。
- `--case-list file`: 从文件读 case 名或 ELF 路径。
- `--dimension vector`: 只用 target 里名称包含 `vector` 的 inspection hints 解析 `.gcno`。
- `--requirements-json req.json` / `--requirements-dir dir`: 给 compare 加 must-pass line/branch/call 证据点。
- `--reset-scope selected|all|none`: 每个 case 前删除哪些 `.gcda` counter；默认 `selected`。
- `--dry-run`: 只看会选哪些 case 和 `.gcno`，不运行。
- `--command-template`: 支持 `{spike_bin}`、`{elf}`、`{case_name}`、`{run_name}`、`{case_dir}` 等占位符；需要 Spike commit/log 证据时可把 `--log={case_dir}/spike.log` 写进去。默认模板直接执行 `{spike_bin}`，不经过 `bash -lc`，避免 login shell 覆盖临时 `HYPTEST_SPIKE_BIN`。

输出文件：

- `summary.md`: 最终人工可读报告。
- `summary.json`: 机器可读矩阵。
- `cases/<idx>_<case>/run.log`: 单 case Spike 输出。
- `cases/<idx>_<case>/before_gcov` / `after_gcov`: 单 case 前后 `.gcov` 快照。
- `cases/<idx>_<case>/compare.md` / `compare.json`: 单 case 增量覆盖证据。

全量跑完后，下一步让 agent 分析补点时直接给这类 prompt：

```text
用 spike-coverage-testpoint 分析 $RUN_DIR/case_matrix_all/summary.json 和 summary.md。
目标仍然是 targets/memblock_non_h.json。
请只把 PASS 且 in-scope 的 counter movement 当正向覆盖线索；
MISSING_ELF、RUNNER_ERROR、MARKER_MISMATCH、TIMEOUT 只能作为诊断线索；
`pass-counter-evidence-scope-review-required` 先按 target scope 判断，不要直接算 MemBlock non-H 正向证据。
请结合 Spike 源码和 .gcov still-zero/entry/header movement，输出还缺哪些高质量测试场景、测试点、observable、gate note 和 hyptest-workflow handoff。
请把最终分析保存成 $REPORT_DIR/testpoint_plan.md，报告必须包含 Conclusion、Data、Evidence、Limits / Next steps，并在 Data/Evidence 里链接 $RUN_DIR/case_matrix_all。
不要直接写 case。
```

`summary.md` 会额外折叠两类快速定位信息：

- Runner issues：FAILED/MARKER_MISMATCH/TIMEOUT 的 marker、断言位置和错误摘要。
- Missing ELF diagnostics：显式 `--case` 找不到 ELF 时，会在 run.log/summary 里列出 missing path 和相似 case 建议，方便修正 case 名或 artifact 映射。
- Evidence use：每个 case 会标 `evidence_use`。缺 ELF 不生成 before/after compare；非 PASS 但计数移动只算 diagnostic-only；PASS 但命中 target `scope_out` 会标成 scope-review-required。
- Target scope warnings：case 虽然 PASS，但 run.log 命中 target `scope_out` 关键词时会提醒，例如 MemBlock non-H target 下日志出现 HS/VS/VU、stage2、guest page fault、H 扩展指令名等。
- Per-case coverage highlights：每个 case 主要新增覆盖/仍为 0 的 top Spike `.gcov` 文件，优先按 target 的 inspection/source-priority 排序，默认展示前 8 个，`l/b/c` 分别表示 line/branch/call event 数量。它还会单独列出 entry/header movement 和仍为 0 的 entry/header；若 case 名里包含对应指令入口，比如 `amoand_d`，该入口会优先展示，避免被共享文件淹没。

注意：这个脚本默认顺序执行，不做并行。`.gcda` counter 是共享状态，并行跑会污染单 case 增量证据。

同一条访问/指令的 marker 如果分多条 JSON 记录输出，用相关字段聚合：

```bash
python3 scripts/analyze_path_markers.py \
  --log /tmp/path_markers.jsonl \
  --require mem.access.scalar_load \
  --require mem.translate.tlb_miss_walk \
  --require mem.fault.page \
  --ordered \
  --group-by access_id \
  --markdown-out "$REPORT_DIR/path_markers_grouped.md"
```

解析 path marker 日志：

```bash
python3 scripts/analyze_path_markers.py \
  --log /tmp/spike_mem_path_cov.jsonl \
  --require mem.access.scalar_load \
  --require mem.translate.tlb_miss_walk \
  --require mem.fault.page \
  --ordered \
  --markdown-out "$REPORT_DIR/path_markers.md"
```

改 skill 或脚本后跑 smoke：

```bash
bash scripts/run_smoke_tests.sh
```

## 目标配置

不要把具体规格写死在 `SKILL.md` 或脚本里。要换分析目标时，从 `targets/TEMPLATE.json` 复制一个新 target，填写：

- `spec`
- `scope_in`
- `scope_out`
- `dimensions`
- `path_analysis`：可选。证据策略、路径报告字段 checklist、路径置信度、单 case 增量规则、path marker 词表。它不是完整路径矩阵。
- `inspection_hints`
- `duplicate_search_terms`

当前已有目标：`targets/memblock_non_h.json`。

## 注意

- 覆盖率只是证据，不是测试意图。
- `insns/*.h` 入口覆盖只能说明指令入口有没有跑到，语义仍要结合共享路径源码判断。
- branch/call 覆盖是聚合边计数，不等于完整路径覆盖；同一条执行流需要单 case 增量证据或 path marker 证据。
- `single-case-increment-confirmed` 要求：单 case 隔离、目标 PC/指令证据、所有 must-pass counters 增加，branch/call 使用 numeric count 快照，并且没有 missing/decreased/not-comparable 事件；否则降级为 `counter-increment-observed` 或 `edge-covered-path-unknown`。
- path marker 脚本的 `marker-sequence-observed` 只说明 marker 序列在 JSON per-instruction/access 记录里出现，最终路径结论仍要检查插桩位置和架构 observable。
- 没有 pc+insn、seq 或 access_id 的 JSON marker 记录会降级为 `json-marker-sequence-observed-weak`。
- 默认 gate 测试点必须先做 profile/gate 判断；0% entry 可能只是 ISA/profile 没打开，不一定值得写默认用例。
- target 可用 `special_run_scope`、`manual_only_dimensions`、`dimension_metadata` 标记 manual/special-run 维度。
- `XSError/cache error/NMI` 这类需要特殊注入的 MemBlock 路径已放在 `memblock_non_h.json` 的 `micro cache error/NMI paths`，默认按 manual/special-run 处理。
- 不要从 target 里的字段枚举“理论组合”来生成测试点；必须从 Spike 源码、`.gcov`、单 case 增量或 marker 记录反推真实路径。
- 生成 case、修改 `test_point`、注册 `test_register.c` 时，应切到 `hyptest-workflow` skill。
