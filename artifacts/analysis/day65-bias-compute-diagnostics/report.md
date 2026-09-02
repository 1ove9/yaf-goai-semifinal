# Day 6.5 frequency-bias and candidate-B compute diagnostics

## Result

The radius-only NEC2 run is `day65-nec2-surrogate-radius-diagnostic`. Its frozen
`explained_fraction` is **0.333333333**, classified as
`partial_attribution`. Candidate B's released-instrument cell ratio to A is
**1.162552290**, classified as
`future_timeout_extension_authorized`.

No openEMS time stepping was invoked. The only solver invocation was one real
NEC2 subprocess sweep. No ES/random batch was started.

## Released 6x build-only XML mesh audit

| Candidate | X lines | Y lines | Z lines | Total cells | Min cell (m) | Max cell (m) | Six-field lower bound (GiB) | XML SHA-256 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| A | 491 | 487 | 495 | 117641160 | 7.5e-05 | 0.00461219166 | 5.258970 | `a6aab62a1055a3c6effb3f652fa7dbe99e9ab9922c951f111cd0fe52a91caede` |
| B | 501 | 525 | 523 | 136764000 | 7.5e-05 | 0.00461219166 | 6.113827 | `c0db05cf170b873201529461cf90c4fd5a2c981cd39be1cdce15e911ee3471ba` |

Memory estimate method: `six_float64_field_components_per_Yee_cell_lower_bound`. It is a transparent lower
bound of `cells * 6 field components * 8 bytes`, not a prediction of total
openEMS process memory.

## Frozen classification

`cells_B / cells_A = 1.162552290` against the inclusive
threshold `1.35`. Future timeout authorization:
`43200.0` seconds. No retry is executed in this task.

## Formal timeout evidence

- `runs/day65-pipeline.stdout.log`
- `runs/day65-pipeline.stderr.log`

## Correction proposal draft (not implemented)

1. Treat conductor radius as one contributor and pre-register a factorial anchor audit of radius, feed representation, and grid resolution before changing any protocol threshold.
2. A future, separately executed candidate-B audit may raise only openems_timeout_seconds to 43200; geometry, mesh, sweep, and every verdict gate must remain unchanged.

Existing protocols, thresholds, sweeps, scores, candidates, and archived runs
remain unchanged.
