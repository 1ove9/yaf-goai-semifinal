# Day 6.5 factorial anchor audit and candidate-B terminal retry

Pre-registration commit: `07a7b576e693e8da566bb287a92d5d3aca03af32`.

No protocol, threshold, sweep, score, candidate, or prior run was changed.

## Factor table

| factor | f_res GHz | delta/decision MHz | result | source run |
|---|---:|---:|---|---|
| F3 NEC2 lambda/80 | 2.280 | 10.000 | segmentation diagnostic | `day65-factor-f3-nec2-lambda80` |
| F3 NEC2 lambda/320 | 2.280 | 10.000 | segmentation diagnostic | `day65-factor-f3-nec2-lambda320` |
| F4 NEC2 0.3 mm gap | 2.290 | 0.000 | paired with F4 openEMS | `day65-factor-f4-nec2-feed-gap-0p3mm` |
| F2 openEMS shortened ends | 2.230 | 20.000 | material | `day65-factor-f2-openems-endcap-shortened` |
| F4 openEMS 0.3 mm gap | 3.500 | 1290.000 | material | `day65-factor-f4-openems-feed-gap-0p3mm` |
| F1 openEMS 8x/320k | 2.200 | 10.000 | minor | `day65-factor-f1-openems-8x` |

## F3 segmentation stability

lambda/80=2.280 GHz, lambda/160=2.290 GHz, lambda/320=2.280 GHz; maximum shift=10.000 MHz. Classification: `segmentation_stable`.

## Per-factor residual frequency bias

These are separate single-factor estimates and are not added together.

| basis | NEC2 GHz | openEMS GHz | residual MHz |
|---|---:|---:|---:|
| radius-matched baseline | 2.290 | 2.210 | 80.000 |
| F1 grid-only | 2.290 | 2.200 | 90.000 |
| F2 endcap-only | 2.290 | 2.230 | 60.000 |
| F4 feed-gap differential | 2.290 | 3.500 | 1210.000 |

## Candidate B terminal outcome

Status: `success`. Timeout authorization: 43200 seconds. Re-verdict run: `day65-repair-crosscheck-top2`. Dual-band verdict: `NO_RESONANCE_IN_BAND`. Discovery verdict: `insufficient_evidence`.

## Correction proposal v2 (not implemented)

- Do not change protocol thresholds from this audit; retain the measured single-factor shifts as an instrument systematic-error budget.
- If F1 is material, pre-register a further adjacent-grid convergence point before using the anchor as a frequency-calibration reference.
- If F2 is material, harmonize the two solvers on physical outer-envelope rather than centerline length in a future, separately preregistered anchor.
- If F4 is material, isolate the two feed representations with a dedicated port-deembedding study before changing any cross-solver gate.
- Candidate B is terminal under this authorization; its outcome must not trigger a third attempt without a new preregistration.
