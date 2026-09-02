# YAF 复赛终局证据索引

> 私有科学冻结谱系标识：`18b1d20d35ec1cb0c401bd951c64f202c3dd67bd`
> 公开仓库是 sanitized root snapshot。下列原提交哈希作为归档溯源标签保留，但其
> commit/tree 时序不在公开历史中；公开评审以当前路径、文件 SHA-256、255-entry manifest 与
> `docs/provenance/PUBLIC-SNAPSHOT-RECEIPT.json` 为准。

## A. 历史方法与问题修正证据

| 结论范围 | 完整提交哈希 | 冻结路径 | 证据说明 |
|---|---|---|---|
| Day 5 2.4 GHz 单频方法锚 | `dc9218b0d746e1e49862a40f29865a4301e0b98d` | `artifacts/analysis/day5-wire-v6-final/{report.md,summary.json}` | 81.512 mm meander 在 λ/160 NEC2 与 8× openEMS 下频差 1.181%、Pearson 0.955299；只作历史单频方法锚 |
| Day 6 冻结静态双频研究 | `acbf4736b8755b682d215e16fe479ffff534360d` | `artifacts/analysis/day6-freeform/{report.md,summary.json}` | 冻结空间、预算与 seed 集内终局 `insufficient_evidence`；report blob SHA-256 `07426556777d842bd71489a4e866f6a5487714a95e0f10b3ec52f137aac95d00`，summary `28def8a7b5a204e7da394f458ab6bd6e027f124f0da025571065c904ef1a4df1` |
| Day 6.5 候选 A 修复后重判 | `5589b71e9f8470eb425fb200c4587786ca4e1dc8` | `artifacts/runs/day65-repair-crosscheck-top1/summary.json` | 双频重判为 `NO_RESONANCE_IN_BAND`，discovery verdict 为 `insufficient_evidence` |
| Day 6.5 候选 B 与因子审计终局 | `285d50f48b0853833ecea05cd3abe074b4978f03` | `artifacts/runs/day65-repair-crosscheck-top2/summary.json`；`artifacts/analysis/day65-factor-audit/` | 候选 B 同样未建立双频终点；因子审计保留预注册阈值 |

## B. openEMS 仪器闸门证据

| 仪器阶段 | 完整提交哈希 | Run / 分析路径 | 终局状态 |
|---|---|---|---|
| 自由形 r12 旋转一致性 | `c6c3df683db758e60f456c5100ad9339f00c57f8` | `artifacts/runs/day65-freeform-rotation-invariance-r12-*` | 三姿态旋转闸门通过；只释放该渲染链的一致性检查 |
| meander anchor r1 | `ecf5ba420e22a3e840154c27f9254dfb9fdaf2a3` | `artifacts/runs/semifinal-wifi58-meander-renderer-anchor-r1-combined/` | 分歧且 1×/2× 未收敛，`anchor_released=false` |
| meander anchor r2 | `20d34fad3eb9d88631693069de94d1e5c7cec661` | `artifacts/runs/semifinal-wifi58-meander-renderer-anchor-r2-combined/` | `not_released_not_converged` |
| meander anchor r3 | `6bee5eeac5642386f7015bf496e8a592424cb75c` | `artifacts/runs/semifinal-wifi58-meander-renderer-anchor-r3-combined/` | 末档移动 0.680272%、频差 1.360544%、Pearson 0.969483，但最细档谷越过带顶；`not_released_out_of_band_high`；log SHA-256 `0e9da50876fa679870160ba9349a8391c18d7917355d7cef50177899bb967a9f`，summary `d5ac661dc0251d0e7dcecf7a88d967a2c510e568e3338a45c5e84399254f67a9` |
| rod anchor r1 | `88f20bf85574ba3fb289b0ddc516ad5752d3cdba` | `artifacts/analysis/semifinal-wifi58-rod-renderer-anchor-r1/build-only.json`；`artifacts/runs/semifinal-wifi58-rod-renderer-anchor-r1-combined/` | 缺失 `port_ut_1`，`execution_failed`，无 S11 |
| rod anchor r2 | `ba53596f8191ec1a820ae7470349c89091a5bbe8` | `artifacts/analysis/semifinal-wifi58-rod-renderer-anchor-r2/build-only.json`；`artifacts/runs/semifinal-wifi58-rod-renderer-anchor-r2-combined/` | 修复后 voltage/current probe 均 0 可解析样本，`repair_not_confirmed`；log SHA-256 `b3dd5214aae9c0f48f1051514109207bbb86c9f5cc3b832afc6180da62347079`，summary `6981fb426ea700a31aa4b716c845bb7b6b6a99a30a41e1013b090eed89dcf6f1` |

## C. 两状态参照系与初始搜索

| 证据 | 完整提交哈希 | 冻结路径 | 说明 |
|---|---|---|---|
| 人工基线预注册 | `52c4d38acafb6d620234d781406357fbc79bc25b` | `docs/semifinal-paired-manual-baseline-preregistration.md` | 冻结 36 硬件、A/B 单状态表和唯一 warm-parent 规则 |
| 人工基线结果与父代 | `906835eceeae2e48a652e2b7fa891fd3e8461440` | `artifacts/runs/semifinal-paired-manual-baseline/`；`artifacts/analysis/semifinal-paired-manual-baseline/warm_parent.json` | 864 keys、369 求解前拒绝、495 NEC2 sweeps；5,184 assembled、756 scored、0 valid；log SHA-256 `838fd4d77e6fe15ad7bd7625d95d6a8071a96cd6c1e2483dcae77824a80420e4`，summary `a089fa75ac3891ea7895b86962574aefda778c9a2d8728d1f29c2db7027cb133` |
| 初始九单元矩阵 | `a19684b5449774db82b21907cc11c7874287f838` | `artifacts/runs/semifinal-paired-{random,es-cold,es-warm}-s{101,202,303}/` | 2,700 accepted、5,400 subprocess curves；历史 218-entry source manifest SHA-256 `6de538d4ec44931eda14cd4ce1828b2962176c8af500106f48bb0fbba331ffcb` |
| 历史候选冻结 | `4a8222eb7528a24acaa5879e7afa2398f0413740` | `artifacts/analysis/semifinal-paired-agent-batch/frozen_candidates.json` | 旧 top-ES / top-Random / manual 三对象；文档 SHA-256 `0e814e2cc85ae0fe361c91a4d7338ae2175369b494eb49cdef8bd165338695d5` |
| rod-r2 时点 submission package | `bdfb9c1a0e4738c70a0bc111ec17805b69e94c76` | `artifacts/analysis/semifinal-submission/` | 真实历史快照；其 219/219 和旧候选结论不能当作当前终局 |

## D. Robust Hunt R2 与 exact-support v2

| 阶段 | 完整提交哈希 | 冻结路径 | 说明 |
|---|---|---|---|
| Robust Hunt R2 预注册 | `eead162e33c5150f741050df4901f3d608bc5ea5` | `docs/semifinal-paired-r2-robust-hunt-preregistration.md` | 冻结父代回归式 ES、五 seed、budget 400 与终点 |
| Robust Hunt R2 结果 | `66a4325d9bc07ca97a8ec4e6ddf86b2854663a45` | `artifacts/analysis/semifinal-paired-r2-robust-hunt/{report.md,appendix.json}`；五个 `semifinal-paired-r2-es-warm-*` run | 4/5 seed 有有效配对，0/5 过效应门；6,313 拒绝全部为 short segment |
| exact-support v2 预注册 | `e5fab578288f9660a80fa7211b130b5c2fdd63bb` | `docs/semifinal-feasibility-stratified-exact-v2-preregistration.md` | 冻结 representation ablation 与 balanced Stage B |
| exact-support v2 实现 | `513b62471e78d22ee49eeb393526d1f945912e42` | `yaf_ai/exploration/paired_feasible_{coordinates,agents,batch}.py` | 固定 exact nominal support 与 turn 分层闸门 |
| Stage A 表示消融 | `8348708e11be98973fd8a106ccad4053dfa1205a` | `artifacts/analysis/semifinal-feasibility-stratified-v2-stage-a/{report.md,summary.json}` | 200,000 solver-free draws；conditional 为 200,000/200,000 valid；`coverage_improved_all_turns` |
| Stage B exact-support 搜索 | `8fb865005791a3f1fa53d212d0f0a1e813f19558` | `artifacts/analysis/semifinal-feasibility-stratified-v2-stage-b/{report.md,appendix.json}`；十个 `semifinal-paired-stratified-v2-*` run | 10×600 unique accepted，0 valid、0 gate crossing；终点 `no_gate_crossing_observed_under_frozen_stratified_study` |

## E. B-parent A-only 条件补全终局链

| 冻结层 | 完整提交哈希 | 冻结路径 | 说明 |
|---|---|---|---|
| 预注册 | `9e9edbc762e8c885052aa08d469e6872b719d79e` | `docs/semifinal-paired-b-parent-conditional-completion-preregistration.md` | 冻结两个 B 父代、A-only exact support、20-run 矩阵、H1/H2 与停止规则 |
| 实现与门禁 | `d205ffcb26ac376071ca14b537a2db64402d30a2` | `yaf_ai/exploration/paired_b_completion_*.py`；`yaf_ai/analysis/paired_b_completion.py`；对应 scripts | 绑定源 blobs、映射、B 重放、config 与执行 commit |
| Solver-free support certificate | `f054240f09404ce978fe0dbcbb56bf1bf03a8d3d` | `artifacts/analysis/semifinal-paired-b-completion-v1-certificate/{report.md,summary.json}` | 480,002/480,002 spans、0 失败、0 solver calls |
| 20-run 矩阵与终局报告 | `e5f36fd971a7266531a6d124f553f121379ad889` | `artifacts/runs/semifinal-paired-b-completion-*`；`artifacts/analysis/semifinal-paired-b-completion-v1/{report.md,appendix.json}` | 20/20 completed、6,000 accepted、H1/H2=702/0；终点 `b_completion_pair_validity_without_effect_crossing`；裁决 `insufficient_evidence` |

终局最佳描述性记录：`semifinal-paired-b-completion-p01-es-s303` step 265 / proposal 265，pair hash `59a7e7df8fe7b8c3e6a07333e84ef12099886c5971a9815891ef63e1d041f259`，hardware hash `52cc0dfe93a241643f2089bbd67f4d674edede0dfd38617983d9841a530a302b`，worst reflected-power fraction `0.23010531242953516`。

### A-span 支持域因果探针附录

| 冻结层 | 完整提交哈希 | 冻结路径 | 说明 |
|---|---|---|---|
| 预注册 | `5a6e778f57d37511be7b442ef890024079d81f63` | `docs/semifinal-a-span-support-causal-probe-preregistration.md` | 冻结 10 个 ES-only 源筛选块、三档 A-span 剂量、32-call 上限与 counterfactual-only 边界 |
| 实现 | `5d5b7792f9f56931c435ec6661ae82b792f428e2` | `yaf_ai/exploration/a_span_probe.py`；`yaf_ai/analysis/a_span_probe.py`；`scripts/a_span_support_probe.py` | 实现来源门禁、630-geometry 证书、B/零剂量重放与固定剂量序列 |
| 文本身份门禁修正 | `b1ebf8ed578bde819d666c53fb418aa5d9812e9f` | `docs/semifinal-a-span-support-causal-probe-execution-note.md` | 数值执行前仅修正 Windows 文本 checkout 的 Git 身份比较；科学配置与证据原始字节规则不变 |
| 运行与归档 | `18b1d20d35ec1cb0c401bd951c64f202c3dd67bd` | `artifacts/analysis/semifinal-a-span-support-causal-probe-v1/{report.md,summary.json,dose-response.png}`；`artifacts/runs/semifinal-a-span-support-causal-probe-v1/` | 32/32 NEC2 subprocess；10/10 单调；p01/p02 各 5/5 跨冻结数值参考线；终点 `span_support_sufficient_in_frozen_counterfactuals`；裁决上限仍为 `insufficient_evidence` |

## F. 完整性、质量与决策链

| 项目 | SOURCE_HEAD 状态 |
|---|---|
| 当前 manifest | `artifacts/runs/manifest.json`，255 entries，SHA-256 `7f0d7d7d9797a6f3c0f0cdabee2e752092e4f9bc7b0c7ef683e47f8cf16d7f05` |
| 既有 QA 记录 | `archive_run.py --verify` 工作区与 fresh clone 均 255/255；pytest 795 passed；Ruff 通过；mypy strict 检查 165 个源文件且零错误。以上是此前执行并记录的结果，本纯起草会话未重跑 |
| 决策总账 | `DECISIONS.md` 共 109 行；末条日期 `2026-09-01`，内容为 A-span 探针的 Windows 文本 checkout 身份门禁修正 |
| 公开快照 | 新根历史；不含原 144 个提交的 commit/tree 时序及被排除的历史提示词、本机工具配置 blobs；`scripts/semifinal_public_snapshot_verify.py` 无求解器核验终局事实 |

### 历史快照说明

旧 `artifacts/analysis/semifinal-submission/evidence-index.md` 的“Full archive integrity 219/219”属于内部谱系标签 `ba53596f8191ec1a820ae7470349c89091a5bbe8` 所指时点，历史 manifest SHA-256 为 `cd6d8bd106ae6b7da478c836913a84511f1a484e55641e07f21cbe17013dfb8c`。它没有被改写；当前 255-entry 总账在原私有研究链中是 append-only 后继。由于公开仓主动舍弃原对象数据库，公开 Git 本身不证明该提交顺序，只验证当前总账与冻结终局文件。
