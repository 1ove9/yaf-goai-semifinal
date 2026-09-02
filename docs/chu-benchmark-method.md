# Chu--Harrington benchmark method

Status: preregistered before the first Q calculation or benchmark output.

## Scientific scope and immutable sources

This analysis reads version-controlled curve and geometry bytes only. It must not call
any solver, create a run directory, or change an existing artifact. The primary design
pairs are frozen as follows:

| design | NEC2 source | openEMS source |
|---|---|---|
| confirmed meander candidate A | `day5-wire-v6-final-crosscheck-top1` | same run |
| confirmed meander candidate B | `day5-wire-v6-final-crosscheck-top2` | same run |
| native half-wave dipole anchor | `day4-dipole-anchor` | same run |
| patch air variant | `day5-patch-final-nec2-grid44` | `day5-patch-final-openems-2x-mesh-recheck` |

Historical patch discretization curves may appear in a diagnostic appendix, but only
the repaired real 2x openEMS curve and grid-44 NEC2 curve form the primary patch pair.
The benchmark does not change any prior CONFIRMED or DIVERGENT decision.

## Electrical size and Chu--McLean lower bound

At each solver's fitted resonance frequency,

```text
k = 2*pi*f_res/c0
ka = k*a
Q_min(ka) = 1/(ka)^3 + 1/(ka)
```

This is the McLean form for a linearly polarized, perfectly efficient radiator. Each
row records its radius convention:

- Meander candidates A/B: reconstruct the archived proposal parameters and geometry
  hash, then compute the minimum enclosing sphere of every centerline vertex. This
  actual radius is primary. Also report the frozen 30 by 30 mm box half-diagonal
  (`21.213203 mm`) as a secondary sensitivity convention; it is not substituted for
  the actual geometry.
- Native dipole anchor: `a = length/2`.
- Patch air variant: calculate two descriptive radii from the archived transformation:
  patch-metal corners only, and patch plus finite-ground corners together. Both rows
  are shown. A finite ground materially complicates the assumptions behind a Chu
  sphere, so neither patch convention supports a strong physical-limit claim.

## Magnitude-only single-resonance fit

The archives contain S11 magnitude in dB, not complex phase or impedance. The primary
Q estimate is therefore explicitly a loaded-Q proxy fitted in reflected-power space,
not a full complex-RLC extraction. Convert every sample with
`P(f) = 10^(S11_dB/10)`. Let the sampled minimum be `P_min` and freeze the window level
at half the reflected-power notch depth toward unity:

```text
P_half = (1 + P_min)/2
```

Starting at the minimum, find the nearest left and right brackets where the curve
crosses `P_half`. Include both bracketing samples in the fit. Linear interpolation gives
the two crossing frequencies used by the bandwidth cross-check. A curve is initially
eligible only when its minimum is outside the first and last three samples, its depth
is at most -6 dB, both crossings exist, and the fit window contains at least five
samples.

Fit the three-parameter series-RLC magnitude proxy by bounded nonlinear least squares:

```text
x = Q * (f/f0 - f0/f)
P_model(f) = P0 + (1-P0) * x^2/(1+x^2)
```

Bounds are `0 <= P0 < 1`, `f0` inside the frozen window, and
`0 < Q <= 1,000,000`. R-squared is calculated in reflected-power space. A fit with
`R^2 < 0.9` is `low_confidence` and is excluded from the main table and plot. Failed
eligibility, failed optimization, or a fitted `Q/Q_min < 1` is also appendix-only; the
latter is labelled `physics_inconsistent_proxy` rather than treated as beating a
fundamental bound.

## Fractional-bandwidth cross-check

Use the same interpolated `P_half` crossings:

```text
fractional_bandwidth = (f_high - f_low)/f0
Q_FBW = 1/fractional_bandwidth
```

The RLC fit remains the primary estimate. Report both estimates on every successful
row. If `abs(Q_RLC-Q_FBW)/Q_RLC > 0.30`, attach
`bandwidth_disagreement_over_30pct`; this flag alone does not hide an otherwise
high-confidence row.

## Sampling and uncertainty

Every row records sample count, fit-point count, median bin width, relative bin width
at resonance, the two crossing frequencies, and bandwidth. Resonance-bin uncertainty
is `+/- bin_width/2`. Treat the two interpolated crossing locations conservatively as
one total bin of bandwidth uncertainty. Thus the bandwidth-Q interval is obtained from
`bandwidth +/- bin_width` when the lower bandwidth remains positive.

The RLC optimizer's local Jacobian gives a covariance standard error for Q when it is
invertible. The reported combined relative uncertainty is the quadrature sum of
`Q_standard_error/Q` and the bin-limited term `bin_width/bandwidth`. This is a sampling
diagnostic, not a claim that model-form or solver discretization uncertainty is fully
captured. The 51-point patch sweep has roughly 1.1% relative bins and the 201-point
wire sweep roughly 0.5%; narrow notches with too few points will naturally fail or
carry large uncertainty.

## Interpretation limits and wording discipline

S11 bandwidth mixes the radiator, feed mismatch, and any implicit matching behavior;
the extracted quantity is a proxy for loaded Q. NEC2's lossless wires and the
near-lossless openEMS air variants are unusually compatible with the 100%-efficiency
Chu assumption, but this does not remove the mismatch or magnitude-only limitations.

Allowed language includes: "candidate A has Q/Q_min approximately X at ka=Y" and
solver-matched comparisons to the textbook dipole anchor. Candidate-to-anchor
improvement is `(anchor_ratio-candidate_ratio)/anchor_ratio` within the same solver.
The plot's single anchor reference line is the geometric mean of the high-confidence
NEC2 and openEMS anchor ratios; individual anchor points remain visible.

Do not say "approaches" or "reaches" the Chu limit unless `Q/Q_min < 1.5`, the fit is
high-confidence, no physical-consistency warning exists, and the bandwidth diagnostic
is reported. No strong Chu-limit conclusion is permitted for either patch radius.
Results far from the limit must be stated plainly and may be contextualized by the
finite search budget and the fact that the exploration objective did not optimize
bandwidth or Q.

## Day 6 dual-resonance extension

The Day 6 free-form designs do not change the McLean formula, sphere convention,
confidence threshold, or wording rules above. Their actual reconstructed 3D
centerline minimum enclosing sphere is used for both resonances. Each final native
solver curve is analyzed twice and each row retains the final cross-check run ID,
solver, candidate rank, target band, and geometry hash.

To prevent the second resonance from replacing the first in a global-minimum fit,
the frozen fit input for the 2.4 GHz row is 1.90--3.00 GHz (the target band plus
0.50 GHz on either side), and the input for the 5.8 GHz row is 5.125--6.475 GHz
(the target band plus 0.60 GHz on either side). The unchanged fitting routine must
return its fitted resonance inside the corresponding 2.40--2.50 GHz or
5.725--5.875 GHz target band. Otherwise that row is explicitly fit-ineligible.
The usual -6 dB, five-point window, R-squared, bandwidth-disagreement, sampling,
and physical-consistency gates remain unchanged. The two points describe two loaded
resonance proxies of one structure; they are not independent antenna discoveries.
