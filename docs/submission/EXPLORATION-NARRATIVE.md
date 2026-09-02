# 从受限静态双频搜索到两状态条件补全：YAF 的可审计探索链

> 冻结事实源：`18b1d20d35ec1cb0c401bd951c64f202c3dd67bd`  
> 终局裁决：`insufficient_evidence`

## 研究问题如何被证据修正

YAF 最初探索的是单一静态几何能否同时服务 2.45 GHz 与 5.8 GHz。冻结搜索没有给出足以升级结论的结果，后续仪器审计又暴露出自由形 openEMS 表示链的可观测性和收敛问题。项目没有隐藏这些结果，而是把问题切片修正为：同一套量化、理想 PEC meander 硬件能否通过两个情境状态分别服务两个频段，并在冻结参照系中跨越预注册效应门槛。

这一修正不是对旧候选的再次尝试，也不证明静态双频在一般意义上不可能。每个阶段均由独立预注册、固定预算、固定 seed、明确终点和不可追溯修改的证据提交约束。

## 探索时间线与证据

### 1. Day 5：历史 2.4 GHz 单频方法锚

提交 `dc9218b0d746e1e49862a40f29865a4301e0b98d` 中，81.512 mm meander 候选在 λ/160 NEC2 与 8× openEMS 下得到 1.181% 谐振频差和 0.955299 Pearson。证据位于 `artifacts/analysis/day5-wire-v6-final/{report.md,summary.json}`。这一结果只证明历史 2.4 GHz 单频链具备可用的方法学锚点，不能并入当前两状态结论。

### 2. Day 6 与 Day 6.5：静态双频负结果和仪器审计

Day 6 冻结自由形双频研究提交为 `acbf4736b8755b682d215e16fe479ffff534360d`，证据位于 `artifacts/analysis/day6-freeform/{report.md,summary.json}`。两个冻结 GP 候选均没有建立 openEMS 高频段有效谐振和自收敛前提，结论为 `insufficient_evidence`。这只是在冻结空间、预算与 seed 集内的有限负结果，不是静态双频不可能性的证明。

随后自由形渲染器进入显式仪器审计。r12 旋转一致性闸门在提交 `c6c3df683db758e60f456c5100ad9339f00c57f8` 通过。修复仪器下，候选 A 的终局证据提交为 `5589b71e9f8470eb425fb200c4587786ca4e1dc8`；候选 B 与因子审计终局提交为 `285d50f48b0853833ecea05cd3abe074b4978f03`。两者双频裁决均为 `NO_RESONANCE_IN_BAND`，discovery verdict 均为 `insufficient_evidence`。证据位于 `artifacts/runs/day65-repair-crosscheck-top{1,2}/summary.json` 与 `artifacts/analysis/day65-factor-audit/`。

### 3. 5.8 GHz meander 表示梯子：结果可解释，但仪器未释放

| 阶段 | 结果提交 | 证据与结局 |
|---|---|---|
| r1 | `ecf5ba420e22a3e840154c27f9254dfb9fdaf2a3` | `semifinal-wifi58-meander-renderer-anchor-r1-combined`；NEC2/openEMS 分歧且 1×/2× 未自收敛，`anchor_released=false` |
| r2 | `20d34fad3eb9d88631693069de94d1e5c7cec661` | 定标后的 NEC2 预测命中，但 4×→8× 冻结释放条件未成立，终局 `not_released_not_converged` |
| r3 | `6bee5eeac5642386f7015bf496e8a592424cb75c` | 16×→32× 移动 0.680272%，频差 1.360544%，Pearson 0.969483；32× 最小值越过目标带上缘，终局 `not_released_out_of_band_high` |

r3 显示曲线一致性和末档移动改善，但冻结带内条件仍未满足。因此该链被诚实封存为仪器终局，而不是选择中间档释放。

### 4. rod 表示：端口可观测性阻断后续互证

rod-r1 结果提交 `88f20bf85574ba3fb289b0ddc516ad5752d3cdba`：1× openEMS 正常执行 23,716 steps 后缺失 `port_ut_1`，终止为 `execution_failed`，没有可用 S11 或科学裁决。

5.8 GHz rod-r2 以 `repair_not_confirmed` 终止:修复后的 voltage/current
probe 均为 0 个可解析样本,未计算 S11,`scientific_verdict=null`。
因此释放前提未满足,2.45 GHz compatibility anchor 未获授权、未运行。

rod-r2 结果提交为 `ba53596f8191ec1a820ae7470349c89091a5bbe8`，证据位于 `artifacts/analysis/semifinal-wifi58-rod-renderer-anchor-r2/` 与 `artifacts/runs/semifinal-wifi58-rod-renderer-anchor-r2-combined/`。这些是仪器可观测性记录，不是对候选几何性能的正反证。

### 5. 人工物理基线：对照本身也接受有效性审计

人工基线为 864-key 缓存单状态评估网格(36 个硬件 ×〔12 个 A + 12 个 B〕);
其中 369 条因几何无效在求解前被拒绝,495 条完成 NEC2 subprocess 扫频。
随后仅由缓存组装 5,184 个潜在配对,其中 756 个曲线完整并被评分,
0 个有效配对;组装阶段无新增求解器调用。

预注册提交为 `52c4d38acafb6d620234d781406357fbc79bc25b`，结果提交为 `906835eceeae2e48a652e2b7fa891fd3e8461440`。人工对照的 state-A 选择落在扫频端点，因此它是冻结的诊断参照，不被包装成最强可能基线。

### 6. 初始配对矩阵与 Robust Hunt R2：有效配对稀疏，效应门未跨越

九单元配对矩阵在提交 `a19684b5449774db82b21907cc11c7874287f838` 完成：2,700 accepted pairs、5,400 条 NEC2 subprocess 曲线，只有 ES-warm seed 101 的 48 条记录满足配对有效性。冻结候选在提交 `4a8222eb7528a24acaa5879e7afa2398f0413740` 选定，但 worst-state reflected power 只比人工诊断参照低 4.674341%，未达到冻结的 10% 门槛。

Robust Hunt R2 在 `eead162e33c5150f741050df4901f3d608bc5ea5` 预注册、`66a4325d9bc07ca97a8ec4e6ddf86b2854663a45` 封存。五个 seed 各接受 400 条，4/5 seed 观察到至少一个有效配对，但 0/5 跨效应门槛。2,000 accepted 中 1,928 条为 turn 3；6,313 次拒绝全部为 short-segment failure。这把失败定位到参数表示与合法支持域，而不是简单增加同类重试。

### 7. Solver-free 表示消融：先证明采样表示覆盖合法域

exact-support v2 在 `e5fab578288f9660a80fa7211b130b5c2fdd63bb` 预注册、`513b62471e78d22ee49eeb393526d1f945912e42` 实现。Stage A 提交 `8348708e11be98973fd8a106ccad4053dfa1205a` 对 4 个 turn × 5 个 seed × 10,000 draws 做 200,000 次 common-random-number、零求解器比较。conditional representation 为 200,000/200,000 valid，并在每个 turn 的 5/5 seed 上改善覆盖，终点为 `coverage_improved_all_turns`。

该结果只说明提案表示覆盖，不包含天线分数，也不选择或删除 Stage B 的 turn。

### 8. exact-support v2 Stage B：全空间分层搜索没有观察到有效配对

Stage B 在提交 `8fb865005791a3f1fa53d212d0f0a1e813f19558` 封存，证据位于 `artifacts/analysis/semifinal-feasibility-stratified-v2-stage-b/` 及十个 `semifinal-paired-stratified-v2-*` run。Random 与 ES 各 5 seed，每 run 600 accepted 且 600 unique，共 6,000 条；有效配对与 gate crossing 均为 0。B-state search-valid 只在 ES 中出现 2/3,000，在 Random 中为 0/3,000。冻结 selected row 只是诊断性 fallback，不是有效候选。

### 9. B-parent A-only 条件补全：不同冻结条件空间中的终局结果

该研究由四个连续提交冻结：预注册 `9e9edbc762e8c885052aa08d469e6872b719d79e`、实现 `d205ffcb26ac376071ca14b537a2db64402d30a2`、support certificate `f054240f09404ce978fe0dbcbb56bf1bf03a8d3d`、矩阵 `e5f36fd971a7266531a6d124f553f121379ad889`。证书穷举 480,002/480,002 个跨度点、0 失败、0 solver calls；矩阵 20/20 runs completed，共 6,000 accepted、0 rejections，并在每条记录上复现冻结 B 的身份和曲线。

前一项冻结的全配对分层研究在其 6000 次评估中未观察到 H1。随后独立预注册的
两父代 A-only 条件补全研究,在不同的冻结条件空间内观察到 702 条 H1 accepted
records,其中 ES 为 697 条、Random 为 5 条;ES 在 10/10 个 parent×seed 单元
中观察到 H1,Random 为 5/10。所有记录均未跨越预注册效应门槛,因此结果属于
"双状态有效性被观察到、性能提升未被观察到",最终裁决仍为
`insufficient_evidence`。

702 条 H1 accepted records 的 `pair_hash` 经核验互不重复。697 对 5 与 10/10 对 5/10 只是在两个父代、五个 seed、固定预算内的描述性计数，不是成功率、显著性或一般算法结论。

最佳描述性记录来自 `semifinal-paired-b-completion-p01-es-s303` step 265：worst reflected-power fraction `0.23010531242953516`，而冻结门槛为 `0.19394054289730642`；等价 S11 为 −6.381 dB 与 −7.123 dB，仍差约 0.743 dB。

## Post-hoc descriptive diagnostic / 终局后描述性诊断

> 说明：本节发生在冻结终点之后，不属于预注册终点，也不进入前述效应门判定。

终局后的描述性审计显示,在两个冻结 B 父代、A-only 二维条件空间及 NEC2 指标
下,702/702 条 H1 accepted records 的瓶颈均为 A;575/702 的 A-span 落在允许
上界最后 0.5%,按 worst reflected-power fraction 排序的 top-10 全部不低于
998385 ppm。这显示当前条件切片存在强烈边界压力,与 A 状态空间受限的解释
一致,但不构成物理极限证明,也未排除父代选择、参数化、有限预算及算法因素。

该诊断说明 A-span 上界在当前切片中表现为活跃约束；它没有证明扩大边界一定跨过门槛，也没有排除其他共享硬件父代、参数化或搜索策略的影响。

## 10. A-span 支持域因果探针（独立因果诊断附录）

该附录由四个连续提交冻结：预注册 `5a6e778f57d37511be7b442ef890024079d81f63`、实现 `5d5b7792f9f56931c435ec6661ae82b792f428e2`、换行门禁修正 `b1ebf8ed578bde819d666c53fb418aa5d9812e9f`、运行归档 `18b1d20d35ec1cb0c401bd951c64f202c3dd67bd`。队列限定为 ES-only；对每个 `(parent, seed)`，按 `(worst_reflected_power_fraction, pair_hash, run_id, step_index, proposal_index)` 的最小元组冻结一条 H1 源记录，共形成两个父代 × 五个 seed 的 10 个源筛选块。该有限队列不是来自天线空间的无偏样本。

探针保持共享硬件、state-A 导线长度、冻结 state B、40 mm 盒界、几何方程、评分、频点表与 λ/20 NEC2 不变，只对 A-span 控制施加 `dose_ppm ∈ {0, 50000, 100000}`。这对应控制跨度相对零剂量增加 0、1、2 mm，实际全宽增加 0、1.5、3 mm；所有几何仍在 40 mm 盒内，实测最大全宽为 33.48644 mm。32/32 次求解均为真实 NEC2 subprocess：2 次冻结 B 重放加 10 块 × 3 剂量，零 fallback、零 openEMS；零剂量曲线与源记录规范哈希 10/10 相等。

| 剂量 | A-span 增量 | 实际全宽增量 | 平均 state-A reflected-power loss | 冻结诊断结果 |
|---:|---:|---:|---:|---|
| 0 ppm | 0 mm | 0 mm | 0.23371 | 零剂量重放对照 |
| 50,000 ppm | +1 mm | +1.5 mm | 0.19962 | 10/10 块的单调中间点 |
| 100,000 ppm | +2 mm | +3 mm | 0.16823 | 高剂量改善 10/10；相对零剂量平均降低 28.02%（27.32%–28.23%） |

10/10 块呈单调剂量响应；+100,000 ppm 的 hybrid loss 在 p01 5/5、p02 5/5 中跨过冻结数值参考线 `T_ref = 0.19394054289730642`。科学终点为 `span_support_sufficient_in_frozen_counterfactuals`。这把边界压力的关联观察升级为预注册的模型内因果证据，支持旧 A-span 上限是活跃约束的解释，并为下一轮执行器或参数空间重设计提供直接依据。

正剂量记录严格属于 `counterfactual-only`：它们不是 H1/H2，不进入旧候选池或算法比较，也不能称为“跨过效应门槛的设计”，只能称为跨过冻结数值参考线的反事实记录。该探针不证明物理上限，不证明扩界必然成功，也不提供新天线或双求解器确认；主研究的 H1/H2=702/0、终点与 `insufficient_evidence` 裁决上限均不改变。

在任何求解器调用之前，初始门禁因 Windows `core.autocrlf` 文本检出差异而停止。提交 `b1ebf8ed578bde819d666c53fb418aa5d9812e9f` 只把七个文本源码路径的身份检查改为通过 `git hash-object --path` 比较过滤后的 Git blob；归档证据仍按原始字节校验。该修正有独立 DECISIONS 条目与执行说明，没有改变队列、剂量、几何、求解器、频点、评分、阈值或终点。

## 终局解释

环境没有失效：它先拦截了端点假极小、短段非法几何、未释放仪器和不可追溯的候选替换，又把配对有效性与性能效应拆成 H1/H2 两级。终局观察到 H1，却没有观察到 H2；这是一项有定位能力的阶段性负结果。

当前证据能够支持的最强表述是：在两个冻结 B 父代的 A-only 条件空间、既定 NEC2 参照系、五个 seed 与每 run 300 accepted 的预算下，存在配对有效记录，但没有记录跨越冻结性能门槛。独立 openEMS 候选互证未获授权，连续机械运动、材料损耗、接触、执行器体积与制造公差均未建立。

## 下一阶段问题定位

提交后的后续研究可分别预注册两条路线：

1. 共享硬件的联合条件协同设计：外层选择 B-valid 父代池，内层完成 A 状态，避免把单一父代误当成整个空间。
2. 边界或执行器扩展：把 A-span 边界距离作为冻结观测量，独立评估扩展盒界、状态自由度或参数化能否缓解当前活跃约束。

其中边界或执行器扩展路线现在已有预注册、单变量、有限源筛选队列下的模型内因果证据，可作为下一轮独立预注册的直接依据。

两条路线都必须另起预注册，不能回写本研究的空间、门槛或裁决。openEMS 候选互证也只能在仪器释放后另行授权。
