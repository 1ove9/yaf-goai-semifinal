<div align="center">

# ⚡ 源序天线锻造平台 (Source Sequence Antenna Forge, YAF)

**面向天线探索、优化与求解器证据的开放、可审计 AI 平台。**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Typed: mypy strict](https://img.shields.io/badge/mypy-strict-blue)](pyproject.toml)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

[English](README.md) · [简体中文](README.zh-CN.md)

</div>

---

> [!IMPORTANT]
> **GOAI 复赛评审入口：**请先阅读审计定稿
> [`docs/submission/SUBMISSION-README.md`](docs/submission/SUBMISSION-README.md)。
> 公开仓库是经过清理的单根快照：包含终局代码、报告与 **255/255** 项 SHA-256
> 证据总账，但不包含私有 144 提交研究历史的原 commit/tree 时序或被排除的
> prompt/config blobs。冻结裁决为
> **`insufficient_evidence`**。

## GOAI 复赛审计快照

> 本结果是一个**仅基于 NEC2 的双状态计算研究**，不是“已发明的新天线”、可制造
> 设计或经双求解器确认的候选。

- 冻结的 B-parent 条件补全研究完成 20/20 个 run、6,000 次 accepted 评估，观察到
  **H1/H2 = 702/0**：出现双状态有效记录，但没有记录跨过预注册数值效应线。
- 独立预注册、仅作反事实诊断的 A-span 探针得到 10/10 单调响应与 32/32 次 NEC2
  subprocess 调用；它定位活跃空间边界，不属于 H1/H2，也不改变终局裁决。
- 候选 openEMS 互证未获授权：有界 rod-r2 仪器闸门终止于
  `repair_not_confirmed`，电压和电流探针均为 0 个可解析样本。
- 当前证据总账按 SHA-256 校验为 **255/255** 项通过。

### 10 分钟、零求解器复验入口

在 Python 3.11+ 的干净 clone 中运行。最小评审依赖不包含 NEC2 或 openEMS，以下命令
也不会调用两者：

```powershell
python -m venv .venv-review
.venv-review\Scripts\python.exe -m pip install -r requirements-semifinal.txt
.venv-review\Scripts\python.exe scripts/archive_run.py --verify
.venv-review\Scripts\python.exe scripts/semifinal_public_snapshot_verify.py
```

预期证据行包括：

```text
solver_calls=0
history_mode=sanitized_root_snapshot
original_history_replay=not_available
archive_verify=255/255 OK
b_completion_h1_h2=702/0
a_span_probe_solver_calls=32
a_span_probe_monotonic=10/10
support_certificate=480002/480002 OK
final_verdict=insufficient_evidence
```

完整说明见 [`docs/semifinal-reproducibility.md`](docs/semifinal-reproducibility.md)，
公开快照回执见
[`docs/provenance/PUBLIC-SNAPSHOT-RECEIPT.json`](docs/provenance/PUBLIC-SNAPSHOT-RECEIPT.json)。
报告中的原提交 ID 只作为溯源标签；对应 Git 对象有意不进入公开历史，因此 GitHub
无法恢复已排除的本机工具状态与历史提示词。

今天设计一根天线，意味着人类专家在 HFSS/CST 里迭代数周。**YAF 把这个循环倒过来**：
你声明*想要什么*（频段、增益、极化、尺寸预算），生成模型 + 可微电磁学 + 神经算子
代理 + 经典求解器组成的流水线替你搜索设计空间。

```
      spec ──▶ 生成 ──▶ 粗筛 ──▶ 精调 ──▶ 验证 ──▶ 评分 ──┐
       ▲     (VAE/GAN/  (FNO      (可微     (真实 NEC2 MoM │
       │      diffusion) 代理)     FDTD ∇)   /openEMS FDTD) │
       └────────── 主动学习（GP 学习真实仿真分数）◀─────────┘
```

受 fixture 覆盖的验证路径运行**真实电磁学**：部分偶极子、贴片和平面像素几何
可经过 openEMS FDTD / NEC2 MoM 实算，S 参数与选定远场变换对照官方求解器 API。
这是组件级验证，不等于所有候选都已获双求解器确认；每种几何和渲染路径仍须通过
自己的仪器闸门，只有预先声明的真实求解器判据全部通过，候选才可称为收敛。

## 为什么是 YAF？

- 🤖 **一句话到天线（text-to-antenna）智能体** —— 可调度已安装的 openEMS/NEC2
  适配器并始终显示 `solver_mode`；只有对应仪器闸门通过，输出才构成物理证据。
- ⚡ **真实物理 oracle** —— 自研 openEMS 工具链的受测路径与官方 API fixture 对照；
  NEC2/openEMS 一致性取决于具体几何与渲染器，历史锚点不能替代候选级互证。
- 🧠 **可微电磁内核** —— JAX 实现的 2D FDTD，端到端梯度流已验证：`∂(S11)/∂(几何)`，支持基于梯度的逆向设计。
- 🎨 **生成式设计脚手架** —— β-VAE / GAN / diffusion 模块可提出候选，受支持的
  平面几何可进入求解器评估；具体验证边界以
  [`docs/HONEST_STATUS.md`](docs/HONEST_STATUS.md) 为准。
- 🔌 **求解器无关** —— 统一 `SolverAdapter` 协议；内置 NEC2 (MoM) 与 openEMS (FDTD) 适配器，HFSS/CST/FEKO/COMSOL/MEEP 留有骨架。
- 📡 **前沿物理内置** —— 超表面、RIS 智能反射面、OAM 涡旋波、石墨烯、时空调制天线均为一等公民模型。
- 🏗️ **生产级架构** —— FastAPI + WebSocket、Celery、PostgreSQL/Qdrant/MinIO、React + Three.js 前端，Docker Compose 一键起。
- 🔬 **彻底诚实** —— 每个仿真结果都标注 `solver_mode`（`native` / `subprocess` / `fallback_analytical`），收敛判定只认真实求解器标签，[`docs/HONEST_STATUS.md`](docs/HONEST_STATUS.md) 逐行审计哪些经过物理验证、哪些还是脚手架。**绝不静默伪造物理。**

## 通用平台快速上手（不属于复赛科学证据）

### 30 秒体验（无需安装求解器）

```bash
git clone https://github.com/1ove9/yaf-goai-semifinal yaf && cd yaf
pip install -e .

yaf demo dipole      # 半波偶极子 → S11 / VSWR / 增益
yaf demo fdtd        # 可微 FDTD：看梯度反传
yaf demo bayesian    # GP + EI 贝叶斯优化调谐
yaf info             # 检查本机可用的求解器/后端
```

> ⚠️ 未安装 `nec2c` / openEMS 时，求解器走解析降级路径，结果显式标注
> `fallback_analytical`，**只代表管线跑通，不是电磁真值**。设置
> `YAF_NO_FALLBACK=1` 可让缺求解器直接报错。真实求解器安装见
> [docs/next-steps.md](docs/next-steps.md)（CI 从源码构建 openEMS
> v0.0.36，Ubuntu 配方见 `.github/workflows/ci.yml`）。

### 和设计智能体对话

```bash
export DEEPSEEK_API_KEY=sk-...   # 只存服务端，绝不下发浏览器
yaf serve                        # 后端 :8000
pnpm -C frontend dev             # 前端 :5173 → "AI 问答"页
```

在安装兼容求解器后，智能体可调度 `simulate_patch`、`simulate_dipole`、
`run_inverse_design` 等工具。结果始终保留 `solver_mode`，物理声明仍取决于对应
仪器和候选闸门；这条通用工作流不会升级上面的 GOAI 复赛判定。

### 全栈启动（API + Worker + 前端）

```bash
cp .env.example .env
docker compose up -d
curl http://localhost:8000/health     # → {"status":"ok","version":"0.1.0"}
open http://localhost:5173            # React + Three.js 界面
```

### 通过 API 设计天线

```bash
curl -X POST http://localhost:8000/api/v1/designs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "wifi_dipole",
    "frequency_range": [2.4e9, 2.5e9],
    "size_constraint": {"x_min": -0.1, "x_max": 0.1, "y_min": -0.1, "y_max": 0.1, "z_min": -0.1, "z_max": 0.1},
    "polarization": "linear",
    "material_palette": ["copper"]
  }'
```

## 核心模块

| 模块 | 路径 | 说明 |
|------|------|------|
| 领域模型 | `yaf_core/domain/` | Design, Geometry, Simulation, Optimization |
| 端口协议 | `yaf_core/ports/` | SolverAdapter, AIBackend, CADBackend |
| 几何内核 | `yaf_core/geometry/` | 参数化生成器, SIREN 隐式曲面, SIMP 拓扑优化 |
| 物理模型 | `yaf_core/physics/` | 超表面, RIS, OAM, 石墨烯, 时空调制 |
| 求解器 | `yaf_solvers/` | NEC2 ★, openEMS ★, MEEP/HFSS/CST/FEKO 骨架 |
| AI 引擎 | `yaf_ai/` | Diffusion, VAE, GAN, FNO, PINN, 可微 FDTD, 贝叶斯优化 |
| API 服务 | `yaf_api/` | FastAPI + WebSocket |
| 任务队列 | `yaf_worker/` | Celery + Redis |
| 数据库 | `yaf_db/` | PostgreSQL + Qdrant |
| 前端 | `frontend/` | React 18 + Three.js + TypeScript |

## 项目现状 —— 给物理打分前请先读这个

| 声明 | 状态 |
|---|---|
| NEC2 (MoM) 真实端到端：线天线 S11 / 远场 / 增益 | ✅ 对真实 nec2c 输出 fixture 锁定 |
| openEMS 受支持 fixture 路径：偶极子 / 贴片 / 平面像素几何 | ✅ 在这些路径上锁定存档的官方 API fixture |
| NF2FF 远场：增益 / 效率 / 方向图 | ✅ 同一批 dump 上与官方变换逐点一致 |
| 跨求解器基础设施 | ⚠️ 依赖具体几何/渲染器；复赛双状态候选未获 openEMS 互证授权 |
| 逆向设计管线接真实物理 oracle | ✅ `converged` 必须有真实求解器标签 |
| 主动学习反馈（GP 学真实分数）| ✅ fallback 分数永不入库 |
| 色散基板（Drude/Lorentz）| ✅ 已知答案测试；Debye **显式拒绝**（v0.0.36 引擎不支持）|
| AI 设计智能体（DeepSeek 工具调用 → 真实求解器）| ✅ 诚实规则写入结果与提示词 |
| 未装 nec2c/openEMS 机器上的物理精度 | ❌ 解析降级，显式标注 |
| 非平面面片（喇叭：需波导端口）、FNO 代理训练 | 🚧 路线图 |
| 制造导出（Gerber/STEP）| 🚧 路线图 |

完整审计：[`docs/HONEST_STATUS.md`](docs/HONEST_STATUS.md) ·
按依赖排序的路线图：[`docs/next-steps.md`](docs/next-steps.md)

我们相信：诚实的脚手架胜过作弊的演示。真实求解器 subprocess 核心路径已经实现，
但仪器放行仍取决于具体几何，不能视为对全部候选的科学确认。物理接地训练数据与
更多经校准的渲染路径仍是高影响力贡献，见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 开发者验收命令

以下检查与上面的零求解器复赛复验入口相互独立：

```bash
docker compose up -d                                          # 基础设施
curl -fsS http://localhost:8000/health                        # 200 OK
pytest tests/ -q                                              # 当前完整测试套件
python -m yaf_ai.differentiable.diff_fdtd_jax --demo          # "✓ Gradient flow verified"
python -m yaf_ai.generative.vae_designer --train --epochs 2   # 权重写盘
python scripts/demo_dipole.py                                 # S11 / VSWR / 增益
mypy yaf_core yaf_ai yaf_solvers yaf_api yaf_db yaf_worker --strict
```

## 路线图

- **Phase A** —— ✅ **核心基础设施已实现（2026-08）** —— openEMS + nec2c
  subprocess 路径、NF2FF 远场、像素几何光栅化、色散材料与已知答案 fixture；
  每个新渲染器和科学候选仍须独立校准并通过放行闸门
- **Phase B** —— 物理接地的 AI：10⁴ 真实仿真数据集、FNO 代理粗筛、条件 VAE、3D/CPML 可微 FDTD
- **Phase C** —— 制造：DfM 约束、Gerber/STEP 导出、打样-实测主动学习闭环
- **Phase D** —— 平台化：真实 DB/队列接线、前端改版、鉴权、可观测性
- **Phase E** —— 发明：对标已发表设计的 benchmark、prior-art 新颖度评分

## 许可证

### 前身、贡献边界与第三方披露

| 组件 | 本项目中的作用与贡献边界 | 使用或披露版本 | 许可证与分发边界 |
|---|---|---|---|
| [Antenna Forge](https://github.com/1ove9/antenna-forge) | 同一创作者维护的前身代码库。本项目继承 YAF 的基础领域模型、求解器适配器/API/Worker/前端脚手架、通用 AI 模块与工程结构。 | 仓库沿革；经过清理的公开快照不声称一个精确的上游 commit。 | MIT；前身与本仓库均采用 MIT，因此代码继承在许可证层面兼容。 |
| 本 GOAI 复赛仓库 | 新增预注册与决策链、自由形/meander/双状态探索空间、冻结评分与搜索研究、仪器闸门、双求解器审计、SHA-256 证据总账、255 个归档 run、终局分析和公开快照验证器。 | [`goai-semifinal-2026-09-03`](https://github.com/1ove9/yaf-goai-semifinal/tree/goai-semifinal-2026-09-03) | 仓库自研源码采用 MIT。 |
| DeepSeek API | 通用平台可选的对话/编排服务；零求解器评审路径不依赖它。它**没有**生成、替换、调参或编辑电磁曲线与归档科学数值。 | 外部 API；未把任何模型/API 版本冻结为科学证据。 | 受 DeepSeek 商业服务条款约束；本仓库不捆绑其模型或服务代码。 |
| [nec2c](https://github.com/KJ7LNW/nec2c) | NEC2 线天线计算所用的本地 subprocess 搜索/参照仪器。 | 归档记录了 `subprocess` 模式，但没有保存可执行文件 build id；这是已披露的复现限制。 | 上游 GPL-3.0-only；本仓库不捆绑或再分发，用户另行安装。 |
| [openEMS](https://github.com/thliebig/openEMS) | 独立 FDTD 仪器，仅在预注册仪器闸门授权的路径上使用。 | 归档输出记录为 0.0.36。 | 上游 GPL-3.0-or-later；本 MIT 仓库不捆绑、不重新许可。 |
| [CSXCAD](https://github.com/thliebig/CSXCAD) | openEMS 路径使用的几何/材料库。 | 归档输出记录为 0.6.3。 | 上游 LGPL-3.0-or-later；本仓库不捆绑、不重新许可。 |
| 最小 Python 评审依赖 | 用于零求解器的 255 项证据与终局事实检查。 | 已验收环境：Pydantic 2.13.4、NumPy 2.4.6、SciPy 1.17.1、structlog 26.1.0、Matplotlib 3.11.1、Pillow 12.3.0；安装范围见 [`requirements-semifinal.txt`](requirements-semifinal.txt)。 | Pydantic：MIT；NumPy/SciPy 核心：BSD-3-Clause（wheel 可能含独立许可组件）；structlog：MIT OR Apache-2.0；Matplotlib：Matplotlib License（基于 PSF）；Pillow：HPND。各依赖保留其上游许可证。 |

本仓库的 MIT 许可证只覆盖 MIT 前身代码与本仓库自研源码，不会把另行安装的
GPL/LGPL 求解器或第三方依赖重新许可。下游分发者须分别遵守各上游条款；本说明不构成
法律意见。完整科学边界与 AI 分工见
[`docs/semifinal-compliance.md`](docs/semifinal-compliance.md)。

唯一创作者：[1ove9](https://github.com/1ove9) · GOAI 队伍：`source sequence` ·
[MIT](LICENSE) © 2026 1ove9
