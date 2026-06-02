# Spike Coverage Testpoint Skill

把 Spike 的 gcov/path/case-counter 证据转成“未覆盖 cross 执行场景”的 hyptest 测试点规划。

核心分工：

- 脚本负责快速找证据：哪些文件、函数、源码行、branch、call、单 case 计数或 path marker 没覆盖或证据不足。
- agent 负责做判断：这些证据对应哪个 architecture-visible cross 执行场景，是否值得补，怎么设计可自检测试点。

核心目标不是提高行/代码/分支覆盖率数字本身，而是找出哪些 cross 执行场景没跑到。line/branch/call/entry 覆盖只作为定位证据；最终报告必须说清楚缺的场景、场景签名、可观测行为和 same-flow 置信度。

## 目录

- `SKILL.md`: Codex skill 主说明。
- `specs/`: 当前项目实现配置，例如 coverage Spike runner、环境变量接口、源码/覆盖率证据来源。
- `targets/`: 覆盖率分析目标配置。具体看哪块覆盖率、范围、排除项和维度放这里。
- `scripts/analyze_spike_gcov.py`: 解析 `gcov -b -c` summary，按 target 维度排序支撑证据缺口，并标出 `entry` / `shared-path` / `mixed` 证据类型。
- `scripts/inspect_gcov_lines.py`: 精查 `.gcov`，提取 `#####`、未执行 branch/call、源码上下文，并报告被过滤掉的函数/事件数量。
- `scripts/build_handoff_packet.py`: 根据 summary/line JSON 生成 hyptest-workflow 交接包骨架，包含 profile/gate 待确认字段。
- `scripts/compare_gcov_snapshots.py`: 比较单 case 前后 `.gcov` 快照，报告函数上下文、计数增加、计数下降、counter 格式、before/after 缺失文件和缺失事件。
- `scripts/run_case_coverage_matrix.py`: 从 hyptest 已生成的 ELF 里选 case，但不调用 hyptest 编译或普通 Spike runner；它直接用 coverage Spike 一条条跑 ELF，给每个 case 生成 before/after `.gcov`、compare 结果和最终矩阵报告。
- `scripts/analyze_path_markers.py`: 解析 coverage Spike path-marker 日志，报告 marker 序列是否出现；带 pc+insn、seq 或 access_id 的 JSONL 是强相关证据，弱 JSON/text fallback 会降级。
- `scripts/check_handoff_final.py`: 检查报告/交接包里是否残留裸 `TODO(agent)`，也可用 strict 模式检查 handoff 字段完整性。
- `scripts/run_smoke_tests.sh`: 改 skill 后的脚本级回归 smoke。
- `scripts/validate_spec.py`: 校验 project spec JSON，包括 coverage Spike 默认参数、ISA support 状态和 `NO` 行的 unsupported-feature rules。
- `scripts/validate_target.py`: 校验 target JSON 结构和正则。
- `evals/`: skill 评估用例。

## 快速使用

### 什么情况用

当你想从 Spike 覆盖率证据反推“哪些 cross 执行场景没覆盖、还应该补哪些 hyptest 测试点”时，用这个 skill。

典型场景：

- 看某次 Spike gcov 覆盖率哪里没跑到。
- 只分析某个目标，比如 MemBlock、frontend、AMO、vector load/store。
- 根据低 line/branch/call counter 证据定位 cross 场景缺口，并设计高质量测试点。
- 判断某个 cross 执行场景/执行流是否真的跑过，而不是只看每个分支是否分别覆盖。
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
项目实现：<使用哪个 specs/*.json；通常由 target.project_spec 指向>。
目标：<使用哪个 targets/*.json；如果没有就从 targets/TEMPLATE.json 新建>。
覆盖率输入：<gcov summary / .gcov 目录 / coverage HTML 路径>。
范围：<只看哪些模块/维度/文件/函数；要排除什么>。
输出：<测试点规划 / hyptest-workflow handoff packet / 只建 target>。
约束：<不要写 case / 不改 hyptest 文件 / 不包含 H 扩展 / 需要 path-aware 结论等>。
```

#### 1. 分析 MemBlock non-H 覆盖率

```text
用 spike-coverage-testpoint 分析 Spike 覆盖率。
目标用 targets/memblock_non_h.json。
coverage repo 和 hyptest repo 已在 bashrc 里通过 `$HYPTEST_SPIKE_COV`、`$HYPTEST_HOME` 配好。
覆盖率输入：$HYPTEST_SPIKE_COV/cov_doc/gcov_raw/<明确的 memblock summary 文件>.txt，以及对应 .gcov 目录。
只要测试点规划，不要写 case。
重点看哪些 MemBlock cross 执行场景没有覆盖到；代码、函数、分支、call 只作为支撑证据，并给出值得补的高质量 hyptest 测试点。
```

#### 2. 只看某一类缺口

```text
用 spike-coverage-testpoint 看 MemBlock non-H 覆盖率里 vector whole/mask 和 vector indexed 的缺口。
覆盖率输入：<明确的 summary.txt> 和 <对应 .gcov 目录>。
请读取 summary 和对应 .gcov，说明哪些 entry/branch/call 没覆盖，
再判断缺的是哪些 cross 执行场景、应该补哪些测试点、observable 是什么、是否需要特殊 profile。
不要写 case。
```

```text
用 spike-coverage-testpoint 只分析 AP 支持的 AMO/LR/SC 覆盖率缺口，不包含 Zacas/AMOCAS。
覆盖率输入：<明确的 summary.txt> 和 <对应 .gcov 目录>。
要区分 entry 覆盖和 MMU.amo / LR/SC reservation 语义覆盖；Zacas/AMOCAS 在 NanHu-V5.1 AP spec 中是 NO，不能当作 in-scope 缺口。
最后给 hyptest-workflow handoff packet。
```

#### 3. 换一个分析目标

```text
我要分析 Spike frontend 覆盖率，不是 MemBlock。
项目实现继续用 specs/nanhu_v5_1_ap.json。
请从 targets/TEMPLATE.json 新建一个 target，
把我要测的 coverage_focus/scope/exclusion/dimensions 都放 target 文件里，
不要把 coverage Spike runner、环境变量、源码根目录这些项目实现信息塞进 target，
不要写死进 SKILL.md 或脚本。
先只建 target 并解释怎么用，不要分析覆盖率。
```

#### 4. 已经有候选，准备交接

```text
根据刚才的 Spike 覆盖率候选，生成 hyptest-workflow 交接包。
每个候选要包含 scenario_coverage_gap、cross_scenario_signature、coverage evidence、source/gcov evidence、target_semantic、
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
coverage repo 和 hyptest repo 已在 bashrc 里通过 `$HYPTEST_SPIKE_COV`、`$HYPTEST_HOME` 配好。
先跑 case_elf_asm/spike 里前 20 个 ELF，每个 case 独立 reset gcda、生成 before/after gcov、compare，并输出最终 summary。
跑完后请 agent 根据报告分析哪些 case 对目标路径有增量、哪些证据还不够，不要直接写 case。
```

跑完全部 ELF 后分析要补哪些测试场景：

```text
用 spike-coverage-testpoint 跑完 MemBlock non-H 全部 Spike ELF。
目标用 targets/memblock_non_h.json。
coverage repo 和 hyptest repo 已在 bashrc 里通过 `$HYPTEST_SPIKE_COV`、`$HYPTEST_HOME` 配好。
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

- `结论`: 当前覆盖率证据指向哪些 cross 执行场景缺口，哪些最值得补。
- `数据`: target、输入路径、case 数、runner 状态、覆盖计数等数据。
- `证据`: 具体 `.gcov`、函数、源码行、branch/call、case log、compare 文件，以及它们如何支持场景判断。
- `限制与下一步`: 不能证明什么，下一步要 inspect、单 case 增量、path marker，还是交给 `hyptest-workflow`。

面向人读的 Markdown 标题和解释文字统一使用中文；JSON key、稳定证据字段名、脚本状态枚举可以保留英文，方便后续脚本和 agent 继续识别。

默认输出路径规则：

```text
正式 md 报告：
$HYPTEST_SPIKE_COV/cov_doc/reports/<target_name>/<run_tag>/

正式运行证据：
$HYPTEST_SPIKE_COV/cov_runs/<target_name>/<run_tag>/

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
entry_line.md       指令入口 .gcov 精查证据
compare.md          单 case 增量覆盖证据
path_markers.md     path marker 序列证据
handoff.md          给 hyptest-workflow 的交接证据包
testpoint_plan.md   agent 最终测试点分析报告
```

### 人怎么看这些输出

先分清两类目录：

```text
cov_doc/reports/<target>/<run_tag>/   人看的报告，优先看
cov_runs/<target>/<run_tag>/          原始证据，追溯时看
```

主入口只有四个：

| 你想知道 | 看哪个文件 | 这个文件回答什么 |
|---|---|---|
| 看总体覆盖率展示 | `summary.md` | 哪些维度有 cross 场景证据缺口、哪些入口 0%、line/branch/call 支撑证据和优先级排名。 |
| 看具体源码哪里没覆盖 | `line.md` | `mmu.cc/mmu.h/v_ext_macros.h/...` 里哪些函数、源码行、branch、call 没跑到。 |
| 看具体指令入口有没有跑到 | `entry_line.md` | `riscv/insns/*.h.gcov` 的入口级行/分支/call 证据。 |
| 看最后该补哪些测试点 | `testpoint_plan.md` | agent 综合证据后的 cross 执行场景缺口、observable、gate 建议和下一步。 |

其他文件按需看：

- `handoff.md`: 给 `hyptest-workflow` 写 case 的交接包，不是最终结论。
- `compare.md`: 单 case 前后 `.gcov` 增量证据，用来确认某个 case 是否补到目标计数。
- `path_markers.md`: path marker 序列证据，用来确认 gcov 不能证明的 same-flow。
- `*.json`: 给脚本和 agent 继续处理的结构化数据，不是主要人工阅读入口。

一句话原则：`summary.md`、`line.md`、`entry_line.md` 是证据，`testpoint_plan.md`
是 cross 场景结论和行动计划。aggregate coverage 只能说明边/计数分别覆盖过，不能证明同一条动态执行流；
要证明 same-flow，看 `compare.md` 或 `path_markers.md`。

逐 case 跑完后，优先看 `case_matrix*/summary.md` 总览；单个 case 再看
`cases/<idx>_<case>/compare.md` 和 `run.log`。

一次好的最终分析只检查四件事：

- `结论`: 现在最缺哪里，优先补什么。
- `数据`: target、输入、case 数、line/branch/call/0% entry 等关键数字。
- `证据`: `.gcov`、源码函数/行、branch/call、case log 或 compare/path marker，以及它们支持的场景判断。
- `限制与下一步`: 哪些只是 aggregate evidence，哪些需要单 case 增量、path marker 或 `hyptest-workflow` 查重落 case。

## 高级：手动跑脚本

通常不需要用户手动跑脚本，直接 prompt Codex 即可。需要复现或调试时可以这样跑。
先让使用者在自己的 `~/.bashrc` 里设置环境变量；skill 和脚本只引用这些变量，不写个人 workspace 绝对路径：

```bash
export HYPTEST_SPIKE_COV=/path/to/spike-coverage
export HYPTEST_HOME=/path/to/riscv-hyp-tests
```

默认布局下只需要这两个变量。脚本会自动推导：

```text
SPIKE_BUILD_DIR=$HYPTEST_SPIKE_COV/build
SPIKE_GCOV_RAW=$HYPTEST_SPIKE_COV/cov_doc/gcov_raw
SPIKE_SOURCE_ROOT=$HYPTEST_SPIKE_COV
HYPTEST_ELF_DIR=$HYPTEST_HOME/case_elf_asm/spike
HYPTEST_SPIKE_COV_BIN=$HYPTEST_SPIKE_COV/build/spike
```

这里的 `HYPTEST_SPIKE_COV_BIN` 是 coverage skill 专用的 Spike，不是 hyptest 里编译/普通自检用的 `HYPTEST_SPIKE_BIN`。coverage matrix 只消费 `case_elf_asm/spike` 里已经存在的 ELF，不负责编译 hyptest case，也不调用 hyptest 的普通 Spike 命令。默认 runner 参数来自所选 target 引用的 `specs/*.json`：脚本读取 `coverage_spike.default_args` 后生成 `{spike_bin} <spec args> {elf}`。例如 `targets/memblock_non_h.json` 引到 `specs/nanhu_v5_1_ap.json`，默认会自动带 NanHu-V5.1 AP 的 `--isa=...` 和 `--priv=MSU`，不需要每次手写。只有临时特殊实验需要覆盖项目默认 runner 时，才传 `--command-template`。

summary 文件不做通用默认，因为它和 target/模块绑定。跑 summary 分析时显式传 `--summary <具体 summary.txt>`；如果某个人固定只分析一个目标，也可以在自己的 shell 里临时设 `SPIKE_COV_SUMMARY`，但 skill 不把它当成必需接口。

只有目录布局不标准时，再在 `~/.bashrc` 里覆盖对应变量，例如 `SPIKE_BUILD_DIR`、`SPIKE_GCOV_RAW`、`SPIKE_SOURCE_ROOT`、`HYPTEST_ELF_DIR` 或 `HYPTEST_SPIKE_COV_BIN`。

配置后可先自检解析结果：

```bash
python3 scripts/run_case_coverage_matrix.py --check-env
```

如果不是临时试跑，再设定正式报告和运行证据目录：

```bash
REPORT_DIR="$HYPTEST_SPIKE_COV/cov_doc/reports/memblock_non_h/20260521_current"
RUN_DIR="$HYPTEST_SPIKE_COV/cov_runs/memblock_non_h/20260521_current"
mkdir -p "$REPORT_DIR" "$RUN_DIR"
```

校验 spec 和 target：

```bash
python3 scripts/validate_spec.py specs/nanhu_v5_1_ap.json
python3 scripts/validate_target.py targets/memblock_non_h.json
```

跑 summary：

```bash
SUMMARY="$HYPTEST_SPIKE_COV/cov_doc/gcov_raw/<summary-file>.txt"
python3 scripts/analyze_spike_gcov.py \
  --summary "$SUMMARY" \
  --target targets/memblock_non_h.json \
  --top 18 \
  --json-out "$RUN_DIR/summary.json" \
  --markdown-out "$REPORT_DIR/summary.md"
```

精查 `.gcov`：

```bash
python3 scripts/inspect_gcov_lines.py \
  --gcov-dir "${SPIKE_GCOV_RAW:-$HYPTEST_SPIKE_COV/cov_doc/gcov_raw}" \
  --source-root "${SPIKE_SOURCE_ROOT:-$HYPTEST_SPIKE_COV}" \
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
python3 scripts/run_case_coverage_matrix.py \
  --target targets/memblock_non_h.json \
  --all-elves \
  --limit 20 \
  --gcno-from-target \
  --out-dir "$RUN_DIR/case_matrix_20"
```

全量跑完所有 mapped ELF：

```bash
python3 scripts/run_case_coverage_matrix.py \
  --target targets/memblock_non_h.json \
  --all-elves \
  --gcno-from-target \
  --out-dir "$RUN_DIR/case_matrix_all"
```

只跑名字像 MemBlock/访存相关的 ELF，适合先收一版更聚焦的证据：

```bash
python3 scripts/run_case_coverage_matrix.py \
  --target targets/memblock_non_h.json \
  --all-elves \
  --case-regex 'memblock|pbmt|pte|pmp|pma|amo|lr|sc|load|store|vector|trigger|fault|unaligned|misalign' \
  --gcno-from-target \
  --out-dir "$RUN_DIR/case_matrix_filtered"
```

只跑指定 case：

```bash
python3 scripts/run_case_coverage_matrix.py \
  --target targets/memblock_non_h.json \
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
- `--check-env`: 打印当前 `HYPTEST_HOME`、`HYPTEST_SPIKE_COV` 和推导出的 build/raw-gcov/source-root/ELF/coverage-Spike 路径后退出，适合第一次配置后自检。
- `--dry-run`: 只看会选哪些 case 和 `.gcno`，不运行。
- `--command-template`: 支持 `{spike_bin}`、`{elf}`、`{case_name}`、`{run_name}`、`{case_dir}` 等占位符；省略时使用 target 的 project spec `coverage_spike.default_args`，例如 `{spike_bin} --isa=<spec default_isa> --priv=MSU {elf}`。需要 Spike commit/log 证据时可显式覆盖成 `{spike_bin} --isa=<spec ISA> --priv=MSU -l --log-commits --log={case_dir}/spike.log {elf}`。显式传入后脚本完全按该模板执行。

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
请把最终分析保存成 $REPORT_DIR/testpoint_plan.md，报告必须包含 结论、数据、证据、限制与下一步，并在数据/证据里链接 $RUN_DIR/case_matrix_all。
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

默认 smoke 只用内置合成 fixture，不需要真实 coverage repo。需要顺手验证当前机器的真实 gcov 输入时，再打开外部 smoke：

```bash
HYPTEST_SPIKE_COV_EXTERNAL_SMOKE=1 bash scripts/run_smoke_tests.sh
```

## 目标配置

不要把具体规格写死在 `SKILL.md` 或脚本里。要换分析目标时，从 `targets/TEMPLATE.json` 复制一个新 target，填写：

- `project_spec`
- `coverage_focus`
- `scope_in`
- `scope_out`
- `dimensions`
- `scenario_coverage`：推荐填写。定义 cross 场景轴、证据策略和优先场景提示；它是报告 checklist，不是自动组合矩阵。
- `path_analysis`：可选。证据策略、路径报告字段 checklist、路径置信度、单 case 增量规则、path marker 词表。它不是完整路径矩阵。
- `inspection_hints`
- `duplicate_search_terms`

当前已有目标：`targets/memblock_non_h.json`。

## 注意

- 覆盖率只是证据，不是测试意图；最终目标是找 cross 执行场景覆盖缺口。
- 不要输出“补一条覆盖 line N 的 case”作为最终测试点；要说清楚 instruction/access、profile/gate、地址/翻译/保护/设备条件、异常/trigger/cache/vector/atomic 子条件和 observable。
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
