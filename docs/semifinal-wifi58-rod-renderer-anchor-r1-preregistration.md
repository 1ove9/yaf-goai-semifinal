# Semifinal 5.8 GHz resolved-rod renderer anchor r1 preregistration

Status: frozen before any rod-renderer numerical solve
Run family: `semifinal-wifi58-rod-renderer-anchor-r1-*`

## Role and immutable boundary

This is a bounded instrument-qualification study authorized as new follow-up
research by the final sentence of plan v3.4. It does not modify the paired-state
scientific object. Section 4.3 geometry equations, section 7 score, section 8
mesh table, every threshold, the budget formula, parent-selection rules, and the
1.5--6.5 GHz/251-point sweep remain unchanged. Every r1/r2/r3 archive byte is
immutable. The frozen r3 combined evidence hashes are:

| Evidence | SHA-256 |
|---|---|
| `log.jsonl` | `0e9da50876fa679870160ba9349a8391c18d7917355d7cef50177899bb967a9f` |
| `summary.json` | `d5ac661dc0251d0e7dcecf7a88d967a2c510e568e3338a45c5e84399254f67a9` |

The r2 geometry is reused byte-for-byte and must pass this SHA-256 gate before
every solve:

```text
1c0e018ac1e65aacf30ac158ef2336f461b430036b0c6ad9eb2bfefb15ba0d5a
```

The executable binary64 length remains
`0.0258441774 * 5480000000 / 5800000000 = 0.02441829175034483 m`;
the feed gap remains `0.000600 m`; `wire_radius_m` remains `5e-5`; and
the edge order, y-axis orientation, metadata, sweep, NEC2 `EK=false`, and real
subprocess requirements remain unchanged. The representation selector belongs
only in `solver_settings`, never geometry metadata.

This study is not anchor r4. R3's no-r4 boundary remains binding for the
zero-width thin-line ladder, which receives no 64x level. This study qualifies
one different representation once.

Forbidden changes include changing the default thin-line behavior, bulk
`max_step`, margin, grading ratio 1.4, port resistance, `end_criteria=1e-4`,
EK, a cylinder, a generic or free-form Wire, deriving length from openEMS,
changing the 5.725--5.875 GHz band, raising the 3600-second timeout, running a
2.45 GHz anchor, changing `paired_meander.py`, or starting G6, a baseline,
Random, ES-cold, ES-warm, or any candidate.

## Motivation and bounded question

R3's thin-line openEMS sequence was 5.36, 5.58, 5.70, 5.80, 5.84, and
5.88 GHz. Its last two increments were both +40 MHz, its Richardson diagnostic
was unavailable, and NEC2 resonated at 5.800 GHz. No grid-independent limit was
established over that bounded 1x--32x ladder; the observed drift is consistent
with a mesh-dependent effective-radius effect.

The meander builder currently serializes every centerline segment through
`add_metal_box(start, stop)` with equal transverse start/stop coordinates. The
openEMS conductor is therefore a zero-width PEC line and the frozen 0.05 mm
radius does not enter that representation. R3 changed only the transverse grid
distance `min(1.5 mm, pitch/2)/refinement`, which was about
1.292 mm/refinement and agrees with its archived mesh sizes.

R3 did not record executed time steps or a termination reason. Its 32x nominal
physical window is approximately 3.1 ns under the disclosed CFL proxy, and
whether a step cap truncated the response cannot be recovered.

This study asks whether a finite PEC square rod whose cross-section is resolved
by an exterior near-field mesh provides a converged, valid 5.8 GHz openEMS
anchor under the unchanged gates.

## Retrospective diagnostic model

This model was built after observing r3 and is permanently marked
`diagnostic_only`, `retrospective=true`, and `affects_verdict=false`. It
cannot select a setting, stop a run, or affect a verdict.

With `L=0.02441829175034483 m`, `f_half=c0/(2L)=6.1387 GHz`, and the
0.05 mm NEC2 radius at 5.800 GHz, define:

```text
K = (1 - 5.800/6.1387) * ln(L/a) = 0.3416
f(r) = f_half * (1 - K/ln(L/r))
```

| Level | Delta | `r_eff=0.2 Delta` | Model (GHz) | r3 (GHz) |
|---|---:|---:|---:|---:|
| 8x | 161.5 um | 32.3 um | 5.822 | 5.800 |
| 16x | 80.8 um | 16.2 um | 5.852 | 5.840 |
| 32x | 40.4 um | 8.1 um | 5.877 | 5.880 |

The `r_eff ~= 0.2 Delta` source remains unverified and no DOI may be added
without checking the primary source. A descriptive square-rod equivalent
radius `0.59 * 2a = 59 um` predicts 5.791 GHz, but this prediction is not a
gate.

## The only representation modification

The qualified object is the combined instrument change **square-rod conductor
plus matching finite-area lumped port**. A frequency movement must not be
attributed solely to the arm radius.

- Every axis-aligned centerline segment becomes a PEC box. Its axial limits are
  exactly its endpoints, without end extension. Its two transverse limits are
  `center-a` and `center+a`.
- The adapter reads `a` from `mesh.metadata["wire_radius_m"]`. It must not
  import a NEC2 or `yaf_ai` constant. The anchor runner rejects a missing value
  or any value other than the frozen `5e-5 m`.
- The lumped port keeps its axis, gap endpoints, impedance, and direction, but
  its two transverse limits become `center-a` and `center+a` so its section
  matches the rod.
- `solver_settings["openems_wire_representation"]` accepts only
  `"thin_line"` and `"rod"`. The absent/default value is `"thin_line"`
  and must rebuild the legacy XML byte-for-byte. This anchor uses `"rod"`.

## Frozen rod mesh

At refinement `q` in `(1,2,4,8)`, set `resolution=a/q`. For each
transverse coordinate of every rod and the port, the mandatory pre-smoothing
lines are:

```text
center-a, center, center+a
center-a-k*resolution and center+a+k*resolution for k=1..q
```

The exterior band extends from each surface by `a`, and its seed spacing is
50, 25, 12.5, and 6.25 micrometres. No extra interior conductor line is
intentionally added beyond the fixed centre line. Outside this band, all
axial-line, grading, smoothing, bulk-step, and margin rules are byte-for-byte
the r3 rules.

Every mandatory line must survive final smoothing. The final grid quality
invariant is:

```text
0.5 * a/q <= final minimum cell size <= a/q
```

A violation is a builder defect to be fixed before the implementation commit;
it is not a result-dependent tuning permission. Mandatory pre-smoothing seed
spacing equals `a/q`; final smoothing may add smaller cells within the stated
invariant. All CFL calculations use the final smoothed x/y/z arrays.

## Frozen physical-time window

For final smoothed minimum spacings, define:

```text
dt_proxy = 1 / (c0 * sqrt(1/dx_min^2 + 1/dy_min^2 + 1/dz_min^2))
```

Rebuild the default r3 1x XML and require SHA-256
`cfeb036bb550cf2a5847f4388b8ac2556a8752eff70180d555e6d1ce29aa94ad`.
Set `T_target=40000*dt_proxy(legacy r3 1x final grid)`. For each rod grid:

```text
number_of_timesteps = ceil(T_target / dt_proxy(rod final grid))
```

`end_criteria=1e-4` and the 3600-second process timeout remain unchanged.
`T_target` is a conservative safety window; the timeout is the practical
compute boundary and both limits are terminal.

For each level, parse and record `executed_timesteps`,
`openems_timestep_seconds` when available, `dt_proxy`,
`terminated_by` in `{end_criteria,timestep_cap,unknown}`, and the last 20
stdout lines. Record:

```text
actual_simulated_time_seconds = executed_timesteps * openems_timestep_seconds
estimated_simulated_time_seconds = executed_timesteps * dt_proxy
```

The actual field is `null` when the real time step cannot be parsed; a proxy
must never be presented as actual time. A 4x or 8x `timestep_cap` makes that
decision input invalid and yields `not_released_not_converged`. An `unknown`
termination is an execution failure, not a scientific verdict.

## Execution failure policy

A 3600-second timeout, OOM, crash or non-zero exit, missing port data, or
unparseable termination reason produces `execution_failed`, archives a
zero-result failure record, emits no scientific verdict, and terminates this
cycle without retry.

Only a verifiable host restart, power failure, or accidental user termination
may authorize one byte-identical replacement. That replacement requires a new
DECISIONS entry before execution and may not alter any parameter or timeout.

## Build-only resource disclosure

Before solving, build all four final rod meshes without time stepping and
record x/y/z line counts, cells, per-axis minimum and maximum cell sizes,
`dt_proxy`, maximum steps, and `cells*maximum_steps`. These values disclose
cost only; they cannot change the ladder, settings, gates, or stopping rule.
No runtime prediction is preregistered.

## Frozen ladder and decision inputs

Run one NEC2 curve, then all four rod levels `(1x,2x,4x,8x)` in order unless
an execution failure terminates the study. No numerical result may adaptively
skip, replace, reorder, or add a level.

Self-convergence uses only full-sweep internal minima at 4x and 8x. Agreement
uses only NEC2 and 8x. Intermediate levels cannot substitute for a decision
input. The full-sweep internal-minimum and movement definitions are exactly
the prospective r3 definitions.

## Unchanged release gates

Release requires all five conditions:

1. NEC2 has a valid 5.725--5.875 GHz internal minimum at S11 <= -6 dB.
2. OpenEMS 8x has a valid 5.725--5.875 GHz internal minimum at S11 <= -6 dB.
3. NEC2 versus openEMS 8x relative resonance difference is <= 0.03.
4. Their full 251-point Pearson correlation is >= 0.9.
5. The full-sweep 4x-to-8x movement is <= 0.03.

S11 depth difference remains record-only.

## Exhaustive scientific verdict

`execution_failed` is outside the scientific verdict. Otherwise exactly one
scientific verdict is selected in this order:

1. `not_released_not_converged` if 4x or 8x lacks a full-sweep internal
   minimum, movement is `None` or greater than 3%, or either decision level
   terminates at its time-step cap.
2. `not_released_resonance_invalid` if NEC2 or openEMS 8x fails resonance
   validity. Check NEC2 first and openEMS second. Within a solver report the
   first applicable reason in this order: `no_internal_minimum`,
   `out_of_band_low`, `out_of_band_high`, then
   `depth_above_minus_6_db`.
3. `not_released_agreement` if relative frequency difference is greater than
   3% or Pearson correlation is below 0.9.
4. `released`, with `anchor_released=true`, if every gate passes.

Every non-released verdict sets `anchor_released=false`. The invalid-resonance
record carries `solver` in `{nec2,openems_8x}` and the frozen reason.

## Preregistered outcome branches

The retrospective model predicts 5.791 GHz for the square rod, but both
branches are equally valid:

- If the scientific verdict is `released`, the only permitted release text is:
  "rod renderer is released for the 5.8 GHz instrument path. Paired-state
  openEMS cross-check execution remains blocked until a separately
  pre-registered 2.45 GHz rod compatibility anchor passes."
- Any non-released verdict or `execution_failed` terminates the 5.8 GHz rod
  instrument for this submission cycle.

There is one representation, one four-level ladder, and one attempt. There is
no rod r2, third representation, cylinder, EK, sphere-ended Wire, thin-line
extension, or result-driven retry.

## G5 semantic amendment and future boundary

This prospective sequencing amendment is independent of either rod outcome:

> NEC2 remains the preregistered hypothesis-generation and ranking oracle. The rod
> anchors gate only openEMS candidate cross-check execution and the final cross-solver
> verdict. NEC2-only baseline, Random, ES-cold, and ES-warm runs may proceed under their
> existing preregistration, but openEMS results must never influence ranking, parent
> selection, or top-candidate selection. Until both 2.45 and 5.8 GHz rod anchors are
> released, the final verdict ceiling remains `insufficient_evidence`.

The amendment is valid only while all three invariants remain true: the manual
baseline archive commit precedes every ES-warm evaluation; the unique warm
parent rule remains unchanged; and each baseline/Random/ES implementation,
test, and preregistration gate passes before its numerical execution.

A released result authorizes only a separately preregistered, one-shot
2.45 GHz rod compatibility anchor as the next openEMS task. Only after both
anchors release may all six paired-state openEMS curves use `"rod"` and map
the section 13 candidate 1x-to-2x rule in rod units. Failure at either frequency
makes openEMS diagnostic-only and retains the `insufficient_evidence` ceiling.
No 2.45 GHz code or run belongs to this task.

## Non-decision diagnostics

All records set `affects_verdict=false`: the fixed r3 Richardson formula over
rod 2x/4x/8x; the NEC2 rerun minus archived r3 NEC2 curve comparison; and the
retrospective radius model and square-rod prediction. Model records also set
`diagnostic_only=true` and `retrospective=true`.

## Evidence, tests, and stopping rule

The implementation must preserve the default thin-line XML hash and all r1,
r2, and r3 archive hashes. It must test rod geometry and port bounds, mandatory
and final mesh invariants, the fixed ladder and decision inputs, CFL arithmetic,
the three termination states, actual-versus-estimated time fields, all verdict
branches and reason priority, solver-settings isolation, geometry identity, and
pure diagnostic-model arithmetic. No fitted-error assertion may be attached to
the retrospective model.

Pytest, Ruff, and strict mypy must pass before any solve. The combined run or
failure record is archived verbatim, the manifest is verified in the working
tree and a fresh clone, and evidence is committed. Work then stops immediately,
without a 2.45 GHz anchor, G6, baseline, Random, either ES variant, a candidate,
or a paired-meander representation change.
