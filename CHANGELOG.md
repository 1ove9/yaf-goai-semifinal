# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **Real openEMS FDTD subprocess path** (v0.0.36): self-built simulation XML
  (grid, lumped ports, MUR boundaries), port time-probe DFT → S11/Zin —
  locked point-by-point against the official Python API on fixture data
- **NF2FF far field**: near-field recording boxes + `nf2ff` binary driver +
  result parser; gain/efficiency from real physics (bit-identical to the
  official transform on the same dumps); dipole 2.25 dBi / patch 6.82 dBi
  known answers
- **Parametric patch antenna path**: metal patch + lossy substrate + ground +
  probe feed; resonance within 0.8 % of the official API reference
- **Planar pixel-geometry rasterization**: arbitrary planar sheets (VAE pixel
  designs, printed spirals, fractals) rasterized onto the FDTD grid
  (pixel-patch setup of arXiv:2505.18188); known-answer locked
- **Dispersive substrates**: first-order Drude/Lorentz materials with a
  discriminating known-answer test; Debye is explicitly refused (no engine
  extension in openEMS v0.0.36 — no silent fake physics)
- **Cross-solver validation**: NEC2 (MoM) vs openEMS (FDTD) on the same
  geometry, resonance agreement < 10 %
- **Inverse-design pipeline with a real physics oracle**: capability-aware
  candidate verification, `oracle_mode` label, convergence gated on real
  solver results
- **Active-learning feedback (step 6)**: GP + Expected Improvement over the
  patch design space, trained exclusively on real-solver scores
- **AI design agent**: DeepSeek function-calling (`simulate_patch`,
  `simulate_dipole`, `run_inverse_design`) drives real simulations from chat;
  SSE tool-activity frames in the frontend; honesty rules in prompt + results
- **CI builds openEMS from source** (cached), so all real-solver end-to-end
  tests run in the cloud; recipe validated on an identical Ubuntu 24.04 system
- `yaf` CLI (`yaf demo dipole`, `yaf demo fdtd`, `yaf serve`, `yaf info`) — one-command experience
- **Solver honesty layer**: every `SimulationResult` now carries
  `solver_metadata["solver_mode"]` (`native` / `subprocess` / `fallback_analytical`)
  and an explicit `warning` when results come from an analytical fallback rather
  than a real EM solver
- `YAF_NO_FALLBACK=1` strict mode: raises `SolverUnavailableError` instead of
  silently degrading to closed-form approximations (recommended for CI)
- Known-answer physics tests (half-wave dipole impedance vs. induced-EMF theory)
- **Real NEC2 output parser**: per-frequency impedance blocks, radiation
  patterns and power budget from actual nec2c output (the old keyword grep
  never matched and silently returned hardcoded values); WSL bridge on Windows
- GitHub Actions CI (ruff + mypy --strict + pytest), release workflow
- Community files: LICENSE (MIT), CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CITATION.cff
- English README with bilingual (中文) version

### Fixed
- Primitive coordinates were serialized at 7 significant digits while grid
  lines used 12 — an irrational feed position could land 7.6e-11 m off its
  mesh line, openEMS found no excitation edges, and the zero-energy run
  reported S11 = 0 / VSWR = 1.0 ("perfect match"). Primitives now use the same
  format as grid lines, and an all-zero voltage probe is a hard error
- Port DFT normalization aligned with the official single-sided convention
  (2·dt) so port power and NF2FF radiated power share one scale — radiation
  efficiency is now physically meaningful
- `FarFieldResult.gain_dbi()` computes real directivity by spherical
  integration (validated ±0.3 dB against the official NF2FF Dmax)

## [0.1.0] - 2026-05-21

### Added
- Domain model (`yaf_core/domain/`): Design, Geometry, Simulation, Optimization (Pydantic v2)
- Solver adapters: NEC2 (card writer + subprocess + analytical fallback),
  openEMS (CSXCAD XML + analytical fallback), skeletons for MEEP/HFSS/CST/FEKO/COMSOL
- Differentiable 2D FDTD in JAX with verified gradient flow
- Generative models: β-VAE antenna designer, GAN metasurface, diffusion designer
- Surrogates: FNO, DeepONet (untrained scaffolding)
- Optimization: NumPy GP Bayesian optimization, NSGA-II, SIMP topology optimization
- Physics models: metasurface, RIS, OAM, graphene, space-time modulation
- FastAPI gateway + WebSocket, Celery worker, docker-compose stack
  (PostgreSQL, Redis, MinIO, Qdrant)
- React 18 + Three.js frontend scaffold
- 45-test suite, `mypy --strict` clean on 64 source files
- `docs/HONEST_STATUS.md` — line-by-line credibility audit
- `docs/next-steps.md` — dependency-ordered roadmap to real physics
