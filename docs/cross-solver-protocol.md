# Cross-solver protocol: openEMS air variant versus NEC2 wire grid

Status: **frozen before the first Day 3 cross-check run**
Protocol version: `day3-air-wire-grid-v1`

## Purpose and scope

NEC2 is a thin-wire, free-space method-of-moments solver. It cannot represent the
volume dielectric and loss model of the FR4 microstrip simulations used in Day 2.
Comparing the Day 2 FR4 result directly with a wire model would therefore mix a
material-model change with a solver comparison and would not be physically valid.

This protocol instead validates a controlled **air-substrate variant**. Agreement is
evidence about the shared conductor geometry, finite ground, feed, and resonance
calculation in that variant. It is not direct validation of FR4 loss, dielectric
loading, surface waves, or the Day 2 absolute operating frequency. Extrapolation back
to FR4 is limited to confidence in the common metal/feed construction; the FR4 material
model remains openEMS-only evidence.

## Frozen transformation

The source is an archived Day 2 `top_designs[index]` record. The tool reconstructs the
geometry from the archived run config and `proposal_parameters`, and rejects it unless
the reconstructed geometry hash equals the archived hash.

1. The patch length, patch width, finite ground length, finite ground width, air-gap
   height, and probe-feed x/y position are copied without change.
2. FR4 (`eps_r=4.4`, loss tangent `0.02`) is replaced with lossless air
   (`eps_r=1.0`, loss tangent `0.0`). No conductor dimension is retuned after seeing a
   solver result.
3. The common sweep is centered on the deterministic free-space half-wave estimate
   `c/(2*patch_length)` and spans 75–125% of that estimate at 51 points. This is a
   frequency-range recalibration necessitated by removing dielectric loading; the metal
   stays invariant.
4. openEMS uses the same finite patch, finite ground, air gap, and vertical lumped
   probe. Far-field processing is disabled because the decision uses S11 only.
5. NEC2 uses an explicit finite wire grid for both patch and ground; it does not use an
   infinite `GN` ground. Each plane uses six intervals per axis. The intervals on either
   side of the mandatory feed-x or y=0 node are allocated in proportion to the two side
   lengths, then spaced uniformly on each side; this avoids sub-radius sliver segments.
   Every crossing is split into wire edges so electrical junctions are explicit. A one-segment vertical feed
   wire connects the finite ground grid to the patch grid and carries the voltage source.
   A minimal three-angle `RP` request is included because NEC2 needs an execution card
   after `FR`; its far-field values are not used by this S11-only decision.
6. The common grid-wire radius is selected by equal exposed conductor area:
   `r = (patch_area + ground_area) / (2*pi*total_grid_wire_length)`. The feed-wire radius
   is `min(r, air_gap/20)`. This is an equivalence rule, not a claim that a wire grid is
   identical to a sheet.

The underlying NEC conventions are documented in the vendored
`_reference/necpp/src/c_geometry.h` (`wire`: segment count and radius),
`_reference/necpp/example/example1.nec` (`GW`, `GE`, and center voltage `EX` cards), and
the vendored `_reference/necpp/docs/necpp_guide.pdf`, which traces the API to the NEC-2
card model. The equal-area replacement follows the standard wire-grid modeling idea of
preserving conductor area per unit wire length; its exact formula above is preregistered
here so it cannot be tuned after viewing results.

## Frozen extraction and decision rule

For each solver, resonance is the sampled frequency with the minimum
`20*log10(|S11|)` in the common 51-point sweep. openEMS is the reference denominator for
the relative frequency difference.

- Resonance agreement: `abs(f_nec2 - f_openems) / f_openems <= 0.05`.
- S11-depth agreement: `abs(S11_nec2_at_its_min - S11_openems_at_its_min) <= 3.0 dB`.
- `CONFIRMED` requires **both** inclusive thresholds. Every other numeric outcome is
  `DIVERGENT` and is archived unchanged.

A process mode other than real openEMS `subprocess`/`native` and real NEC2 `subprocess`
is an execution failure, not a cross-check result. Analytical fallback must never be
relabeled as solver agreement.

## Evidence and interpretation

Each run stores both full 51-point curves in `log.jsonl`, an archive-compatible
`summary.json`, solver modes, the transformation definition, equal-area grid data, and
the mechanical decision fields. A `CONFIRMED` result may upgrade a Day 2 spec only when
the already-frozen 10% classic-improvement criterion is also satisfied. Permitted
language is: “GP found a design better than classic and the air-variant cross-solver
check confirmed it.” It is not evidence that YAF invented a new antenna.
