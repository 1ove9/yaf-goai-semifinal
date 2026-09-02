# Cross-solver protocol v2.1: resonance validity before agreement

Status: **frozen before the first Day 4.5 numeric run**  
Protocol version: `day4-wideband-resonance-v2.1`

## Reason for the revision

Protocol v2 could label two flat, severely mismatched S11 curves as confirmed when
their sampled minima happened to occur at the same sweep boundary. In
`day4-wire-v4-crosscheck-top1` and `day4-wire-v4-crosscheck-top2`, both solvers chose
sample index 0, the reported depths were only about -0.05 to -0.11 dB, and the high
Pearson correlations described parallel flat curves rather than a shared resonance.
The resulting Day 4 wire conclusion is withdrawn in
`artifacts/analysis/day4-wire/RETRACTION.md`.

V2.1 adds a validity gate. It does not reinterpret or edit any v1 or v2 evidence.

## Mandatory resonance-validity gate

Each solver curve is checked independently before resonance-frequency difference or
curve correlation may be used for a verdict. Let `i_min` be the zero-based index of
the minimum sampled S11 value among `N` ordered samples. A curve has a valid in-band
resonance only when both conditions hold:

1. `3 <= i_min <= N - 4`, so the minimum is outside the first and last three sampled
   points; and
2. `S11[i_min] <= -6.0 dB`.

If either solver fails either condition, the cross-check verdict is
`NO_RESONANCE_IN_BAND`. Such a result is neither `CONFIRMED` nor `DIVERGENT` and
cannot support `confirmed_improvement`. The archive records each solver's minimum
index, minimum frequency, minimum depth, and the two gate results.

## Wideband cross-check sweep

Every Day 4.5 wire cross-check uses 1.5--3.5 GHz with 201 linearly spaced samples in
both solvers. Resonance-frequency difference and Pearson correlation are computed
over this full common band only after both curves pass the validity gate. A narrower
exploration sweep may be used by the NEC2 oracle, but it cannot substitute for this
verification sweep.

For two valid curves, v2's ordinary inclusive thresholds are inherited unchanged:

- resonance-frequency relative difference, with openEMS as denominator, at or below
  5%; and
- S11-in-dB Pearson correlation at or above 0.8 after interpolation onto 201 common
  frequency samples.

Both pass for `CONFIRMED`; otherwise the verdict is `DIVERGENT`. S11-depth difference
remains record-only.

## Inherited controls

The native half-wave-dipole anchor gate from protocol v2 remains mandatory and
unchanged: at most 3% resonance-frequency difference and at least 0.9 curve
correlation. The frozen 6/12/24 grid-convergence attribution rules also remain
unchanged. Analytical fallback remains an execution failure.

The Day 4.5 wire result may be called `confirmed_improvement` only when the selected
design has valid in-band resonances in both solvers, passes both ordinary v2.1
agreement thresholds, and improves on the frozen straight reference under the
preregistered corrected wire score. Failure at any stage is reported without
relaxing these gates.
