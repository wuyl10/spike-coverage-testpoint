# Spike Coverage Testpoint Skill

把 Spike 的 gcov 覆盖率缺口转成 hyptest 测试点规划。

核心分工：

- 脚本负责快速找证据：哪些文件、函数、源码行、branch、call 没覆盖或覆盖少。
- agent 负责做判断：这些缺口对应什么架构场景，是否值得补，怎么设计可自检测试点。

## 目录

- `SKILL.md`: Codex skill 主说明。
- `targets/`: 覆盖率分析目标配置。具体规格、范围和排除项放这里。
- `scripts/analyze_spike_gcov.py`: 解析 `gcov -b -c` summary，按 target 维度排序覆盖缺口。
- `scripts/inspect_gcov_lines.py`: 精查 `.gcov`，提取 `#####`、未执行 branch/call 和源码上下文。
- `scripts/build_handoff_packet.py`: 根据 summary/line JSON 生成 hyptest-workflow 交接包骨架。
- `scripts/compare_gcov_snapshots.py`: 比较单 case 前后 `.gcov` 快照，确认必经 line/branch/call 计数是否增加。
- `scripts/analyze_path_markers.py`: 解析 coverage Spike path-marker 日志，确认同一条执行流 marker 序列是否出现。
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
再判断是 confirmed-not-executed、edge-covered-path-unknown、single-case-increment-confirmed，
还是 needs-path-instrumentation。
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
并给 path_confidence。
```

#### 7. 路径标记插桩设计或分析

```text
用 spike-coverage-testpoint 给 coverage Spike 设计 MemBlock path marker 插桩。
目标用 targets/memblock_non_h.json。
场景是：<具体执行流>。
请从 target 的 path_analysis.path_markers 里选 marker，
说明建议插在哪些 Spike 源码函数/分支，输出 JSONL marker 格式，
以及如何用 analyze_path_markers.py 判断 marker 序列有没有出现。
不要改普通 Spike 行为。
```

#### 8. 要真正写 case

先用本 skill 得到测试点计划。然后再说：

```text
根据上面的 handoff packet，用 hyptest-workflow 写前 2 个 case，
做查重、选位置、更新 test_point/test_register.c、编译并跑 spike。
```

## 输出应该长什么样

一次好的分析应该至少包含：

- 覆盖率输入：target、summary、gcov 目录。
- 高优先级缺口：按维度排序，带 line/branch/call/0% entry 证据。
- 行级证据：具体 `.gcov` 文件、源码行、函数、miss kind。
- 路径置信度：`confirmed-not-executed`、`single-case-increment-confirmed`、`edge-covered-path-unknown`、`needs-path-instrumentation` 或 `out-of-scope`。
- 路径签名：从 Spike 源码和 `.gcov` 证据反推的目标入口、共享函数路径、must-pass 证据点、源码证明的条件、observable、剩余不确定性。
- 测试点候选：missing scenario、test idea、observable、gate note。
- 查重提示：应该在 hyptest 里搜哪些关键词。
- handoff packet：后续交给 `hyptest-workflow` 写 case。

## 高级：手动跑脚本

通常不需要用户手动跑脚本，直接 prompt Codex 即可。需要复现或调试时可以这样跑。

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
  --json-out /tmp/spike_cov_memblock_analysis/summary.json \
  --markdown > /tmp/spike_cov_memblock_analysis/summary.md
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
  --json-out /tmp/spike_cov_memblock_analysis/line.json \
  --markdown > /tmp/spike_cov_memblock_analysis/line.md
```

生成交接包骨架：

```bash
python3 scripts/build_handoff_packet.py \
  --summary-json /tmp/spike_cov_memblock_analysis/summary.json \
  --inspect-json /tmp/spike_cov_memblock_analysis/line.json \
  --top 8 \
  --markdown
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
  --markdown
```

解析 path marker 日志：

```bash
python3 scripts/analyze_path_markers.py \
  --log /tmp/spike_mem_path_cov.jsonl \
  --require mem.access.scalar_load \
  --require mem.translate.tlb_miss_walk \
  --require mem.fault.page \
  --ordered \
  --markdown
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
- 不要从 target 里的字段枚举“理论组合”来生成测试点；必须从 Spike 源码、`.gcov`、单 case 增量或 marker 记录反推真实路径。
- 生成 case、修改 `test_point`、注册 `test_register.c` 时，应切到 `hyptest-workflow` skill。
