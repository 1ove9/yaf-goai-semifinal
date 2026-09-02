## What & why

<!-- Summary of the change and the motivation. Link issues with "Fixes #123". -->

## Checklist

- [ ] `pytest tests/ -x -q` passes
- [ ] `mypy yaf_core yaf_ai yaf_solvers --strict` passes
- [ ] `ruff check .` passes
- [ ] New physics code has a **known-answer test** (vs. analytical solution or published reference)
- [ ] Solver results are honestly labeled (`solver_mode` metadata) — no silent fake physics
- [ ] Docs updated if behavior changed
