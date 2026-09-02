# YAF GOAI 复赛评审入口

> 私有科学冻结谱系标识：`18b1d20d35ec1cb0c401bd951c64f202c3dd67bd`
>
> 公开仓库：<https://github.com/1ove9/yaf-goai-semifinal>（sanitized root snapshot）
> 最终科学裁决：`insufficient_evidence`

## 一句话问题

YAF 将研究对象限定为情境条件化的两状态可重构 meander：同一套量化硬件在状态 A 服务 2.40–2.50 GHz，在状态 B 服务 5.725–5.875 GHz；搜索结果先由 NEC2 评价，独立 openEMS 互证只有在仪器释放闸门通过后才允许进行。

## 终局负结果状态卡

| 项目 | 冻结结果 |
|---|---|
| 科学终点 | `b_completion_pair_validity_without_effect_crossing` |
| H1 / H2 | 702 / 0 |
| H1 身份 | 702 个不同 `pair_hash` 的两状态计算记录；哈希互异不代表统计独立或物理唯一 |
| 最佳记录 | p01 / `es-b-completion` / seed 303 / step 265 |
| 最佳值与门槛 | worst reflected-power fraction `0.2301053124`，门槛 `0.1939405429`；等价 S11 为 −6.381 dB 与 −7.123 dB，尚差约 0.743 dB |
| 证据范围 | NEC2-only paired-state computational record；没有独立 openEMS 候选曲线 |
| 仪器状态 | 5.8 GHz rod-r2 为 `repair_not_confirmed`；2.45 GHz compatibility anchor 未获授权、未运行 |
| 裁决上限 | `insufficient_evidence` |
| 关联诊断 | 独立标注的 post-hoc descriptive diagnostic，不改变预注册终点 |
| 独立因果诊断附录 | 预注册反事实探针；终点 `span_support_sufficient_in_frozen_counterfactuals`；不改变主结论 |

前一项冻结的全配对分层研究在其 6000 次评估中未观察到 H1。随后独立预注册的
两父代 A-only 条件补全研究,在不同的冻结条件空间内观察到 702 条 H1 accepted
records,其中 ES 为 697 条、Random 为 5 条;ES 在 10/10 个 parent×seed 单元
中观察到 H1,Random 为 5/10。所有记录均未跨越预注册效应门槛,因此结果属于
"双状态有效性被观察到、性能提升未被观察到",最终裁决仍为
`insufficient_evidence`。

702 条 H1 accepted records 的 `pair_hash` 经核验互不重复。两个研究使用不同冻结条件空间，因此上述 0 与 702 只能并列报告，不能构成同一总体上的前后效应量比较。697 对 5、10/10 对 5/10 也只是在固定父代、seed 和预算下的描述性计数。

## 三件套导览

### 1. 最小可运行探索环境

- 配对状态环境与几何：`yaf_ai/exploration/paired_meander.py`、`paired_solver.py`、`paired_runner.py`
- 条件补全执行层：`yaf_ai/exploration/paired_b_completion_*.py`
- 终局报告重建：`scripts/paired_b_completion_report.py`
- 支持域证书：`scripts/paired_b_completion_certificate.py`
- 公开快照无求解器验证：`scripts/semifinal_public_snapshot_verify.py`

### 2. 探索日志

- 总账：`artifacts/runs/manifest.json`
- 当前终局总账：255 条 run entries；每条绑定 `log.jsonl` 与 `summary.json` 的 SHA-256
- 条件补全证据：`artifacts/runs/semifinal-paired-b-completion-*`
- 终局分析：`artifacts/analysis/semifinal-paired-b-completion-v1/{report.md,appendix.json}`
- 支持域证书：`artifacts/analysis/semifinal-paired-b-completion-v1-certificate/{report.md,summary.json}`
- 独立因果诊断附录：`artifacts/runs/semifinal-a-span-support-causal-probe-v1/` 与 `artifacts/analysis/semifinal-a-span-support-causal-probe-v1/{report.md,summary.json,dose-response.png}`

### 3. 参照系与判据

- 人工物理基线与唯一 warm parent：`artifacts/runs/semifinal-paired-manual-baseline/`、`artifacts/analysis/semifinal-paired-manual-baseline/warm_parent.json`
- Random、ES-cold、ES-warm 及条件补全比较见 `REFERENCE-FRAME.md`
- 冻结决策链：`DECISIONS.md`
- 证据到结论的索引：`EVIDENCE-INDEX.md`

## 终局权威与历史材料替代关系

`18b1d20d35ec1cb0c401bd951c64f202c3dd67bd` 是私有原始研究谱系的科学冻结标识。为彻底排除历史提示词与本机工具配置，公开仓库从清理后的终局树创建为新的单根快照，不含原 144 个研究提交的 commit/tree 时序，也不含被排除的 prompt/config blobs；因此该 ID 在公开 Git 中不可解析。公开版本的权威由当前文件树、255-entry manifest、公开快照回执和快照校验器共同构成。`artifacts/analysis/semifinal-submission/` 中的 219/219、2,700 accepted pairs、48 valid pairs、1/9 cells、旧候选 4.674341% 等数字只描述早期历史检查点，不能代替终局 B-parent 条件补全结论。

终局新增事实为：manifest 255 项；support certificate 480,002/480,002、0 失败；条件补全 20/20 runs、6,000 accepted、H1/H2=702/0；科学终点 `b_completion_pair_validity_without_effect_crossing`；最终裁决仍为 `insufficient_evidence`。其后独立预注册的 A-span 反事实探针观察到 10/10 单调剂量响应，p01 与 p02 各 5/5 在高剂量跨过冻结数值参考线，终点为 `span_support_sufficient_in_frozen_counterfactuals`；这些正剂量记录不属于 H1/H2 或旧候选池，不改变主结论。

## 无求解器复核范围

### 当前 255-entry 归档的完整字节完整性入口

```powershell
python scripts/archive_run.py --verify
```

该命令对当前 manifest 的 255 条 run entries 逐项重新计算其 `log.jsonl` 与 `summary.json` 的 SHA-256。它验证归档字节完整性，不重算科学指标、不重放 agent，也不调用 NEC2 或 openEMS。

### 公开快照终局事实验证入口

```powershell
python scripts/semifinal_public_snapshot_verify.py
```

该命令不调用求解器，检查公开快照回执与冻结文件哈希，从 20 行条件补全矩阵重新合计 6,000 accepted、H1/H2=702/0，并验证 A-span 探针的 10 个 parent×seed 块、固定三档剂量、32 次归档 subprocess 调用及 counterfactual-only 边界。成功输出包含 `archive_verify=255/255 OK` 与 `final_verdict=insufficient_evidence`。

历史 `scripts/semifinal_demo.py --verify` 依赖被有意排除的原始提交对象，只是内部历史工具，不是公开评审入口，也不应在本单根快照中执行。

### 关键研究子集的记录级语义重建

| 脚本 / 模块 | 覆盖范围 | 明确边界 |
|---|---|---|
| `scripts/freeze_paired_candidates.py --verify` + `yaf_ai.exploration.paired_candidates` | 旧 9-cell 与人工基线的候选排序、指标、身份 hash、所选轨迹 | 不覆盖 exact-support v2 或条件补全 |
| `scripts/paired_feasible_stage_b_report.py` + `yaf_ai.analysis.paired_feasible_stage_b` | exact-support v2 Stage B 的 10×600 已记录数据、指标、轨迹、hash、turn quota 与终点 | 分析生成脚本会写报告，没有只读 `--verify`；不是评审执行命令 |
| `scripts/paired_b_completion_certificate.py` | 两个冻结 B 父代共 480,002 个整数 A-span 支持点的穷举证书 | 支持域资格检查，不是电磁性能评价 |
| `scripts/paired_b_completion_report.py` + `yaf_ai.analysis.paired_b_completion` | 条件补全 20×300 已记录数据的指标、轨迹、hardware/state/pair hash、H1/H2、seed support 与终点 | 不重跑 agent、Random/ES 提案生成、预算或求解器；脚本会写报告，没有只读 `--verify` |

这里的“语义重建”只指对已记录曲线和参数的记录级重算，不表示重新运行搜索或电磁求解。条件补全的提交版 `report.md`、`appendix.json` 与 support-certificate artifacts 承载终局结论；255/255 manifest 校验将其源 run 字节绑定到总账。

## 干净克隆与开发质量门

评审环境需要 Python 3.11+ 与 `requirements-semifinal.txt` 中的最小依赖；不要求、也不
包含原研究 Git 历史：

```powershell
python -m venv .venv-review
.venv-review\Scripts\python.exe -m pip install -r requirements-semifinal.txt
.venv-review\Scripts\python.exe scripts/archive_run.py --verify
.venv-review\Scripts\python.exe scripts/semifinal_public_snapshot_verify.py
```

开发环境质量门：

```powershell
.venv\Scripts\python.exe -m pytest tests\ -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy yaf_core yaf_ai yaf_solvers yaf_api yaf_db yaf_worker --strict
```

绑定 `18b1d20d` 的既有验收记录是 pytest 795 passed、Ruff 通过、mypy strict 检查 165 个源文件且零错误，以及工作区和 fresh clone 均为 255/255。它们是此前执行并记录的 QA 结果，不是本次纯起草会话重新执行的结果。

## 部署、依赖与合规

- 复现指南：`docs/semifinal-reproducibility.md`。
- 合规与历史清理披露：`docs/semifinal-compliance.md`。
- 机器可读公开快照回执：`docs/provenance/PUBLIC-SNAPSHOT-RECEIPT.json`。
- 项目许可证：`LICENSE`；依赖约束：`pyproject.toml`；精简评审依赖：`requirements-semifinal.txt`。
- 科学数值只来自归档 solver subprocess 输出或归档曲线的确定性变换；LLM、图像模型、渲染器和人工编辑不产生或替代物理数值。
- 展示媒体必须附注：“Visualization reconstructed from archived parameters; it does not participate in scientific scoring or validation.”

队伍：`source sequence`；公开仓库：<https://github.com/1ove9/yaf-goai-semifinal>。尚需在赛事平台人工确认的字段见 `GAPS.md`。
