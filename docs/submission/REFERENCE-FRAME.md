# YAF 复赛参照系与发现信号

> 事实源：`18b1d20d35ec1cb0c401bd951c64f202c3dd67bd`  
> 本文件描述比较规则，不升级终局裁决。

## 1. 科学对象

研究对象是同一套量化、理想 PEC meander 硬件及两个状态控制：

- 状态 A：2.40–2.50 GHz；
- 状态 B：5.725–5.875 GHz；
- 两个状态共享 hardware identity，状态几何必须不同并通过冻结轨迹/几何谓词；
- NEC2 是冻结搜索与排名参照系；openEMS 只在独立仪器释放后承担候选互证。

所有结论均限定于预注册的空间、父代、seed、预算和指标。静态空间、全配对 exact-support 空间和 B-parent A-only 条件空间不是同一总体，不能做跨空间提升率比较。

## 2. 指标与两级终点

对每个状态：

```text
L = 10^(S11_db / 10)
state_FoM = 1 - L
base_score = min(FoM_A, FoM_B) = 1 - max(L_A, L_B)
```

其中 `L` 是反射功率比例，越低越好。高 `base_score` 只说明当前记录的最差状态反射较低，不自动满足效应门。

效应量在冻结 NEC2 参照系内独立判定：

```text
L_agent <= 0.90 × L_manual
```

冻结人工参照为 `L_manual = 0.21548949210811824`，因此 `L_REQUIRED = 0.19394054289730642`。B-parent 条件补全终局中的最佳记录为 `0.23010531242953516`，未跨门槛。

两级终点：

- H1：`valid_pair_search is true`，即两个状态均满足冻结有效性条件；
- H2：H1 成立且 `worst_reflected_power_fraction <= 0.19394054289730642`。

终局 H1/H2 为 702/0。H1 只能说明 NEC2 记录层面的两状态有效性；它不包含独立 openEMS 候选曲线、连续机械运动或真实材料效应。

## 3. 人工物理基线

人工基线为 864-key 缓存单状态评估网格(36 个硬件 ×〔12 个 A + 12 个 B〕);
其中 369 条因几何无效在求解前被拒绝,495 条完成 NEC2 subprocess 扫频。
随后仅由缓存组装 5,184 个潜在配对,其中 756 个曲线完整并被评分,
0 个有效配对;组装阶段无新增求解器调用。

来源：

- 预注册：`52c4d38acafb6d620234d781406357fbc79bc25b`
- 结果：`906835eceeae2e48a652e2b7fa891fd3e8461440`
- run：`artifacts/runs/semifinal-paired-manual-baseline/`
- 分析：`artifacts/analysis/semifinal-paired-manual-baseline/`

人工参照的 state-A 选择落在 sweep index 100，因此 `valid_pair_search=false`，是冻结诊断参照，不代表最强可能人工方案。

## 4. 唯一 warm parent

唯一 warm parent 在人工基线归档时冻结于 `artifacts/analysis/semifinal-paired-manual-baseline/warm_parent.json`：

| 字段 | 冻结值 |
|---|---|
| hardware grid / pair grid | 6 / 963 |
| hardware hash | `d8d7e70ee2f085ca4c9a73b37c9c69a63bd02b97bdb0307d4fda0934642ca933` |
| pair hash | `e9f13ba6ede326e3adc4a48ba0a7658c0ca712434550ed98bffab681d262b321` |
| search/base score | `0.7845105078918817` |
| state A | 70.359 mm，span 1.000000 |
| state B | 25.844 mm，span 0.760000 |
| validity | `valid_pair_search=false`，`positive_eligible=false` |

它只用于预注册的 ES-warm 初始化，不能在观察结果后替换。它本身是诊断父代，不是通过效应门的记录。

## 5. 算法参照

| 参照 | 初始化与支持域 | 用途 | 解读限制 |
|---|---|---|---|
| Random | 与对应研究中的 ES 使用相同冻结参数空间、预算和 seed | 判断结构化搜索是否在同一实验内产生不同描述性覆盖 | 不跨研究空间比较；计数不解释为成功概率 |
| ES-cold | 不使用人工父代，从冻结初始分布开始 | 原始 9-cell 中与 Random、ES-warm 对照 | 只描述该矩阵，不外推到条件补全 |
| ES-warm | 只使用提交前冻结的唯一 warm parent | 检查预先给定物理起点能否改善局部搜索 | 不允许观察结果后换父代；旧 9-cell 只有 seed 101 出现有效记录 |
| ES-b-completion | 对每个冻结 B 父代进行 A-only cold search；源 A 状态不参与初始化 | 与同条件空间 Random 比较 H1/H2 描述性计数 | 697 对 5、10/10 对 5/10 不构成一般算法结论 |

B-parent 条件补全固定两个父代、两个 agent、五个 seed、每 run 300 accepted。每条 accepted record 必须逐位复现父代 B 的 hardware、geometry 和规范曲线身份，否则矩阵终止。

## 6. 支持域证书

在矩阵前，提交 `f054240f09404ce978fe0dbcbb56bf1bf03a8d3d` 对两个父代各 240,001 个整数 A-span 点进行穷举，共 480,002/480,002、0 失败、0 solver calls。证书检查 exact legality、binary64 trajectory audit、边界/前驱与 canonical round-trip。

证书证明的是冻结条件映射的合法支持域，不是电磁性能评价，也不改变 H1/H2 判据。

## 7. 终局比较表

| 冻结研究 | 条件空间 | Accepted | H1 | H2 | 结论 |
|---|---|---:|---:|---:|---|
| exact-support v2 Stage B | 全配对分层空间；Random/ES，各 5 seed | 6,000 | 0 | 0 | `no_gate_crossing_observed_under_frozen_stratified_study` |
| B-parent A-only completion | 两个冻结 B 父代，各自搜索二维 A support | 6,000 | 702 | 0 | `b_completion_pair_validity_without_effect_crossing` |

两行必须并列理解，不能写成同一总体上的前后提升。702 个不同 `pair_hash` 只表示冻结身份去重，不等于 702 个统计独立样本或物理唯一结构。

## 8. 独立仪器与裁决上限

5.8 GHz rod-r2 以 `repair_not_confirmed` 终止:修复后的 voltage/current
probe 均为 0 个可解析样本,未计算 S11,`scientific_verdict=null`。
因此释放前提未满足,2.45 GHz compatibility anchor 未获授权、未运行。

因此当前候选互证未获授权，最终裁决始终为 `insufficient_evidence`。任何后续互证必须先释放仪器并另行预注册，不能追溯修改本研究的 H1/H2、门槛、候选或终点。

## 9. 独立反事实诊断附录

B-parent 条件补全终局之后，提交 `5a6e778f57d37511be7b442ef890024079d81f63` 预注册了 A-span 支持域因果探针，结果归档于 `18b1d20d35ec1cb0c401bd951c64f202c3dd67bd`。它对两个冻结 B 父代、五个 seed 的 10 个 ES-only 源筛选块各施加 0、+50,000、+100,000 ppm 的单变量 A-span 剂量，同时保持硬件、state-A 导线长度、state B、40 mm 盒界、求解器、频点和评分不变。

该附录观察到 10/10 单调剂量响应，高剂量在 p01 5/5、p02 5/5 中跨过冻结数值参考线，终点为 `span_support_sufficient_in_frozen_counterfactuals`。但正剂量记录是模型内 NEC2-only 的 `counterfactual-only` 诊断记录，不属于 H1/H2、旧候选池或算法比较；有限源筛选队列不是无偏样本。它不改变本文件的 H1/H2 判据、比较规则、冻结门槛或 `insufficient_evidence` 裁决上限。
