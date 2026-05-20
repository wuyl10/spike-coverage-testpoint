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
- `scripts/validate_target.py`: 校验 target JSON 结构和正则。
- `evals/`: skill 评估用例。

## 快速使用

先校验 target：

```bash
python3 scripts/validate_target.py targets/memblock_non_h.json
```

跑 MemBlock non-H summary：

```bash
python3 scripts/analyze_spike_gcov.py \
  --summary /nfs/home/wuyuanlong/workspace/offical-spike-coverage/cov_doc/gcov_raw/gcov_memblock_non_h_summary.txt \
  --target targets/memblock_non_h.json \
  --top 18 \
  --json-out /tmp/spike_cov_memblock_analysis/summary.json \
  --markdown > /tmp/spike_cov_memblock_analysis/summary.md
```

精查重点 `.gcov`：

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

## 目标配置

不要把具体规格写死在 `SKILL.md` 或脚本里。要换分析目标时，从 `targets/TEMPLATE.json` 复制一个新 target，填写：

- `spec`
- `scope_in`
- `scope_out`
- `dimensions`
- `inspection_hints`
- `duplicate_search_terms`

当前已有目标：`targets/memblock_non_h.json`。

## 注意

- 覆盖率只是证据，不是测试意图。
- `insns/*.h` 入口覆盖只能说明指令入口有没有跑到，语义仍要结合共享路径源码判断。
- 生成 case、修改 `test_point`、注册 `test_register.c` 时，应切到 `hyptest-workflow` skill。
