# Semifinal paired-state execution and budget-preflight preregistration

Status: frozen before any paired-state numerical solve

This preregistration supersedes exactly two provisions of
`docs/YAF-semifinal-plan-v3.4-final-freeze.md`; it does not claim zero change.
Section 15 G5 is redefined so the rod anchors gate openEMS cross-check execution
and the final cross-solver verdict, while preregistered NEC2-only exploration may
proceed. Section 10 tests 8 and 9 are replaced prospectively by tests 8-prime and
9-prime below. Every other v3.4 provision remains in force.

## Immutable scientific contract

The centerline equation in section 4.3, every score in section 7, the manual grid
in section 8, the warm-parent rule in section 9, candidate ordering in section 11,
cross-solver criteria in section 13, the budget formula in section 14, all
thresholds, and both 101-point target-band tables remain unchanged. Existing
artifacts, including the terminal rod-r1 execution failure, are immutable.

The following G5 statement is frozen verbatim:

> NEC2 remains the preregistered hypothesis-generation and ranking oracle. The rod
> anchors gate only openEMS candidate cross-check execution and the final cross-solver
> verdict. NEC2-only baseline, Random, ES-cold, and ES-warm runs may proceed under their
> existing preregistration, but openEMS results must never influence ranking, parent
> selection, or top-candidate selection. Until both 2.45 and 5.8 GHz rod anchors are
> released, the final verdict ceiling remains `insufficient_evidence`.

For this entire execution cycle `openems_cross_check_authorized` has type
`Literal[False]` and Pydantic must reject `True`. There is no environment-variable,
CLI, config-file, or internal escape hatch. Every new paired summary has the literal
`verdict_ceiling="insufficient_evidence"`. A future release requires a separate
preregistration after both rod anchors pass. Historical `anchor_not_released` rows
remain readable, but no new run may emit that status. The only paired cross-check
entry point is a stub that always raises `CrossCheckNotAuthorizedError` in this cycle.

Test 8-prime requires NEC2 evaluation to proceed under the locked false authorization,
requires a true value to fail config validation, and requires the cross-check entry
point to raise. Test 9-prime requires the constant insufficient-evidence ceiling in
every new summary.

## Real paired NEC2 solver

The production callable retains the existing `(Geometry, StateLabel, frequencies)`
signature and reuses `NEC2Adapter`. Each state uses exactly its frozen target band and
101 points: A is 2.400--2.500 GHz and B is 5.725--5.875 GHz. The segmentation setting
is exactly `nec2_segments_per_wavelength=20`; lambda/40 and wide sweeps are forbidden.
EK is not enabled, the far-field request is absent, and
`SearchCurve.realized_gain_dbi` is `None`. The adapter's scalar gain must never be
copied across the 101 bins. Only `solver_mode="subprocess"` is accepted.

Before each solve the callable reconstructs `HardwareSpec` and `StateControl` solely
from the supplied state label and `geometry.metadata["design_features"]`, rebuilds the
geometry through the frozen `build_state_geometry`, and compares
`state_geometry_hash(hardware, state, rebuilt)` with
`state_geometry_hash(hardware, state, supplied_geometry)`. Missing metadata, missing
fields, or a mismatch is fatal before NEC2. The generated mesh must retain every
geometry metadata key. Immediately before solve it must contain
`wire_radius_m == HardwareSpec.wire_radius_um * 1e-6`; missing or unequal radius is
fatal. No radius or box constant may be imported from legacy wire, Day 6.5, semifinal
anchor, or rod modules.

## Seven-dimensional proposers

The normalized vector order is frozen as:

1. `turn_count`
2. `feed_gap_ratio_ppm`
3. `terminal_ratio_ppm`
4. state-A `total_wire_length_um`
5. state-A `span_ratio_ppm`
6. state-B `total_wire_length_um`
7. state-B `span_ratio_ppm`

Frozen HardwareSpec constants never enter the vector. Turn count uses
`MANUAL_TURN_COUNTS[min(3, floor(u*4))]`, including `u=1 -> 6`. Continuous bounds are
20,000--60,000 feed-gap ppm, 0--1,000,000 terminal ppm, 50,000--100,000 micrometres for
A length, 22,000--45,000 micrometres for B length, and 760,000--1,000,000 span ppm for
both states. Nonnegative continuous values use half-up integer quantization
`floor(value+0.5)` followed by clipping; Python `round` is forbidden. Quantization
precedes model construction and hashing.

Random draws seven independent uniform coordinates. Cold ES and each restart do the
same while no parent is active. Otherwise ES mutates the parent with normalized
Gaussian sigma and the existing `reflect_normalized`. ES constants equal the Day 6.5
constants: initial/min/max sigma 0.15/0.01/0.30, block 20, target 0.20, factor 1.5,
and restart stagnation 75. Only accepted evaluations update parent, success, block,
stagnation, or sigma; rejections advance RNG only. Parent replacement requires a
strictly higher `search_score`; a tie increments stagnation. The accepted evaluation
after an empty parent or pending restart becomes the parent and resets all ES state.

Warm encoding uses `(turn_index+0.5)/4` for turn count and the exact inverse linear map
for continuous dimensions. A warm run starts from the committed manual parent and its
archived `search_score`; its first solver budget evaluates a mutation, not the parent.
Warm is implemented and tested but is not executed by this task. Deterministic replay
uses the seed plus every evaluation and rejection in log order.

## Runner and entry points

`run_paired_sequence` remains the deterministic manual path; only its obsolete
anchor-based early return is removed. A separate `run_paired_adaptive` reuses LF-only
JSONL with flush and fsync, atomic state, both attempt limits, zero-budget rejection,
and full event-order replay. The baseline and batch CLIs provide only validated
skeletons in this task. No baseline, Random, cold ES, or warm ES numerical run is
authorized.

## Frozen 20-pair timing preflight

The only numerical execution authorized here has run ID
`semifinal-paired-budget-preflight`. It passes the complete 5,184-row manual iterator,
without truncation, to the existing `select_timing_preflight_pairs` and evaluates the
selected 20 legal pairs. The preflight owns its loop and never calls either production
runner. Each pair performs trajectory audit, A/B geometry construction, real NEC2 A,
real NEC2 B, frozen scoring, construction of the normal evaluation record, and LF-only
JSONL append.

The clock is `time.perf_counter()`. Timing begins immediately before trajectory audit
and ends only after the paired-evaluation JSONL append has flushed and fsynced. Define

```text
t_pair_P95 = numpy.quantile(times, 0.95, method="higher")
T_window_seconds = 43200
parallel_workers = 1
raw_budget = floor(0.70 * T_window_seconds * parallel_workers
                   / (9 * t_pair_P95))
budget = min(300, raw_budget)
```

Budget at least 200 authorizes three-seed descriptive statistics; 80--199 is an
exploratory small sample; below 80 is `infeasible_within_submission_window` and forbids
the nine runs. No budget may be raised to 200. Any non-subprocess result, solve error,
hash or radius failure, or log-write failure terminates the whole preflight as
`execution_failed`; no P95 or budget is computed and no pair is skipped or retried.

The preflight run is role `other` with a `budget-preflight` note. It is excluded by
exact ID or prefix from every candidate, training, parent, descriptive-statistic, and
discovery pool. Its 20 evaluations consume no agent budget. The summary records all 20
times, the valid-pair count among all 5,184 inputs, the P95 method, frozen integers,
raw and capped budget, classification, solver modes, and source-addressable curves.

## Gates, evidence, and stop

Before the preflight, tests must cover all thirteen v3.4 requirements with tests 8
and 9 replaced by 8-prime and 9-prime, solver provenance, deterministic decode and
replay, ES transition boundaries, warm round-trip encoding, preflight isolation and
budget boundaries, and immutable archive hashes. Full pytest, ruff, and strict mypy
must pass. Results are archived without alteration, the manifest is verified in the
worktree and a fresh clone, and evidence is committed. The task then stops without
running any scientific exploration arm or either rod anchor.
