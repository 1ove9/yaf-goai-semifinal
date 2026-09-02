# Semifinal frozen discrete manual baseline and warm-parent preregistration

Status: frozen before any manual-baseline NEC2 solve

This task executes sections 8 and 9 of
`docs/YAF-semifinal-plan-v3.4-final-freeze.md` under the solver contract in
`docs/semifinal-paired-execution-preregistration.md`. It does not change the
section 4.3 centerline, section 7 scores, any row of the section 8 integer grid,
section 11 candidate ordering, section 13 cross-check criteria, section 14 budget
formula, any threshold, the lambda/20 search density, or the locked
`openems_cross_check_authorized: Literal[False]`. It authorizes only the frozen
manual baseline described here. Random, ES-cold, ES-warm, either rod anchor, the
2.45 GHz anchor, and openEMS remain unauthorized in this task.

## Preregistered structural limitation

This prediction uses only the frozen integer tables and elementary arithmetic. It
does not use any S11 value from the 20-pair timing preflight and cannot be used to
delete, insert, tune, or refine a grid row.

The A lengths are 52,005, 61,182, 70,359, and 79,537 micrometres. Their adjacent
relative increments are approximately 17.6%, 15.0%, and 13.0%, while the
2.40--2.50 GHz target band has 4.1% relative width. The B lengths are 22,000,
25,844, 29,721, and 33,597 micrometres. Their adjacent relative increments are
approximately 17.5%, 15.0%, and 13.0%, while the 5.725--5.875 GHz target band has
2.6% relative width. If resonance varies approximately as inverse length, adjacent
rows move resonance by about 13--18%, whereas landing in-band requires only about
plus or minus 1.3--2%. The frozen discrete grid is therefore expected to have a
structurally low valid-pair rate, possibly zero.

If every assembled pair has `valid_pair_search=false`, the grid, score, thresholds,
and number of manual arms remain unchanged. The result is reported as ¡°the v3.4
section 8 frozen discrete manual template produced no valid two-state solution in
this space.¡± It is not called the strongest feasible manual baseline. The diagnostic
warm parent is then the trajectory-legal, curve-complete pair with the highest
`base_score`, with no positive eligibility. Later Random and ES-cold execution is
not blocked by that scientific result, but those arms are outside this task.

## Frozen 864-key single-state cache

The run ID is exactly `semifinal-paired-manual-baseline`. The run config uses
`agent="manual"`, `openems_cross_check_authorized=false`, and the constant
`verdict_ceiling="insufficient_evidence"`. This baseline is outside every agent
budget and is excluded by exact run ID or prefix from `freeze_candidate` and every
cross-run agent candidate pool.

The unique cache key is

```text
(hardware_hash, state_label, total_wire_length_um, span_ratio_ppm)
```

Traversal is deterministic: the 36 rows of `manual_hardware_grid()` in existing
field order, followed for each hardware by all 12 `manual_state_grid("A")` rows and
then all 12 `manual_state_grid("B")` rows. This is exactly
`36 * (12 + 12) = 864` keys. No other length is legal. Every state uses
`PairedNEC2Solver`, its exact frozen 101-point target-band table,
`nec2_segments_per_wavelength=20`, radius from `HardwareSpec`, subprocess-only
execution, and `SearchCurve.realized_gain_dbi=None`.

For each key, geometry is built and validated before the solver. A geometry failure
is logged as `single_state_rejected`, consumes no NEC2 call, and does not terminate
the batch. A successful curve is cached and logged once; the same key must never be
solved twice. A non-subprocess result, solver exception, identity/hash/radius failure,
or log-write failure terminates the entire run as `execution_failed`; no parent is
frozen, no faulting key is retried, and no later key is skipped to manufacture a
partial conclusion.

## Frozen 12-by-12 assembly

After the cache phase, all 5,184 rows of `iter_manual_pairs()` are visited in their
existing `(hardware_grid_index, pair_grid_index)` order. If either state curve is
missing, the pair is counted as curve-incomplete and is absent from the scoring and
parent pools; it is not represented as `valid_pair_search=false`. A curve-complete
pair is scored only with `score_paired_curves` and receives the existing 21-point
`audit_trajectory`. An illegal trajectory is counted and excluded. Assembly never
calls a solver.

Every curve-complete, trajectory-legal pair is written as a normal
`paired_evaluation` JSONL row with `proposer="manual-physics-baseline"` and explicit
`hardware_grid_index` and `pair_grid_index`. Its A/B curves, metrics, hashes, and
trajectory are sufficient to reconstruct every ranked number.

## Unique ES-warm parent

`freeze_manual_warm_parent(records)` is separate from `freeze_candidate`. Its pool
contains only curve-complete `paired_evaluation` rows that passed the 21-point
trajectory audit. If any row has `valid_pair_search=true`, only that eligible pool is
ranked. Otherwise the whole legal pool is ranked and `positive_eligible=false`.
Ranking is exactly:

```text
base_score descending,
hardware_hash ascending,
hardware_grid_index ascending,
pair_grid_index ascending
```

Run ID and step index are forbidden as substitutes for the last two tie breakers.
The immutable result is written to
`artifacts/analysis/semifinal-paired-manual-baseline/warm_parent.json` and contains
the parent run ID, pair and hardware hashes, both state hashes, both grid indexes,
`base_score`, `search_score`, validity and positive eligibility, the complete
reconstructible proposal, the exact seven-dimensional `encode_warm_parent` vector,
and a nullable `baseline_commit` placeholder. The vector must decode to the same
quantized hardware and both states field by field. All three future warm seeds must
share this one parent, but this task does not run ES-warm.

## Evidence, failure, and stop rules

The summary records the 864-key total, geometry-rejection count, NEC2-success count,
subprocess count, curve-incomplete pairs, trajectory-invalid pairs, scored rows,
valid-pair count, selected parent identity, and the insufficient-evidence verdict
ceiling. The source run is archived with role `other` and a note containing
`baseline=manual-reconfigurable`. The warm-parent document is committed beside the
archive. Existing preflight, rod-r1, and meander r1/r2/r3 artifact bytes are
immutable.

Before numerical execution, full pytest, Ruff, strict mypy, and archive verification
must pass. After the run, the archive is verified in the worktree and a fresh clone.
The evidence commit ends this task. No Random, ES-cold, ES-warm, anchor, or openEMS
execution follows automatically.
