# Semifinal 5.8 GHz meander-renderer anchor r2 preregistration

Status: frozen before any r2 numerical solve
Run family: `semifinal-wifi58-meander-renderer-anchor-r2-*`

## Purpose and evidence boundary

This is a new follow-up qualification study under
`v3.4-final-freeze`. It does not change the paired-state scientific object,
the section 4.3 geometry equations, section 7 score, section 8 mesh table,
any threshold, budget formula, or ES-warm parent rule. It must finish and
archive its combined certificate before any baseline, Random, ES-cold, or
ES-warm evaluation is allowed.

The immutable r1 combined certificate reported:

- NEC2 global resonance: 5.480 GHz at -17.78196081626043 dB;
- openEMS global resonances: 5.080 GHz at 1x and 5.280 GHz at 2x;
- r1 NEC2/openEMS-2x relative frequency difference: 3.787878787878788%;
- full 251-point Pearson correlation: 0.8736230658225413;
- none of the three sampled points in 5.725--5.875 GHz was an internal
  local minimum; and
- openEMS moved upward by about 3.9% from 1x to 2x, toward NEC2, so those
  two levels did not establish convergence.

These openEMS results motivate extending the convergence ladder only. They
are forbidden inputs to the r2 length calibration. The calibration factor
uses only the archived r1 NEC2 resonance frequency of 5,480,000,000 Hz.
The exact half-wave construction ignored finite-wire end effects and placed
the thin-wire resonance near 0.47 wavelength; the descriptive 2.330 GHz and
0.4753-wavelength values are motivation only and never enter the r2 length.

The r1 archived bytes are immutable. Their frozen SHA-256 values are:

- `log.jsonl`: `937bd9d53a992a7bfce54d886652291fbac49c366f8fd617d4681f5ff4258b89`
- `summary.json`: `61d012118b489634f9e04c4c5a02ada6532edbf3e9088f68806376b6b07f68c7`

## One authorized calibration

The only authorized geometry-length modification is

```text
L_r2 = 0.0258441774 * 5480000000 / 5800000000
     = 0.02441829175034483 m  (binary64 evaluation)
```

The executable constant and its regression test must evaluate the written
expression directly and compare it exactly. The task input also displayed
`0.024418291713793103 m`; that transcription is arithmetically smaller than
the frozen expression by approximately `3.6551726e-11 m` and is therefore
non-normative. This disclosure resolves the contradiction without using any
openEMS result or introducing another calibration.

If r2 NEC2 has no valid internal minimum in 5.725--5.875 GHz, the terminal
verdict is `not_released_out_of_band`, `anchor_released=false`, and r3 is
forbidden.

## Frozen geometry and solver dispatch

The geometry is a y-axis straight dipole dispatched through the audited
meander thin-box renderer:

- `feed_gap_m = 0.000600`;
- each arm conductor length is `(L_r2 - 0.000600) / 2`;
- edge order is `feed_gap`, `positive_arm`, `negative_arm`;
- `antenna_class = meander_dipole` and openEMS must dispatch through
  `_build_meander_wire_xml`;
- NEC2 uses `wire_radius_m = 5e-5`, `EK=false`, and
  `solver_mode=subprocess`;
- fallback, generic-wire, freeform, EK, radius matching, and a thin-box
  half-width of 0.05 mm are prohibited; and
- the sweep is 1.5--6.5 GHz at 251 identical frequencies in both solvers.

The frozen vertices in metres are:

```json
[
  [0.0, -0.0003, 0.0],
  [0.0, 0.0003, 0.0],
  [0.0, 0.012209145875172415, 0.0],
  [0.0, -0.012209145875172415, 0.0]
]
```

The frozen edges are:

```json
[[0, 1], [1, 2], [0, 3]]
```

With the frozen metadata and the random Geometry UUID excluded, canonical
sorted compact JSON has SHA-256:

```text
1c0e018ac1e65aacf30ac158ef2336f461b430036b0c6ad9eb2bfefb15ba0d5a
```

The implementation must hard-code and validate the vertices, edges, and
hash before any numerical call.

`minimum_pitch_m` is computed by the same r1 function with only the length
input replaced by `L_r2`; the frozen result remains
`0.0025844177413793103 m`. No new 1x baseline is defined. Refinement remains
a grid-density multiplier.

## Unconditional ladder and recorded resources

After one NEC2 solve, openEMS levels 1x, 2x, 4x, and 8x run in that exact
order. All four levels are unconditional: no result-dependent branch,
adaptive early stop, or skipped intermediate level is allowed.

For each openEMS level, `summary.json` records:

- x/y/z line counts;
- total cell count;
- minimum and maximum cell sizes;
- peak process-tree memory in MiB; and
- elapsed wall-clock seconds.

The 1x and 2x levels are descriptive only and cannot release the anchor.
Self-convergence reads only valid 5.8 GHz-band internal resonances at 4x and
8x. It passes exactly when their relative movement is at most 0.03. An
invalid band resonance at either level produces no movement and fails
convergence.

Cross-solver agreement reads only NEC2 and openEMS 8x. It uses their same
251-point frequency array and passes exactly when:

- relative resonance-frequency difference is at most 0.03; and
- full-sweep Pearson correlation is at least 0.9.

The 8x level becomes the minimum openEMS density for later candidate work
only if this study releases the anchor. This study must not start a candidate.

## Unchanged release thresholds

The r1 thresholds are retained verbatim:

- resonance is an internal local minimum in 5.725--5.875 GHz;
- resonance depth is at most -6 dB;
- NEC2 versus openEMS-8x relative frequency difference is at most 3%;
- 251-point Pearson correlation is at least 0.9; and
- openEMS 4x-to-8x valid-resonance movement is at most 3%.

S11 depth difference remains record-only for cross-solver agreement.

## Exhaustive and mutually exclusive verdict priority

Exactly one of four verdicts is emitted, in this order:

1. If NEC2 lacks a valid high-band resonance:
   `not_released_out_of_band`.
2. Otherwise, if 4x or 8x lacks a valid high-band resonance, their movement
   is `None`, or their movement exceeds 3%:
   `not_released_not_converged`.
3. Otherwise, if the NEC2/openEMS-8x frequency difference exceeds 3% or
   Pearson is below 0.9: `not_released_agreement`.
4. Otherwise: `released` and `anchor_released=true`.

There is no fifth verdict. All non-released verdicts set
`anchor_released=false`. No result authorizes r3.

## Execution, evidence, and stopping rule

Implementation and gate tests may begin only after this preregistration and
the matching DECISIONS entry are committed. Numerical execution may begin
only after pytest, Ruff, and strict mypy all pass. The combined run contains
one real NEC2 subprocess curve and four real openEMS subprocess curves with
no fallback.

The run is copied verbatim to `artifacts/runs/`, added to the integrity
manifest, verified in the working tree and a fresh clone, and committed as
the third r2 commit. Work stops immediately after that evidence commit. No
baseline, Random, ES-cold, ES-warm, candidate, r3, or adaptive retry is part
of this study.
