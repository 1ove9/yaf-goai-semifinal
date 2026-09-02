# Contributing to YAF (YuanXu Antenna Forge)

Thanks for your interest in contributing! YAF is an AI-driven antenna inverse-design
platform, and we welcome contributions of all kinds: solver adapters, AI models,
physics validation, documentation, frontend work, and bug reports.

[中文贡献指南见下方](#中文指南)

## Ground rules

1. **Read [`docs/HONEST_STATUS.md`](docs/HONEST_STATUS.md) first.** It documents
   exactly which parts of the codebase are physically validated and which are
   scaffolding. PRs that claim physical correctness must come with known-answer
   tests (see below).
2. **Never silently fake physics.** If a solver is unavailable, the code must
   label results as `fallback_analytical` — see `yaf_solvers/base.py`. PRs that
   return synthetic results labeled as real simulation output will be rejected.
3. **Follow the roadmap.** [`docs/next-steps.md`](docs/next-steps.md) orders work
   by dependency. The highest-value contribution right now is **Phase A**:
   real openEMS / nec2c integration with known-answer regression tests.

## Development setup

```bash
git clone https://github.com/1ove9/yaf-goai-semifinal yaf && cd yaf
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pre-commit install
```

Run the checks that CI runs:

```bash
ruff check .
mypy yaf_core yaf_ai yaf_solvers --strict
pytest tests/ -x -q
```

## Pull request checklist

- [ ] Tests pass locally (`pytest tests/ -x -q`)
- [ ] `mypy --strict` passes on `yaf_core yaf_ai yaf_solvers`
- [ ] `ruff check .` passes
- [ ] New physics code has a **known-answer test** (compare against an analytical
      solution or published reference — e.g., half-wave dipole 73 + j42 Ω)
- [ ] New solver adapters implement the `SolverAdapter` protocol and set
      `solver_mode` metadata honestly (`native` / `subprocess` / `fallback_analytical`)
- [ ] Docs updated if behavior changed (`README.md`, `docs/`)

## What to work on

Good first issues are labeled [`good first issue`](../../labels/good%20first%20issue).
High-impact areas:

| Area | Difficulty | Where |
|---|---|---|
| Known-answer solver tests (dipole, monopole, patch) | Medium | `tests/physics/` |
| Real openEMS integration (Linux/WSL2) | Hard | `yaf_solvers/openems_adapter/` |
| CPML boundary for differentiable FDTD | Hard | `yaf_ai/differentiable/` |
| Dataset generation pipeline (geometry → S-params) | Medium | `yaf_ai/` |
| Frontend 3D editor improvements | Medium | `frontend/src/` |
| Documentation & tutorials | Easy | `docs/` |

## Commit style

Conventional-ish: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `ci:`.
Keep the subject under 72 characters; explain *why* in the body when non-obvious.

## Reporting bugs

Use the bug report template. Always include:
- OS + Python version
- Whether real solvers (`nec2c`, openEMS) are installed, or you're on the fallback path
- Minimal reproduction

---

## 中文指南

1. **先读 [`docs/HONEST_STATUS.md`](docs/HONEST_STATUS.md)** —— 它标注了代码库中
   哪些部分经过物理验证、哪些还是脚手架。
2. **绝不静默伪造物理结果。** 求解器不可用时必须显式标注 `fallback_analytical`。
3. **按路线图来。** [`docs/next-steps.md`](docs/next-steps.md) 按依赖顺序排列了
   接下来的工作，当前最有价值的贡献是 Phase A（真实 openEMS / nec2c 集成 +
   已知答案回归测试）。

开发环境、PR 检查清单与上方英文一致。欢迎用中文提 issue 和 PR。
