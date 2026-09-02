# Semifinal 5.8 GHz meander-renderer anchor r3 preregistration

Status: frozen before any r3 numerical solve
Run family: `semifinal-wifi58-meander-renderer-anchor-r3-*`

## Role and immutable boundary

This is a bounded instrument-certificate study, not a modification of the
paired-state scientific object. Section 4.3 geometry equations, section 7
score, section 8 mesh table, all numerical thresholds, the budget formula,
and parent-selection rules remain unchanged. R1 and r2 source evidence and
all three r2 commits (`7f44ac8`, `45d5aec`, `20d34fa`) are immutable.

The r2 geometry is reused byte-for-byte. R3 must call the r2 geometry builder
and validate the same geometry SHA-256 before every solve:

```text
1c0e018ac1e65aacf30ac158ef2336f461b430036b0c6ad9eb2bfefb15ba0d5a
```

Consequently, the executable binary64 length remains
`0.0258441774 * 5480000000 / 5800000000`, the feed gap remains
`0.000600 m`, and all r2 geometry metadata, vertices, edge order, y-axis
orientation, radius, EK setting, meander dispatch, thin-box mapping, sweep,
and frequency array remain byte-identical. The r3 protocol label belongs to
the run config and must not be injected into geometry metadata.

Forbidden changes include generic-wire, freeform, fallback, EK, radius
matching, changing thin-box half-width to 0.05 mm, redefining the 1x grid,
or calibrating length from any openEMS value.

The immutable archive hashes are:

| Evidence | `log.jsonl` SHA-256 | `summary.json` SHA-256 |
|---|---|---|
| r1 combined | `937bd9d53a992a7bfce54d886652291fbac49c366f8fd617d4681f5ff4258b89` | `61d012118b489634f9e04c4c5a02ada6532edbf3e9088f68806376b6b07f68c7` |
| r2 combined | `8d8387a9859417d6e9f62c07a385ba4d6a89e204e579d6c0359ddeb3b241de2c` | `5c0987c439f21147e187cbc630870b57aaea3e6736569d05d28b232fe2dd7871` |

## Motivation

R2 validated the calibrated geometry model: NEC2 resonated at exactly
5.800 GHz. Its openEMS ladder moved 5.360 -> 5.580 -> 5.700 -> 5.800 GHz,
with adjacent movements of +220, +120, and +100 MHz. The movement did not
show sufficient decay. The 4x global minimum at 5.700 GHz was below the
5.725--5.875 GHz target band, so r2's frozen band-valid movement was
undefined. Its `not_released_not_converged` verdict was correct and remains
unchanged.

R3 asks one question only: does the unchanged openEMS sequence reach a
stable limit inside the target band? It is a single bounded extension, not
a repeated search for a passing refinement.

## The only modification: an unconditional six-level ladder

Run exactly one NEC2 solve followed by openEMS at exactly these density
multipliers, in this order:

```text
(1x, 2x, 4x, 8x, 16x, 32x)
```

All six openEMS levels run unconditionally. No numerical result may stop,
skip, reorder, replace, or add a level. Refinement retains r2's multiplier
parameterization and does not define a new baseline.

The only decision pair is 16x -> 32x. Cross-solver agreement uses only
NEC2 and openEMS 32x. No intermediate level may substitute for either
decision input.

## Prospective definition repair, effective only for r3

R2 exposed an undefined intermediate case: requiring both adjacent levels
to have a target-band minimum prevented a movement calculation when a
converging minimum approached the band from outside. R3 prospectively
repairs only that definition. It does not alter or reinterpret r2 evidence
or its archived verdict.

For the 16x-to-32x movement, each curve contributes its global minimum over
the complete 1.5--6.5 GHz, 251-point sweep. The minimum must:

- be outside the first and last three samples;
- be no higher than either immediate neighbour; and
- be strictly lower than at least one immediate neighbour.

There is no target-band or -6 dB requirement on the 16x movement input.
The relative movement is
`abs(f_16x - f_32x) / f_32x`. Missing full-sweep internal minima produce
`None` and fail convergence.

The existing target-band validity definition, including an internal local
minimum and S11 at most -6 dB in 5.725--5.875 GHz, is applied only to NEC2
and openEMS 32x for release. Threshold values are unchanged.

## Frozen release gates

Release requires every item:

1. NEC2 has a valid target-band internal minimum at S11 <= -6 dB.
2. OpenEMS 32x has a valid target-band internal minimum at S11 <= -6 dB.
3. NEC2 versus openEMS 32x relative resonance difference is <= 0.03.
4. Their full 251-point Pearson correlation is >= 0.9.
5. The full-sweep 16x-to-32x internal-minimum movement is <= 0.03.

S11 depth difference remains record-only. R3 does not modify any r1/r2
threshold.

## Exhaustive four-verdict priority

Exactly one verdict is emitted in this order:

1. If either 16x or 32x lacks a full-sweep internal minimum, their movement
   is `None`, or movement is greater than 3%:
   `not_released_not_converged`.
2. Otherwise, if the 32x full-sweep internal minimum is above 5.875 GHz:
   `not_released_out_of_band_high`.
3. Otherwise, if NEC2 or 32x target-band validity fails, or the frozen
   NEC2-to-32x frequency/Pearson agreement fails:
   `not_released_agreement`.
4. Otherwise: `released` and `anchor_released=true`.

This ordering deliberately requires convergence before attributing a
stable high-side limit. A converged low-side, shallow, non-local, or other
non-high target-band failure maps to `not_released_agreement`; no fifth
scientific verdict is permitted. Every non-released verdict sets
`anchor_released=false`.

## Preregistered prediction branches

Extrapolating the descriptive r2 movement sequence suggests that 16x and
32x will lie around 5.80--5.90 GHz. Both branches are valid outcomes:

- If the sequence converges at or below 5.875 GHz and the last movement and
  all other unchanged gates pass, the verdict is `released`.
- If a converged 32x minimum rises above 5.875 GHz, the verdict is
  `not_released_out_of_band_high`, interpreted as a systematic high-frequency
  offset of the openEMS thin-box representation relative to NEC2 for this
  instrument.

A failure to converge remains `not_released_not_converged`; an agreement
failure remains `not_released_agreement`.

## Descriptive diagnostics that cannot affect the verdict

### Fixed Richardson estimate

Use only the full-sweep internal-minimum frequencies at 8x, 16x, and 32x.
Let `d1 = f16 - f8` and `d2 = f32 - f16`.

- If `d2 == 0`, record `f_infinity = f32`, order `None`, and status
  `exact_last_pair_plateau`.
- If `d1` and `d2` have the same non-zero sign and
  `abs(d1 / d2) > 1`, record
  `p = log2(abs(d1 / d2))` and
  `f_infinity = f32 + d2 / (2**p - 1)`.
- Otherwise record no estimate and status `unavailable` with the reason.

This diagnostic may not alter any verdict, threshold, or refinement.

### R2 reproduction comparison

For 1x, 2x, 4x, and 8x, compare the r3 rerun with archived r2 by recording
`r3_frequency_hz - r2_frequency_hz` and `r3_s11_db - r2_s11_db` exactly.
No tolerance, pass/fail label, retry, or decision effect is attached. Any
difference is reported as an instrument reproducibility observation.

## Evidence and resource recording

For every openEMS level, `summary.json` records x/y/z line counts, total
cells, minimum and maximum cell sizes, peak process-tree MiB, and elapsed
seconds. It also contains all seven curves, the five release-gate values,
the Richardson diagnostic, and the four r2 reproduction rows.

All solvers must report `solver_mode=subprocess`. Fallback is fatal. The
combined run is archived verbatim, added to the manifest, verified in the
working tree and a fresh clone, and committed.

## Bounded stopping rule

This is the final anchor extension in this submission cycle. A non-released
32x result is terminal. There is no r4. After the evidence commit, work
stops immediately: no G6, baseline, Random, ES-cold, ES-warm, candidate,
or further anchor run is authorized.
