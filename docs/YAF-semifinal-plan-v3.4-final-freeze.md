# GOAI 赛道三·开放探索·YAF 复赛冲刺

版本：`v3.4-final-freeze`  
日期：2026-08-26  
状态：计划可冻结；当前数值执行仍为 `BLOCKED`  
官方截止：2026-09-03（北京时间）  
内部提交目标：2026-09-02 晚

## 0. 终审结论

主线、机制、评分和求解器不再更换。最终三项修正已经冻结：

1. 将 `G(h,u)` 中心线方程、顶点遍历和拒绝条件写死。
2. 人工基线使用固定整数微米表，不在运行时重新计算半波倍数。
3. ES-warm 的唯一父代、并列规则和提交顺序写死；人工基线 commit 必须早于 warm evaluate。

状态分层：

- 本文与 DECISIONS 提交后：`PLAN_FREEZE_READY`。
- G0-G6 未全过：`NUMERICAL_EXECUTION_BLOCKED`。
- G0-G6 全过：`READY_FOR_BASELINE_AND_COLD`。
- 人工基线归档并冻结父代后：`READY_FOR_WARM`。

聊天、临时脚本和口头判断均不能改变状态。

## 1. 一句话主线

YAF 先用双求解器审计收口“冻结自由形空间与预算下的静态单形态双频探索”，再把阴性结果转化为更贴近真实用途的新问题：同一套理想可伸缩 meander 硬件能否通过两个状态，分别服务 2.45 GHz 与 5.8 GHz，并超过同约束人工物理基线；候选只由 NEC2 冻结，openEMS 只做独立互证，全程由预注册 commit、JSONL、SHA-256 manifest 和 git 往返约束。

若静态收口出现候选级双频解，两状态研究称“问题扩展”；若未出现，才称“冻结空间、预算和种子下的阴性驱动问题修正”。有限搜索不表述为数学不可能性证明。

## 2. 复赛评分策略

- 45% 问题与环境：共享硬件、两个状态、冻结边界、强人工基线和机器闸门。
- 35% 研究信号：撤回、仪器缺陷拦截、静态阴性或反例、问题修正和新探索。
- 20% 可检查性：预注册、日志、manifest、独立互证和干净 clone 复验。

本周不接入 HFSS/CST/COMSOL，不让 LLM、Blender 或生成式视频产生物理数值。GPU 只用于确定性展示。

## 3. 现有证据边界

### 3.1 自由形静态分支

- r12 旋转一致性通过，但绝对锚点未释放。
- 半径匹配后 NEC2/openEMS 约 2.290/2.210 GHz，频差约 3.6%，相关约 0.889，未过锚点 `Delta f<=3%`、`Pearson>=0.9`。
- 候选 A/B 已终结；自由形 openEMS 历史耗时为小时级。

静态终局硬上限：

```text
absolute_anchor_released == false
=> final_verdict == insufficient_evidence
```

即使候选级 v2.1 项目全部通过，也只能写“候选级指标通过，但绝对锚点未释放”。先实现和测试 ceiling，再生成静态终局报告；不改既有归档字节。

### 3.2 meander 底座

- Day 5 top-1/top-2 已获 NEC2/openEMS 双原生求解器确认，历史频差约 1.18%，Pearson 约 0.955/0.953。
- 历史约 29 秒只属于旧 30 mm、2.4 GHz 设置，不能外推到 40 mm、5.8 GHz。
- 新实验只复用已审计的轴对齐中心线与 thin-box 分支；高频锚点、收敛、内存和耗时重新测量。

## 4. 新科学问题与机制

问题：在 40×40×40 mm 边界、单馈电、同一物理拓扑和不超过 3 个执行器自由度的约束下，同一套理想可伸缩 PEC meander 硬件，能否通过状态 A 在 2.40-2.50 GHz 工作、状态 B 在 5.725-5.875 GHz 工作，并在 NEC2 参照系中优于同约束人工可重构基线，随后经 openEMS 独立确认？

冻结机制：`ideal-symmetric-telescopic-PEC-meander-v1`。

### 4.1 共享硬件 `HardwareSpec h`

- `turn_count={3,4,5,6}`。
- `feed_gap_ratio=[0.02,0.06]`，状态间不变。
- `terminal_ratio=[0.0,1.0]`，状态间不变。
- `max_total_wire_length_um=100000`。
- `box_size_um=40000`。
- `wire_radius_um=50`。
- 对称双臂、馈电拓扑、连接、执行器布置和渲染映射共享。

模型外因素：套筒重叠区、接触电阻、材料损耗、机械应力和执行器体积。成果只称“理想可重构计算候选”。

### 4.2 两个状态执行器 `StateControl u`

1. `total_wire_length_um`：A `[50000,100000]`，B `[22000,45000]`。
2. `span_ratio_ppm`：A/B `[760000,1000000]`。

高度不是第三自由变量，`height_ratio` 分支明确禁用。

### 4.3 唯一中心线方程

长度换算为米后，只允许：

```text
gap = 0.040 * feed_gap_ratio
span = 0.020 * span_ratio
pitch = (span - gap/2) / (turn_count + 1)
horiz = (turn_count + terminal_ratio) * pitch
height = (((total_wire_length_m - gap)/2) - horiz)
         / (turn_count - 0.5)
```

正臂顶点遍历：

```text
feed edge: (-gap/2,0,0) -> (gap/2,0,0)
right start: (gap/2,0,0) -> (gap/2,height/2,0)
repeat turn_count times:
    x += pitch
    append (x,y,0)
    except after last horizontal segment: y=-y; append (x,y,0)
terminal: x += terminal_ratio*pitch; append only if increment>0
left arm: point reflection of every right-arm point through origin
```

任一条件触发 `rejected` 且不调用求解器：

- `height<=0`；
- `height/2>0.020 m`；
- `pitch<0.0015 m`；
- 任一段长 `<0.0002 m`；
- 节点超出 40 mm 边界；
- 重建总线长与请求值绝对差 `>1e-9 m`；
- 导线断开、自交、碰撞或馈电边错误。

不得沿用旧 30 mm 常量，不得启用 `height_ratio`，不得改用另一套折线。

## 5. 同一硬件的机器证明

```text
raw proposal
 -> frozen quantization
 -> immutable HardwareSpec
 -> StateControl A/B
 -> geometry and hashes from same objects
```

- 长度量化为整数微米；无量纲比量化为整数 ppm。
- JSON 使用 UTF-8、字段排序和固定分隔符；冻结 schema 与 quantization version。
- A/B 引用同一个 `HardwareSpec`，禁止分别构造共享字段。
- 必须 `hardware_hash(A)==hardware_hash(B)`。
- 必须 `state_geometry_hash(A)!=state_geometry_hash(B)`。
- 共享字段有任何字节差异，在 solver 调用前拒绝整对提案。

## 6. 21 点离散轨迹审计

- 在归一化的两个执行器空间对 `u_A -> u_B` 线性插值 21 点，包含端点。
- 每点使用第 4.3 节同一生成器，检查边界、节距、短段、连接、自交、碰撞、馈电和行程。
- 记录全轨迹最小净空、最小节距、最小高度和相邻状态最大节点位移。
- 只称“21点离散审计”，不称连续运动数学证明。
- 非法提案不消耗 solver budget。
- `max_consecutive_rejections=100`。
- `max_total_proposal_attempts=6000`；达到上限时以 `insufficient_feasible_proposals` 终止。

G4 纯几何见证至少证明：存在一个共享硬件可生成合法 A/B 端点及21点路径；人工36个硬件中至少一个具有非空合法 pair 池。否则停止并另行预注册空间。

## 7. 探索期唯一评分

### 7.1 唯一主档

每个 paired evaluation 只运行两次 NEC2：

```text
state A: 2.400e9 ... 2.500e9 Hz, 101 equally spaced points, lambda/20
state B: 5.725e9 ... 5.875e9 Hz, 101 equally spaced points, lambda/20
```

分段上限按各目标带上边界计算。完整频点、S11、分段档和 solver mode 写入 JSONL。

FoM、base/search score、ES适应度、人工基线和三臂主排名、L主档、候选冻结全部只读这两张曲线。宽扫、lambda/40和openEMS不得回写。

### 7.2 选点与 `valid_search()`

在完整101点数组取全局最小，并列取最低频；不预裁边或二次裁边。

```text
i = argmin(S11[0:101])
S11_selected = S11[i]
valid_search = (3 <= i <= 97) AND (S11_selected <= -6 dB)
```

openEMS、Pearson、跨求解器频差和1×/2×移动不得进入探索有效性、分数或排序。

### 7.3 分数与资格池

```text
FoM_A = 1 - 10^(S11_A_selected/10)
FoM_B = 1 - 10^(S11_B_selected/10)
base_score = min(FoM_A,FoM_B)
valid_pair_search = valid_search(A) AND valid_search(B)
search_score = base_score + 0.25*valid_pair_search
```

- ES适应度只用 `search_score`。
- 候选排序只用 `base_score`。
- 某臂存在 valid pair 时，只在 valid pool 排名；否则选最高base score诊断对象并取消正向资格。

### 7.4 效应量、稳健性和增益

```text
L = max(10^(S11_A_selected/10),10^(S11_B_selected/10))
L_candidate <= 0.90*L_manual
G_candidate,state >= G_manual,state - 0.5 dB
```

10%反射功率降低约0.46 dB，只是最低门槛。lambda/40只对冻结对象以相同两段101点复算，检查改善方向，不重排。增益使用有效全局最小频点的lambda/20 realized gain；无有效谐振自动失败。半波偶极子 `2.15 dBi +/-0.3 dB` 只作增益链闸门。

## 8. 固定人工物理基线

共享硬件网格：

```text
turn_count={3,4,5,6}
feed_gap_ratio_ppm={20000,40000,60000}
terminal_ratio_ppm={0,500000,1000000}
```

共36个共享硬件，字段升序决定 `hardware_grid_index`。

状态网格只读固定整数表：

```text
A_length_um={52005,61182,70359,79537}
B_length_um={22000,25844,29721,33597}
span_ratio_ppm={760000,880000,1000000}
```

半波参考频率 A=2.45 GHz、B=5.80 GHz，仅用于生成上表；运行时禁止重新计算、钳位、删除或扩充。

```text
36*(12 A states + 12 B states)=864 single-state NEC2 sweeps
=432 paired-evaluation equivalents
```

每个硬件缓存24条状态曲线，再对12×12组合做纯几何轨迹审计，不增加求解次数。pair索引按 `(hardware_grid_index,A_length,A_span,B_length,B_span)` 升序。

## 9. 三臂与 ES-warm 唯一父代

- Random：同空间、同 paired budget。
- ES-cold：只与Random做三种子描述比较。
- ES-warm：只提高发现率，不证明算法优越。

固定顺序：

1. G0-G6全过后，人工基线、Random、ES-cold可启动。
2. 人工基线完成后必须先归档、verify并提交。
3. warm父代先限制为通过21点审计的合法pair；若存在valid pair，只在valid pool选最高base score，否则选最高base score诊断pair。
4. 并列按 `hardware_hash`、`hardware_grid_index`、`pair_grid_index` 升序。
5. 三个warm seed共享一个父代；父代run id、hardware hash、A/B state hash、网格索引和人工基线commit hash写入config并进入config hash。
6. 人工基线commit必须早于任一warm evaluate；禁止使用Agent或openEMS结果回写父代。

## 10. 当前仓库必须实现的环境

新增独立 paired-state 模块；禁止包装旧 `evaluate_dual_band_metrics()` 冒充两状态环境。

必须实现：HardwareSpec/StateControl/PairedProposal/PairedMetrics、唯一方程生成器、量化和双哈希、A/B scorer、21点审计、runner、恢复状态、JSONL、锚点闸门、归档映射和静态day65 ceiling。

强制测试：

1. A/B只用各自NEC2目标带。
2. 旧dual-band scorer抛错时paired scorer仍工作。
3. `valid_search`不读openEMS。
4. lambda/40不能重排。
5. hardware hash相同、state hash不同。
6. 共享字段差异在solver前拒绝。
7. 21点审计与rejection零budget。
8. 锚点未释放时evaluations_completed为0。
9. 静态协议全真但锚点未释放时仍为insufficient_evidence。
10. 候选顺序确定。
11. 中心线公式逐字段已知答案测试且height_ratio不可达。
12. 固定网格恰有36个h、12个A、12个B和864次单状态评估。
13. warm父代只能来自更早的人工基线commit。

另做mock集成：三臂各2个pair，验证频段、日志、恢复、solver mode和openEMS零选择泄漏。

## 11. 候选冻结

openEMS候选输出产生前，仅按归档NEC2日志冻结：top-ES、top-Random、人工基线。

```text
valid_pair_search eligibility first
 -> base_score descending
 -> hardware_hash ascending
 -> run_id ascending
 -> step ascending
```

无valid pair时只选诊断对象并取消正向资格。三类×A/B固定为6条openEMS曲线；不得追加候选，openEMS不得改变候选。

## 12. 5.8 GHz 仪器合格证

- run family：`semifinal-wifi58-meander-renderer-anchor-r1-*`。
- 物理拓扑：5.800 GHz直线半波偶极子；端到端中心线长度 `0.0258441774 m`。
- feed gap `0.000600 m`；每臂长度 `(0.0258441774-0.000600)/2`。
- y轴；边顺序为馈电间隙、正臂、负臂；节点、边和几何SHA-256冻结。
- `anchor_topology=straight_half_wave`描述物理；`antenna_class=meander_dipole`仅强制走 `_build_meander_wire_xml` thin-box分支；专用anchor builder不得进入候选空间或调用旧30 mm validator。
- 禁止generic wire和freeform sphere-ended Wire。
- NEC2半径0.05 mm，不启用EK；openEMS映射逐字段冻结。
- 两求解器相同1.5-6.5 GHz/251点。

全部放行：双方有效内部极小且S11<=-6 dB、频差<=3%、Pearson>=0.9、openEMS 1×→2×移动<=3%，并记录网格线、单元数、单元尺寸、峰值内存和耗时。

锚点只证明高频渲染器；候选仍须做相邻网格检查。失败时 `anchor_released=false`，正式入口零评估退出。

薄线回归：lambda/40@5.8 GHz约1.29 mm；除以0.05 mm约25.9，不授权EK。

## 13. 独立互证与正向发现

冻结状态使用1.5-6.5 GHz/251点。每状态要求：v2.1有效内部极小、S11<=-6 dB、NEC2/openEMS频差<=5%、Pearson>=0.8。深度差只记录。

对一个预注册候选先做openEMS 1×→2×；移动>3%则 `instrument_not_converged / insufficient_evidence`，不得继续加密试到通过。

正向发现还须满足：两状态互证全过、NEC2主档L改善>=10%、lambda/40方向保持、两状态增益护栏通过、21点轨迹通过、归档与git往返通过。

## 14. 预算与矩阵

```text
t_pair = NEC2 A-band 101-point sweep
       + NEC2 B-band 101-point sweep
       + validation and JSONL overhead
```

预飞20个合法pair，取P95并原样归档。

```text
agents={random,es-cold,es-warm}
seeds={101,202,303}
runs=9
raw_budget=floor(0.70*T_window_seconds*parallel_workers
                 /(9*t_pair_P95_seconds))
budget=min(300,raw_budget)
```

- budget>=200：三种子描述统计。
- 80<=budget<200：探索性小样本。
- budget<80：不运行9-run，记录 `infeasible_within_submission_window`。

不得把raw budget抬到200。正式预注册保存T_window、worker、20个耗时、P95、raw budget和最终整数。

## 15. 放行闸门

| 闸门 | 必须证据 | 未过动作 |
|---|---|---|
| G0 | 本文与DECISIONS commit早于新数值运行 | 禁止运行 |
| G1 | paired scorer、唯一频点表、NEC2-only valid、公式测试全绿 | 禁止运行 |
| G2 | HardwareSpec、双哈希、21点审计全绿 | 禁止运行 |
| G3 | 静态day65 ceiling代码与测试全绿 | 禁止静态终局报告 |
| G4 | 固定微米网格与纯几何见证通过 | 禁止数值运行 |
| G5 | 高频锚点与1×/2×通过 | 正式入口零评估退出 |
| G6 | pytest、ruff、mypy strict、manifest verify全绿 | 禁止baseline/cold |
| G7 | 人工基线归档commit和父代冻结 | 禁止ES-warm |

## 16. 日程（北京时间）

### 8.26

- 本文与DECISIONS作为G0独立commit；不提交settings.local或初赛草稿。
- 记录pytest/ruff/mypy、manifest和git allowlist。
- 先实现G3 ceiling；不运行两状态solver。

### 8.27

- 实现paired-state环境、唯一方程、scorer、双哈希、轨迹、锚点闸门和13项测试。
- 完成纯几何G4与mock集成，不调用真实solver。

### 8.28

- 跑高频锚点和1×/2×；跑20个paired预飞。
- G0-G6通过后提交 `READY_FOR_BASELINE_AND_COLD`。
- 运行人工基线、Random、ES-cold。
- 人工基线先归档提交并冻结父代，再提交 `READY_FOR_WARM`，启动ES-warm。

### 8.29

- 完成Agent runs；仅按NEC2冻结三类对象并先提交。
- 完成候选网格检查和固定6条openEMS曲线。
- 生成YAF-M1候选卡或负结果卡。

### 8.30

- 无条件停止新增科学实验；未完成项标in-progress。
- 不重试、不换候选、不改阈值；转入报告和复现。

### 8.31-9.1

- 全新clone完成install、锚点、mock/小批量demo和manifest verify。
- Blender只由归档参数重建两状态。
- 完成报告、README、部署、许可证、LLM分工和视频。

### 9.2

- 代码冻结、tag、工作区与clone双重verify；晚间提交。

## 17. 提交与证据纪律

建议提交：

1. `Pre-register paired-state meander equations, scoring, and release gates`
2. `Add paired-state meander environment with auditable hardware identity`
3. `Qualify the 5.8 GHz instrument and freeze the semifinal budget`
4. `Archive the manual reconfigurable baseline and freeze the warm-start parent`
5. `Run semifinal paired-state meander exploration`
6. `Cross-check frozen semifinal candidates and publish analysis`
7. `Package reproducible semifinal submission`

Random用 `baseline-random`；ES、人工基线和锚点用现有 `other`，note明确agent/baseline/anchor。禁止未经审查的 `git add -A`；不提交 `.claude/settings.local.json` 和初赛草稿；既有artifacts零字节改动；新证据执行工作区与全新clone双重verify。

## 18. 止损与措辞

- 几何见证失败：停止并另行预注册空间。
- 高频锚点失败：`instrument_not_converged / insufficient_evidence`。
- 无valid pair：写“当前空间与预算下未发现有效两状态候选”。
- Agent不胜人工：写强人工模板胜出，不改效应量。
- openEMS失败：写清频段和门槛，不换候选。
- 全过：称“YAF发现的两状态可重构天线计算候选YAF-M1”。
- 禁止称“首次发明”“自主自适应天线”或“已可制造天线”。传感闭环、更多求解器和实物验证只进决赛路线图。

## 19. 最终交付物

1. 10分钟可运行的最小环境与demo。
2. 预注册commit链、日志、manifest和clone往返证据。
3. 人工基线、Random、ES-cold、ES-warm公平对照。
4. YAF-M1候选卡或负结果卡，含hardware hash、两状态参数、21点轨迹、曲线、互证和局限。
5. 技术报告、证据索引、README、部署与合规披露。
6. 归档参数驱动动画，并声明展示不参与科学判定。

本版本之后停止计划迭代。后续审计只检查实现是否符合本文，不再重开科学对象、方程、评分、网格、父代、候选或阈值。结果异常只能触发预注册止损或新的后续研究，不得修改本计划迁就结果。
