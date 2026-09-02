# YAF 真实状态报告（HONEST_STATUS）

> 这份文档刻意不美化。如果你看到 README 的 6 条验收命令全绿就以为
> 系统已经能"发明天线"，请先读完这份文件。**仓库当前状态是"可演示的脚手架 +
> AI 训练管线"，距离"能跑真实电磁仿真、能产出可制造的新天线"还有相当的距离。**

写作日期：2026-05-21。所有论断都对应到具体源码行号，可以核对。

> **2026-07-05 更新**：本文档写作后仓库做了以下改动，部分论断已过时：
> 1. **§1.1 的 induced-EMF 近似公式已替换为正确的 Balanis (8-60a)/(8-61a) 实现**
>    （`NEC2Adapter.dipole_impedance_induced_emf`，用 scipy Si/Ci 积分）。半波偶极子
>    现在给出教科书值 73.1 + j42.5 Ω（已知答案测试锁定，±2%）。demo 输出从
>    S11=−2.60 dB / VSWR=7.83 变为 S11≈−10.5 dB / VSWR≈2.2 —— 之前的公式是错的。
>    注意：**gain=2.15 dBi 仍是硬编码**，且该模型仍只对直线偶极子有效。
> 2. **A3（fallback 收口）已实现**：所有结果带 `solver_metadata["solver_mode"]`
>    （`native`/`subprocess`/`fallback_analytical`），fallback 结果带显式 warning；
>    `YAF_NO_FALLBACK=1` 时缺求解器直接抛 `SolverUnavailableError`。
> 3. **§5 的测试盘点已更新**：新增 `tests/unit/test_known_answers.py`（8 个用例，
>    含偶极子阻抗对教科书值、fallback 标注契约、严格模式抛错）。
> 4. 修复 ruff 全量扫描发现的 2 个 F821 真 bug（`bayesian.py` 缺 `import sys`、
>    `vector_store.py` 缺 `import numpy`）；全仓 ruff 清零。

> **2026-07-29 更新：NEC2 subprocess 路径现在是真的了。** 本文档 §1.1 对
> subprocess 路径的评价（"代码路径存在但从未被走过"）当时还是乐观了——
> 实际比那更糟：旧 `_parse_nec_output` grep 的关键字 `INPUT IMPEDANCE` /
> `MAX GAIN` 在 nec2c 输出里**出现 0 次**（那是原版 NEC-2 的措辞），所以即使
> 装了 nec2c，它也会永远静默返回硬编码的 73+j42.5 Ω / 2.15 dBi，且 S11 频扫
> 用余弦模型伪造、远场硬编码偶极子公式。本次改动：
> 1. 新增 `output_parser.py`：按频率块解析真实 nec2c 输出（ANTENNA INPUT
>    PARAMETERS 表的逐频点阻抗 → 真实 S11(f)；RADIATION PATTERNS 表 →
>    真实远场与峰值增益；POWER BUDGET → 真实效率）。解析不到必需数据抛
>    `NEC2ParseError`，绝不静默用默认值。
> 2. 修了 4 个卡片/输入生成 bug：RP 卡多一个字段导致 nec2c 把远场请求解析
>    成近场模式（实测确认）；`_build_nec_deck` 丢弃 `gw_card` 返回值导致
>    mesh 几何从未写入输入文件；GE/GN 地面语义写反（自由空间误挂了
>    εr=13 的有限地）；GW 坐标 %.4f 定点格式在 >3 GHz 时把线径截断为 0。
> 3. `health_check` 不再在异常时返回 True。
> 4. `tests/fixtures/nec2/` 收录真实 nec2c 输出（偶极子 11 点扫频 + 3 单元
>    八木），`test_nec2_real_output.py` 19 个用例：290 MHz 谐振 71.96−j0.21 Ω、
>    增益 2.15±0.1 dBi、八木 8.57 dBi 指向引向器、前后比 >5 dB。端到端
>    3 用例需要 nec2c（本机 Windows 跳过，已在 WSL 全绿）。
> 5. CI 的 test job 现在 `apt-get install nec2c`——端到端真实求解每次必跑。
> **§7 评级更新：任一求解器的物理可信度 D → B（NEC2 线天线路径已真实，
> openEMS 仍是 fallback；fallback 路径的局限不变）。**
>
> **2026-07-29 补充（第二批）：**
> 1. **WSL 桥接**：Windows 主机上 `nec2c` 不在 PATH 时，adapter 自动探测
>    WSL 内的 `/usr/bin/nec2c` 并做路径翻译（`C:\...` → `/mnt/c/...`）。
>    本机 `demo_dipole.py` 现在实跑 MoM（`solver_mode=subprocess`，0.12 s），
>    S11=−8.1 dB / VSWR 2.63 / 增益 2.21 dBi @ 2.45 GHz——真实物理。
>    结果元数据带 `runner` 字段区分 native/WSL 调用。
> 2. **几何诚实化**：`NEC2Adapter.mesh()` 现在**拒绝纯面片几何**（抛
>    `MeshError`）——旧行为把三角形截成"前两个顶点的线"，生成互相重叠的
>    伪导线，结果看着合理实则无意义（demo 曾因此给出 VSWR 592）。线天线
>    必须用 2 节点边表示；面片几何请走 openEMS。demo 和已知答案测试已
>    改为线几何。
> 3. **`FarFieldResult.gain_dbi()` 从伪公式改为真实方向性积分**：旧实现
>    `10·log10(|E|²/2η) + 2.15` 中 +2.15 是无物理依据的硬编码偏置；新实现
>    D = 4πU/P_rad，P_rad 由方向图在球面上数值积分（单 φ 切面假设旋转
>    对称）。交叉验证测试：积分结果与 nec2c 自报增益一致（±0.2 dB）。
> 4. 已知局限：单 φ 切面的旋转对称假设对非旋成体天线只是近似；WSL 桥接
>    首次探测有 ~1 s 开销（已缓存）；openEMS 在 Ubuntu 24.04 官方源中无
>    包，真实 FDTD 路径需源码编译或 Docker（下一阶段）。
>
> **2026-07-30 更新（第三批）：openEMS FDTD 真实路径打通。**
> 1. 官方 v0.0.36 Windows 二进制装于 `C:\opt\openEMS`；适配器新增
>    subprocess 路径：`xml_writer.py` 生成完整仿真 XML（FDTD 段 +
>    RectilinearGrid + LumpedPort 按官方展开为 LumpedElement/Excitation/
>    双 ProbeBox），`openEMS.exe` 直接运行，`port_parser.py` 解析端口
>    时域探针 → DFT → S11/Zin。数学与官方 `Port.CalcPort` 逐点对照
>    （fixtures 锁定，max |ΔS11| < 0.02）。
> 2. **验证链**：官方 Python API 参考跑（0.5 m 偶极子）→ 275 MHz /
>    R=71.8 Ω / S11 −15.2 dB；自研 XML 路径 → 275 MHz / 71.2 Ω /
>    −15.1 dB。**双求解器交叉验证测试**：同一几何 NEC2(MoM) vs
>    openEMS(FDTD)，谐振频率一致性 <10%（实测 ~5%，物理原因：FDTD
>    线模型有效半径更粗）——两套独立数值方法、独立代码库互证。
> 3. **清除两处旧伪造**：native 路径的 `_parse_openems_results` 曾返回
>    mock 正弦 S11、`_compute_far_field_approx` 曾编造 sin(θ) 方向图并
>    标为 native——已删除。subprocess 结果的 far_field/gain/efficiency
>    诚实置 None（NF2FF 后处理未实现，是下一步）。
> 4. 局限：subprocess 路径当前只支持线类几何（2 节点边）；面片/贴片
>    几何仍走标注 fallback；NF2FF（增益/方向图）未接；CI (ubuntu) 无
>    openEMS 二进制，端到端测试仅在本机跑（fixture 测试 CI 照跑）。
> **§7 评级更新：任一求解器的物理可信度 B → B+（线天线类 MoM+FDTD
> 双真实互证；贴片/面片类和远场增益仍缺）。**

> **2026-08-04 更新（第四批）：openEMS 贴片天线真实路径打通。**
> 1. 自研 XML 路径新增参数化微带贴片支持：`_build_patch_xml` 生成
>    PEC 贴片 + 有耗介质基板（`add_material_box`，κ=tanδ·ω·ε₀·εr）+
>    PEC 地板 + 垂直探针 LumpedPort 的完整仿真文件。识别依据是
>    `ParametricGenerator.rectangular_patch` 附带的 metadata
>    （width/length/substrate_thickness/eps_r/loss_tangent/feed_x，
>    本批为此扩展了生成器签名，向后兼容）。
> 2. 网格策略对齐官方：贴片边缘 thirds rule（1/3 内 2/3 外）、基板
>    z 向 4 格、`smooth_lines`（官方 SmoothMeshLines 的简化移植：
>    固定线间从两端按 1.4 比例几何级数平滑填充）。
> 3. **验证**：与官方 Python API 在同一天线（教程 32×40 mm 贴片，
>    εr=3.38）上的 fixture（`patch_s11.csv`）对照——官方
>    −17.79 dB @ 2.440 GHz，自研路径 −16.31 dB @ 2.420 GHz
>    （谐振偏差 0.8%，全频段 max |ΔS11| = 0.06），端到端测试锁定
>    （谐振 ±3%、逐点包络 0.15）。
> 4. 局限：NF2FF（增益/方向图）仍未接，far_field/gain 继续诚实置
>    None；基板损耗 κ 按频带中心一点取值（非色散模型）；显示网格
>    仍是旧的三角面片（求解走 metadata 参数化重建，两者馈电形式
>    不同——显示是 inset、仿真是探针）。
> **§7 评级更新：B+ → A−（线天线 MoM+FDTD 互证 + 贴片 FDTD 对官方
> API 锁定；远场增益路径仍缺）。**

> **2026-08-04 更新（第五批）：NF2FF 远场路径打通，far_field/gain 不再
> 缺席。**
> 1. 自研路径新增 NF2FF 后处理三件套：`xml_writer.add_nf2ff_box`
>    （六面 E/H 时域 DumpBox，按官方默认缩进边界 2 格）、
>    `nf2ff.py`（nf2ff.exe 控制 XML 生成 + 调用 + 结果 HDF5 解析，
>    格式逐项对照 v0.0.36 源码 CalcNF2FF.m/nf2ff.cpp）、adapter
>    `_post_process_far_field`（谐振点或指定频点变换 →
>    FarFieldResult + G = D·e_rad）。
> 2. **格式验证**：同一批面 dump 上，本路径驱动 nf2ff.exe 的输出与
>    官方 python API（Cython _nf2ff）**逐点位相同**（Dmax/Prad/E 场
>    max 相对差 0）。fixture：patch_nf2ff.h5 + patch_farfield.csv。
> 3. **端到端验证**（教程贴片，全自研 XML + openEMS.exe + nf2ff.exe）：
>    增益 6.70 vs 官方 6.60 dBi、辐射效率 0.948 vs 0.949、方向性
>    6.94 vs 6.82 dBi、方向图归一化形状差 <12%；且
>    `FarFieldResult.gain_dbi()` 球面积分与官方 Dmax 一致（±0.3 dB），
>    远场三条独立链路（官方引擎 Dmax / 我们的积分 / 端口功率效率）
>    互证。
> 4. 端口 DFT 归一化从任意 dt 改为官方单边谱 2·dt（S11/Zin 比值
>    不受影响），使 p_in 与 nf2ff 的 Prad 同尺度——效率才是真的。
> 5. 诚实契约不变：远场只在 `spec.far_field_request` 显式请求时记录
>    （近场 dump 让 FDTD 慢数倍）；未请求或 nf2ff 失败 → far_field
>    诚实置 None，失败原因进 `solver_metadata["nf2ff_warning"]`。
> 6. 顺手修复：WSL 探测的 UTF-16 输出在 GBK 控制台下炸 reader 线程
>    （改二进制捕获 + 显式 utf-8 解码）。
> **§7 评级更新：A− → A（S 参数 + 远场增益/效率全链路真实、对官方
> API 锁定；剩余缺口：面片类任意几何、色散材料、CI 无 openEMS
> 二进制故端到端仅本机跑）。**

> **2026-08-04 更新（第六批）：AI 逆向设计管线接上真实物理 oracle；
> 修复一个会产出"完美假结果"的序列化精度 bug。**
> 1. §3 "verify 用的是 fallback 解析"已不成立：`_verify` 现在按求解
>    器能力挑候选（贴片 metadata → openEMS FDTD；2 节点线 → NEC2，
>    缺 nec2c 时走 openEMS），设计目标含增益/效率时自动请求 NF2FF；
>    逐候选真仿真打分取最优。`converged` 判定新增硬门槛：
>    `oracle_mode ∈ {subprocess, native}`——fallback 解析分数永远
>    不能宣布"设计收敛"。`PipelineResult.oracle_mode` 显式暴露。
> 2. 参数化生成改为求解器可算的表示：偶极子发 2 节点线几何
>    （谐振感知 0.475λ±10%），贴片按 Balanis 设计方程在 FR-4 上
>    定尺寸（实测：设计 2.45 GHz → FDTD 谐振 2.36 GHz，闭式公式
>    ~4% 偏差，正是管线迭代要收的差距）。集成测试
>    `test_pipeline_real_physics_oracle` 锁定闭环（生成 → 筛选 →
>    真 FDTD 验证，oracle_mode=="subprocess"）。
> 3. **序列化精度 bug（该测试首跑当场抓到的真 bug）**：图元坐标
>    用 %.6e（7 位有效数字）而网格线用 %.12g（12 位），无理数馈电
>    坐标被截断后离网格线 7.6e-11 m——openEMS 找不到激励边，全程
>    零能量，S11≡0，VSWR=1.0，"完美匹配"实为空仿真。教程整数
>    坐标恰好 7 位可表示，故此前从未暴露。修复：图元与网格线同用
>    %.12g。**新增诚实守卫**：`calc_port` 遇全零电压探针直接抛
>    `OpenEMSParseError`，此类坏仿真从此不可能再冒充成功。
> 4. 遗留：VAE 像素几何仍无真实求解器支持（verify 中排序靠后，
>    需要真 oracle 时用 generator="parametric"）；喇叭/螺旋/分形
>    同样只有标注 fallback。

> **2026-08-04 更新（第七批）：AI 助手升级为智能体（DeepSeek function
> calling → 真实求解器）。** `/api/v1/chat` 现在带三个工具：
> simulate_patch / simulate_dipole（直连 openEMS/NEC2）、
> run_inverse_design（完整管线）。诚实契约延伸到对话层：每个工具
> 结果都带 solver_mode，fallback_analytical 会附加"必须告知用户是
> 解析估算"的强制提示，系统提示词禁止 LLM 引用工具没返回过的数字。
> 注意：LLM 遵守提示词是概率性的，不是保证——数值的最终权威永远
> 是工具返回的 JSON，前端工具活动行让用户能看到真仿真是否发生。
> 智能体循环由假 DeepSeek 端点测试锁定（test_chat_agent.py）。

> **2026-08-05 更新（第八批）：CI 集成 openEMS——端到端物理测试
> 上云。** ci.yml 的 test job 现在从源码构建 openEMS v0.0.36
> （--disable-GUI，与全部 fixture 同版本），actions/cache 缓存产物
> （首建 ~15 分钟，命中后秒级恢复），`YAF_OPENEMS_EXE` 指向构建
> 产物。此前仅本机可跑的 30+ 端到端用例（贴片谐振、NF2FF 远场、
> 管线真 oracle、智能体工具、MoM×FDTD 交叉验证——nec2c CI 里早已
> 有）将在每次 push 全量执行。
> **配方验证方式（诚实声明）**：在与 CI 同发行版的 WSL Ubuntu
> 24.04 上完整实测——apt 依赖 → 全量克隆 v0.0.36 → 构建 → 用
> Linux 二进制跑自研 XML：S11 −15.3 dB @ 275 MHz、nf2ff Dmax
> 2.25 dBi，与 Windows 二进制/官方 API 参考一致。途中发现并修正
> 一个配方坑：浅克隆（--depth 1）无标签导致 CSXCAD 的
> `git describe` 版本推导炸掉，故 CI 用全量克隆。**workflow 本身
> 的 Actions 运行尚未发生**——仓库还没推到 GitHub，首次真实运行
> 要等首次 push；语法已校验，配方已在同版本系统实证。

> **2026-08-06 更新（第九批）：像素几何真验证、主动学习闭环、
> Lorentz 色散基板。**
> 1. **平面面片 → FDTD 像素化路径**：任意平面金属面片（VAE 像素、
>    印刷螺旋、分形）光栅化到 Yee 网格（逐三角形重心测试 + RLE 行
>    合并），置于参数化基板+地板+探针馈电（arXiv:2505.18188 的
>    pixel-patch 架构）。已知答案锁定：教程贴片以"生面片"输入该
>    路径 → 谐振与官方 fixture 一致（±4%，像素量化误差）。馈电
>    吸附像素网格线（避免 runt cell）；图元坐标与网格线同表达式
>    生成（%.12g 一致性，第六批 bug 的教训）。局限：喇叭等非平面
>    面片仍拒绝（需要波导端口）→ 标注 fallback。
> 2. **主动学习（管线第 6 步）从空箭头变真反馈**：GP+EI
>    （BayesianOptimizer ask/tell）在贴片设计空间 (f_ratio,
>    feed_ratio) 上学习，**只吃 subprocess/native 真实分数**，
>    fallback 分数永不入库；`oracle_observations` 显式计数。单元
>    测试锁定提议器向合成最优收敛（均值距离 <0.05 vs 均匀 ~0.09）。
> 3. **色散基板**：Drude/Lorentz 一阶极点（XML 属性
>    EpsilonPlasmaFrequency_1 等，Hz 单位，对照 CSXCAD
>    ReadFromXML + openEMS operator_ext_lorentzmaterial 源码）。
>    判别性已知答案：εinf=2.5 + 30 GHz 极点调至 ε(2.44GHz)≈3.38，
>    FDTD 谐振落在 fixture 位置（引擎若忽略色散会跑到 ~2.8 GHz）。
>    **Debye 显式拒绝**：openEMS v0.0.36 引擎无 Debye 扩展，CSXCAD
>    描述会被 FDTD 内核无声忽略——拒绝而不伪装。
> 4. 集成测试实录：分形候选经像素路径真 FDTD 验证（16 s，
>    oracle=subprocess）——生成器家族中除喇叭外全部接入真实物理。

---

## 1. 求解器适配器：哪些是真的，哪些是 mock

### 1.1 NEC2 (`yaf_solvers/nec2_adapter/`)

| 项 | 状态 |
|---|---|
| **NEC 卡片生成 (`card_writer.py`)** | ✅ **真实**：GW/GE/GN/EX/FR/RP/LD 卡片按 NEC-2 格式正确发出。可以喂给 xnec2c 或 nec2c。已有 3 个单元测试覆盖 dipole/loop/yagi 卡片字符串。 |
| **subprocess 调用 `nec2c`** | ⚠️ **代码路径存在但当前从未被走过**：`adapter.py:122-138` 调用 `nec2c -i ... -o ...`，如果二进制不存在就 `except FileNotFoundError` → fallback。当前 Windows 主机没装 `nec2c`，所以**每次都走 fallback**。 |
| **fallback `_compute_analytical` (`adapter.py:255-319`)** | ❌ **不是 MoM**：这是一段感应电动势法（induced EMF）近似，用 `R_r = 60·(Si term·sin(kL) + Ci term·cos(kL))` 闭式估辐射阻抗，远场图固定为标准半波偶极子方向图，**增益硬编码为 `gain_dbi=2.15`**（`adapter.py:315`）。对于"喂入一个不是偶极子的几何（比如 Yagi、贴片、螺旋）"这条路径会给出**完全错误的物理结果**，但不会报错。 |
| **`_parse_nec_output`** | ⚠️ 字符串 grep `INPUT IMPEDANCE` / `MAX GAIN` 之类的关键字，模式脆弱，没有针对真实 nec2c 输出做过单元测试。 |

**`scripts/demo_dipole.py` 的输出（S11 ≈ −2.60 dB，gain = 2.15 dBi，VSWR = 7.83）是 `_compute_analytical` 算出来的，不是真正的 MoM 仿真。** 输出形状对得上半波偶极子的常识值，但 VSWR=7.83 表明阻抗匹配很差，是闭式公式在自由空间假设下的结果，并不能用来判定真实天线设计的可行性。

### 1.2 openEMS (`yaf_solvers/openems_adapter/`)

| 项 | 状态 |
|---|---|
| **CSXCAD XML 序列化 (`to_native_format`)** | ✅ 真实：发出有效的 `<ContinuousStructure>` XML，但只导出 metal box，不带网格指令/NF2FF/激励，**只是几何而不是完整 CSX 工程**。 |
| **`_run_with_openems_api` (Python 绑定)** | ⚠️ 代码路径存在，依赖 `import openems` + `import CSXCAD`。当前主机两个包都没装，所以**每次走 fallback**。即便能 import，里面的 `AddDump`/`AddLumpedPort` 调用还需要真实端口位置才不会出 ValueError。 |
| **fallback `_run_analytical`** | ❌ **简单 RLC 谐振模型**：`s11 = detuning/(detuning + 1j·0.1)` 是一阶谐振，完全不带几何依赖。max_dim 影响谐振频率 `f_res = c0/(2·max_dim)`，仅此而已。 |

### 1.3 MEEP / HFSS / CST / FEKO / COMSOL

全部是 **skeleton**，`solve()` 直接返回 `status="skeleton_not_implemented"`（5 个 `adapter.py` 共 ~17 行内容）。集成测试里它们不会被调到，所以不影响 45/45 pytest 绿。

### 1.4 `MaterialLibrary.get_dispersive_permittivity`

- Drude / Debye 闭式公式 ✅ 与文献一致
- Kubo 公式 (`_kubo_conductivity`) ⚠️ 只实现了 Hanson 公式的简化形式，没和参考实现（fdtdx 的 `dispersion.py` 或 gprMax 的多极模型）做过数值对照

---

## 2. demo_dipole.py：S11 / 增益是不是物理真值？

**不是。** 当前输出来自 §1.1 的解析降级路径：

- `Gain = 2.15 dBi` 是 `adapter.py:315` 的硬编码值。这是教科书半波偶极子的近似增益，所以"看起来对"，但**它不依赖你喂进去的几何**——即使把 dipole 改成八木天线或 MIMO 阵列，gain 还是 2.15。
- `S11 = −2.60 dB / VSWR = 7.83` 是 induced-EMF 近似在 2.4–2.5 GHz 上算出来的（`_compute_analytical` 第 277–290 行）。形状大体对，但绝对值不可信，**别拿这个去验证制造样品**。
- `Best S11: −2.60 dB @ 2.400 GHz / -10 dB bandwidth: not met` —— 这个"未达标"的结论也是 fallback 模型的特性，不代表真实偶极子做出来就达不到 −10 dB；现实里 73+j42 Ω 的半波偶极子 S11 通常能到 −10 dB 上下，取决于变压器。

**评级**：管线跑通 ✅，物理可信度 ❌。

---

## 3. AI 模块：可信度逐项标注

### 3.1 `yaf_ai/differentiable/diff_fdtd_jax.py` ★

- **能跑梯度 ✅**：本次会话修了两个 bug——之前源频率被设成 `f·dx/c = 1.0`，导致每步采样到 sin 的零点；`compute_s11` 读 `self.eps_r` 而不是传入的参数，所以 jax.grad 拿不到导数。两处都已修。
- **是不是真 FDTD？** 是 **2D TM 模式**的最小实现：Ez / Hx / Hy 在 64×64 网格上时进，PML 用解析衰减乘法（`ez_new = pml.ax * pml.ay * ez_new`，第 187 行）。这是一种简化的 PML，**不是真正的 CPML/UPML**，吸收性能比 fdtdx/ceviche 差很多。
- **demo 报告的"improvement 0.2%"** 说明梯度方向对，但 loss landscape 几乎平的——这套小网格 + 简化 PML 不适合做严肃的逆向设计。**它证明的是"管线可微"，不是"管线能算出真实天线"。**

### 3.2 `yaf_ai/generative/vae_designer.py` ★

- **架构 ✅**：标准 β-VAE，encoder/decoder 都是 MLP，`reparameterize` 正确。loss 从 260 降到 108，β=0.1。
- **训练数据 ❌**：完全用合成数据（`generate_dipoles` / `generate_patches` 是 numpy 画矩形+条带，**没有任何电磁性能标签**）。所以训完的 VAE 只学会"长得像 dipole/patch 的二值图"，不知道哪个真正性能好。
- **`generate()` 返回的样本**：fill factor 在 0.06–0.07 附近（demo 输出），看上去稀疏，没有 S11/增益评估。当前 pipeline 拿 VAE 样本走 `_screen_candidates`，但那个 _screen_candidates 用的也只是几何启发式（`compactness` 偏好）—— **整条 generation 链路尚未接入任何物理 oracle**。

### 3.3 `yaf_ai/surrogate/fno_solver.py` / `deeponet.py`

- 实现了 FNO/DeepONet 的结构，但 **没有训练**：模型权重是随机初始化。`predict_s11` 直接调推理。`pipeline.py:_screen_candidates` 当前**没有调用 FNO**，它走了一个 `compactness/n_faces` 启发式打分。所以 FNO 在管线里其实是死代码。

### 3.4 `yaf_ai/optimization/bayesian.py` ★

- 纯 NumPy 的 GP + EI，能在 2D 玩具问题上收敛（Branin / 偶极子长度调谐）。**和 BoTorch 没对照过**——botorch 装着也没用上，是参考资料而非依赖。

### 3.5 `yaf_ai/inverse_design/pipeline.py` ★

- **六阶段闭环**只是个示意流程：
  - generate（VAE 5 轮，见上）
  - screen（几何启发式，不是 FNO）
  - refine（可微 FDTD 20 步，2D TM 简化版）
  - topo（SIMP，可关）
  - verify（openEMS / NEC2，但实际走 §1 的 fallback）
  - composite_score（增益 + VSWR + efficiency 加权）
- `converged > 0.9` 的判据**几乎不会触发**（因为 verify 用的是 fallback 解析），所以管线总会在 max_pipeline_loops 用完时退出。`tests/integration/test_pipeline.py::test_pipeline_demo` 把 loops 设成 1，断言只是 `loop_count >= 1` 和 `len(all_candidates) > 0`，**没有任何物理判据**。

---

## 4. mypy --strict 通过的真实代价

`pyproject.toml` 里设置了：

```toml
[tool.mypy]
strict = true
warn_return_any = false
disallow_untyped_calls = false
disallow_subclassing_any = false
warn_unused_ignores = false
```

**注意：实际上 CLI `--strict` 把上面四个开关都重新打开了**（mypy 2.1 的行为）。它们在 pyproject 里之所以还留着，是为了**让不带 `--strict` 的 `mypy` 调用也能尽量贴近 strict** —— 不是真正的"降标"。验收命令 `mypy ... --strict` 跑过靠的是逐处加 `cast()` / `float()` / `complex()` / `np.asarray()` 把 `Any` 收窄掉，以及 `# type: ignore[no-untyped-call]` 标注 PyTorch `.backward()`。

### 4.1 `[[tool.mypy.overrides]]` 屏蔽的模块

```toml
module = [
    "OCC.*", "trimesh.*", "gmsh.*", "skrf.*",
    "openems.*", "CSXCAD.*", "necpp.*",
    "qdrant_client.*", "minio.*", "celery.*",
]
ignore_missing_imports = true
```

逐条评级：

| 模块 | 现状 | 评级 |
|---|---|---|
| `OCC.*` (pythonocc-core) | 上游无类型 stub，使用面很窄（只在 `_check_occ` 里 import 试探）| **无害** |
| `openems.*` | Cython 绑定，上游无 stub。代码 import 完只读 `_openems_available` flag。| **无害** |
| `CSXCAD.*` | 同 openems。| **无害** |
| `necpp.*` | C 绑定，上游无 stub。当前代码**没真正调用** necpp Python 接口，只是 `nec2c` subprocess。| **无害**（但应等真正用 necpp 时一起收紧）|
| `gmsh.*` | 上游有 stub，但版本多变；代码里没主动 import gmsh。`pyproject` 依赖列了但没用上。| **待收紧**（或者把 gmsh 从依赖里删掉）|
| `trimesh.*` | 上游 stub 不完整。代码用 `trimesh.creation` 等 API。`types-trimesh` 不存在。| **待收紧** —— 应该把 trimesh 调用收到一个薄 wrapper 里、wrapper 显式 annotate 返回值。|
| `skrf.*` | scikit-rf 自带 `py.typed` 标识，但 mypy 仍然不完美。当前仓库只在 `SParamResult.from_touchstone` 一处用到。| **待收紧** —— 关键路径，应至少给 `skrf.Network` 写一个 minimal stub。|
| `qdrant_client.*` | 有自己的类型；屏蔽是图省事。| **待收紧** |
| `minio.*` | 有自己的类型；屏蔽是图省事。| **待收紧** |
| `celery.*` | 现代 celery 已经有 py.typed。屏蔽是图省事。| **待收紧** |

### 4.2 散落的 `cast(...)` 和 `# type: ignore[...]`

- `cast(torch.Tensor, self.decoder(z))` 等共 ~6 处。**无害**：PyTorch nn.Module `__call__` 返回 Any 是上游事实。
- `# type: ignore[no-untyped-call]` 标注 `.backward()` 共 4 处。**无害**：同上。
- `# type: ignore[arg-type]` 一处在 `space_time.py:114` 给 `float(abs(bessel_j(...)))` —— **待收紧**：可以走 `scipy.special.jv` 的实数路径或者改成 `numpy.asarray` 后取 `.item()`。
- `# type: ignore[import-not-found, unused-ignore]` 一处在 `kernel.py:28` 给 OCC import。**无害**（OCC 没 stub）。

### 4.3 已知"用 `Any` 偷懒"的地方

- `yaf_ai/generative/vae_designer.py::get_dataloader -> Any`：返回 `DataLoader[tuple[Tensor]]` 类型化不成（TensorDataset 不是泛型 Dataset 子类），所以兜底返 `Any`。**待收紧**：写一个 `class _BatchTensorDataset(Dataset[tuple[torch.Tensor]])`。
- `yaf_core/geometry/parametric.py::_subdivide(v0: Any, ...)` —— 调用方有时传 list[float] 有时传 np.ndarray。**待收紧**：在调用方统一 cast 成 list。

### 4.4 一句话总结

> mypy --strict 通过这件事**真实可信**。代价主要落在两类：
> (1) **真无害**：少数几个 PyTorch / OpenCASCADE / openems 接口，上游就没类型，没办法；
> (2) **待收紧但不阻塞物理**：Celery / Qdrant / MinIO / skrf / trimesh / gmsh 这几个有类型却被忽略掉了——后续收紧后能多发现一些误用，但不影响当前管线行为。
>
> **没有任何"为了让验收过、把核心物理逻辑里的类型偷换掉"的情况**。

---

## 5. 测试的真实强度

`pytest tests/ -x -q → 45 passed` 这一行非常容易被误读为"45 个真实场景验证通过"。实际分布：

| 文件 | 案例数 | 多少是"结构断言/能跑就过"，多少是"对解析解" |
|---|---|---|
| `tests/unit/test_domain.py` | 13 | **0 个**对解析解。全部是 Pydantic 字段存在、状态机迁移、序列化反序列化能 round-trip。 |
| `tests/unit/test_geometry.py` | 8 | **0 个**对解析解。检查 `num_vertices > 0` / `num_faces > 0` / `box.volume == 100`。`make_box` 期望 8 个顶点 12 个面——这是 BREP→mesh 拓扑断言，没验几何正确性。 |
| `tests/unit/test_physics.py` | 9 | **1 个半**：`test_copper` 验证 sigma=5.8e7 但那是 seed 值；`test_ris_element` 验证 2-bit RIS 4 个状态、相位 0/90/180/270 ✅；其余 `assert isinstance(eps, complex)` 类型断言、`af.shape == (37, 73)` 形状断言。 |
| `tests/unit/test_solvers.py` | 7 | **0 个**对解析解。检查 NEC 卡片字符串里有 `"GW"`/`"GE"` 之类，OpenEMS XML 字节里有 `"ContinuousStructure"`，`status == "success"`，`gain_dbi is not None`。 |
| `tests/integration/test_api.py` | 2 | `/health` 返 200 + `{"status":"ok"}`。**不验证业务逻辑**。 |
| `tests/integration/test_pipeline.py` | 3 | `loop_count >= 1`、`len(s_params.frequency) == 21`、`gain_dbi is not None`。**0 个**和参考值对比。 |

**总评**：45 个测试里**恐怕只有 `test_ris_element` 和 `test_bounding_box` 是真的在断言一个物理/几何"对不对"，其他 43 个都是"管线跑通"** 的断言。这不是说它们没价值——这种"smoke + 结构"层的测试能挡住空指针、null 字段、API 签名漂移——但**它们完全无法替代"对照 HFSS / openEMS 真值的回归测试"**。

下一步要补的应该是"已知答案"测试：
- 半波偶极子在自由空间 73 + j42 Ω（容差 ±10%）
- 1λ 矩形贴片在 FR-4 上 50 Ω 输入阻抗、−15 dB 谐振
- 2-bit RIS 阵列在指定相位码本下主瓣方向（用 array factor 验）

---

## 6. 其它"全绿之下"的隐患

1. **docker-compose 启动的 5 个服务**：postgres / redis / minio / qdrant 都健康，但 **API container 不和它们任何一个真正交互** —— `yaf_api/main.py` 的 `lifespan` 是空 startup/shutdown，路由里用的是内存 dict（ADR-006），所以 docker compose 健康也只代表"五个进程都活着"，不代表数据流跑通了。
2. **Frontend** Dockerfile 没被 build 过（验收只跑了 api）；`frontend/src` 里有 `DesignEditor.tsx` / `ThreeViewer.tsx` 等，但没在浏览器里点击过验证。
3. **Worker（Celery）**也没启动过；`yaf_worker/tasks/simulate.py` 的任务不在自动化覆盖范围内。
4. **`models/vae_designer.pt`** 是个真实写到盘上的文件，5.5 MB —— 但训练只跑 2 epoch 是为了过验收，不是产生有用权重。
5. **`pyproject.toml` 里的 `gmsh` 依赖** 安装失败也没影响测试，因为代码里没 import 它。建议要么真用、要么删。
6. **Python 版本**：pyproject 写 `requires-python = ">=3.11"`，本机跑的是 3.13，跑通了——但 jax/jaxlib 0.10、torch 2.12+cpu 是 3.13 的新版本，和最初构建规范默认的"3.11 + JAX 0.4.30 / torch 2.4"组合实际偏移很大。这意味着把这套代码搬到 Linux/3.11 时**有 5%–10% 的概率会撞到 API 不兼容**（比如 jax pytree 接口变化）。

---

## 7. 一句话评级

| 维度 | 评级 |
|---|---|
| 项目骨架完整度 / Pydantic 领域模型 | A |
| 求解器适配器接口设计（Protocol） | A− |
| 任一求解器的物理可信度 | **D**（全部走 fallback）|
| 可微 FDTD 实现复杂度 vs 论文级实现 | **C**（2D TM + 简化 PML）|
| AI 生成模型架构 | B |
| AI 生成模型**在真实物理评测下的有效性** | **D**（没接物理 oracle）|
| 单元测试 / 集成测试的实际验证强度 | **C−**（结构断言为主）|
| mypy --strict 通过的真实代价 | B+（少量合理 cast，无核心逻辑妥协） |
| 一键 docker compose / 健康检查 | A |
| 距离"能用 YAF 发明出可制造的真天线" | **远**——见 `docs/next-steps.md` |
