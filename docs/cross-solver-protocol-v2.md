# Cross-solver protocol v2: native-geometry curve agreement and attribution

Status: **frozen before the first Day 4 anchor or convergence run**  
Protocol version: `day4-native-curves-v2`

## Why v2 revises the observable

The Day 3 v1 wifi24 comparison (`day3-crosscheck-wifi24`) observed a 32.57 dB
difference between the two sampled S11 minima. A resonance-depth minimum is extremely
sensitive to feed discretization, reference impedance, loss, and the exact sampled
frequency even when two solvers describe the same broad resonance. It is therefore a
poor binary identity test. V2 retains S11-depth difference as a traceable descriptive
number, but it is no longer a verdict criterion. V1 and all of its archived results
remain unchanged.

For any two native representations of the same geometry, v2 uses both:

1. sampled resonance relative difference, with the openEMS frequency as denominator,
   at or below 5%; and
2. Pearson correlation at or above 0.8 between the two S11-in-dB curves after linear
   interpolation onto 201 equally spaced points over their common frequency band.

Both inclusive thresholds must pass for `CONFIRMED`; otherwise the result is
`DIVERGENT`. Analytical fallback is an execution failure. S11-depth difference is
recorded but cannot change either verdict.

## Mandatory native dipole anchor

Before any Day 4 attribution or wire-design cross-check, a 2.45 GHz free-space
half-wave dipole is modeled natively as a NEC2 wire and as an openEMS wire/thin-box
path. The conductor centerline geometry is shared; no surface-to-wire transformation
is involved. Its sweep is 1.8--3.1 GHz at 101 points.

The anchor gate is deliberately stricter: resonance relative difference at or below
3% and common-band curve correlation at or above 0.9. Failure stops every subsequent
cross-solver comparison. The failed curves remain evidence; the chain must be repaired
and a new anchor run archived rather than weakening these thresholds.

## Frozen patch-grid attribution rule

The object is the archived air variant from `day3-crosscheck-wifi24`. Its archived
openEMS curve is reused without rerunning or editing it. NEC2 is rerun at
`grid_intervals` 6, 12, and 24. At each grid density the equal-exposed-area radius rule
from v1 is recomputed, and the archive records resonance, relative gap to openEMS,
minimum line spacing divided by radius, segment count, and solve time.

Let `gap(g) = abs(f_nec2(g) - f_openems) / f_openems`.

- If gap is monotonically non-increasing and `gap(24) < 0.5 * gap(6)`, classify
  `instrument_boundary` (wire-grid discretization dominates).
- If `gap(24) >= 0.8 * gap(6)`, classify `genuine_anomaly` (the discrepancy has
  plateaued at the tested resolution).
- Every intermediate result is `inconclusive_needs_finer_grid`.

For the roadmap number, a power law `gap = A * grid_intervals**(-p)` is fitted by
ordinary least squares in log-log space to the positive 6/12/24 gaps. An estimate is
reported only when all gaps narrow monotonically and fitted `p > 0`; the integer result
is rounded upward and must exceed 24. This extrapolation is descriptive, not a changed
verdict.

The wifi24 attribution does not automatically reclassify wifi58 or n78. Those v1
results require their own spec-specific convergence evidence; the Day 4 appendix must
say so explicitly.

## Native wire exploration applicability

For the Day 4 meander study, NEC2 is the exploration oracle and openEMS is the
independent verifier. Both consume the same wire centerline geometry and neither uses
the lossy patch-to-grid transformation. The ordinary 5%/0.8 v2 criteria apply to top
designs. `confirmed_improvement` is permitted only when the already-frozen performance
comparison is positive and the v2 cross-solver decision is `CONFIRMED`.
