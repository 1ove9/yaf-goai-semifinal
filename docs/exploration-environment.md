# YAF 天线发明探索环境

`AntennaExplorationEnv` 把 YAF 的真实求解与评分路径封装为可由 Agent 重复进入的、预算受限的探索环境。环境的目标不是把一次优化包装成“发现”，而是提前固定问题边界、参照系和证据标准，让正结果、负结果与环境缺陷都可以被审计。

## 固定部分与可探索部分

一次 run 开始后，以下内容由冻结的 `ExplorationConfig` 固定：

- 频段、最大尺寸、目标增益、VSWR、效率和材料约束；
- 求解器选择、网格与端口规则、YAF 既有复合评分函数；
- evaluation budget、seed、发现阈值和诚实层；
- `solver_mode` 必须是 `native` 或 `subprocess`。解析 fallback 会显式失败，不能成为探索反馈。

Agent 只能探索天线几何，包括经典参数化模板的连续参数和满足尺寸约束的平面像素拓扑。每个动作是一个 `GeometryProposal`，环境通过 `InverseDesignPipeline` 的 `_verify` 与 `_evaluate_metrics` 路径完成求解和评分，不另写一套物理逻辑。

## 提前定义的发现信号

阈值由 `DiscoveryPolicy` 在运行前写入配置与 config hash：

1. **正向发现**：候选在同一 spec 下的 score 至少比经典模板高 10%，且 NEC2 与 openEMS 的最小 S11 差异不超过 3 dB。
2. **负结果**：至少各有 3 个样本时，探索算法的平均 score 系统性低于同预算、同参数空间的随机参照。
3. **环境缺陷信号**：NEC2 与 openEMS 的最小 S11 差异大于 3 dB。该结果标记为 `solver_disagreement`，不计为发现。
4. 不能满足上述证据条件时统一标记为 `insufficient_evidence`。

## 可比较参照系

- `ClassicTemplateBaseline`：中心频率上的 Balanis 矩形贴片公式；NEC2 模式下使用考虑端效应的 `0.475 λ` 偶极子。
- `RandomSearchBaseline`：在和 GP Agent 完全相同的连续参数边界内均匀采样。
- `GPExplorationAgent`：复用 YAF 的 `BayesianOptimizer`，以真实求解得到的负 score 作为最小化目标。

三者都调用同一个 `env.step()`，因此共享 spec、预算定义、求解器、评分和审计日志路径。

## 审计格式

每次运行写入 `runs/<run_id>/`：

- `log.jsonl`：每步一行，包含 schema version、step index、UTC timestamp、几何摘要与 SHA-256、solver name/mode、完整 metrics、score、seed、config hash、提案参数和 proposer。
- `summary.json`：冻结配置、完成步数、solver mode 计数和 top-3 设计。

日志由 Pydantic schema 重读；写入每行后会 flush + fsync，summary 通过临时文件原子替换。

## CLI

```powershell
.venv\Scripts\python.exe scripts\explore_demo.py --spec wifi24 --budget 6 --agent random --seed 42
.venv\Scripts\python.exe scripts\explore_demo.py --spec wifi24 --budget 6 --agent gp --seed 42
```

CLI 默认固定使用 openEMS。若本机不能产生 `subprocess`/`native` 结果，运行会以 `SolverUnavailableError` 失败，而不是记录解析近似值。

## Evidence archiving

`runs/` 是持续增长、被 Git 忽略的工作区草稿目录；复赛提交所需的正式证据必须通过显式归档进入受版本控制的 `artifacts/runs/`。归档不会修改或删除源 run，也不会静默覆盖已经归档的证据。

```powershell
.venv\Scripts\python.exe scripts\archive_run.py <run_id> --role agent-gp --note "..."
.venv\Scripts\python.exe scripts\archive_run.py --verify
```

重复归档会失败。只有明确传入 `--force` 才允许覆盖，且对应 manifest 项会记录 `overwritten: true`。`--verify` 会重新计算每个归档 run 的 `log.jsonl` 与 `summary.json` SHA-256；任一文件缺失或摘要不匹配都会输出 `MISMATCH` 并返回非零退出码。

`artifacts/runs/manifest.json` 是一个数组，每项记录：

- `run_id`、证据角色 `role` 与人工说明 `note`；
- 从 `summary.json` 程序化读取的 `config_hash`、`seed`、`steps_completed`、`solver_mode_counts`；
- 两个证据文件各自的 SHA-256、UTC `archived_at` 和显式覆盖标记 `overwritten`。

正式 agent-vs-baseline 对比只使用 manifest 中 `role != "smoke"` 且 `config_hash` 完全一致的 run。Smoke、失败或废弃路径仍应归档和说明，但不得混入正式比较。
