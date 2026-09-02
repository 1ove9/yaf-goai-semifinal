# Day 3 cross-solver verification

## Scope

Each comparison transforms one archived Day 2 GP design into the preregistered air-substrate variant, then compares real openEMS EC-FDTD with a real NEC2 finite wire-grid MoM model. This validates only the air variant; it does not directly validate the original FR4 substrate model.

| Spec | openEMS f_res | NEC2 f_res | delta f | S11 depth delta | Cross-check | Day 2 verdict | Sources |
|---|---:|---:|---:|---:|---|---|---|
| n78 | 6.944087 GHz (-13.925 dB) | 9.019300 GHz (-5.030 dB) | 29.88% | 8.895 dB | DIVERGENT | insufficient_evidence | `day2-n78-classic-s0`, `day2-n78-gp-s101`, `day2-n78-random-s101`, `day2-n78-gp-s202`, `day2-n78-random-s202`, `day2-n78-gp-s303`, `day2-n78-random-s303`, `day2-n78-gp-s404`, `day2-n78-random-s404`, `day2-n78-gp-s505`, `day2-n78-random-s505`, `day3-crosscheck-n78` |
| wifi24 | 4.917649 GHz (-36.087 dB) | 6.447600 GHz (-3.517 dB) | 31.11% | 32.570 dB | DIVERGENT | insufficient_evidence | `day2-wifi24-classic-s0`, `day2-wifi24-gp-s101`, `day2-wifi24-random-s101`, `day2-wifi24-gp-s202`, `day2-wifi24-random-s202`, `day2-wifi24-gp-s303`, `day2-wifi24-random-s303`, `day2-wifi24-gp-s404`, `day2-wifi24-random-s404`, `day2-wifi24-gp-s505`, `day2-wifi24-random-s505`, `day3-crosscheck-wifi24` |
| wifi58 | 11.277552 GHz (-7.460 dB) | 16.229000 GHz (-3.445 dB) | 43.91% | 4.015 dB | DIVERGENT | insufficient_evidence | `day2-wifi58-classic-s0`, `day2-wifi58-gp-s101`, `day2-wifi58-random-s101`, `day2-wifi58-gp-s202`, `day2-wifi58-random-s202`, `day2-wifi58-gp-s303`, `day2-wifi58-random-s303`, `day2-wifi58-gp-s404`, `day2-wifi58-random-s404`, `day2-wifi58-gp-s505`, `day2-wifi58-random-s505`, `day3-crosscheck-wifi58` |

## Interpretation

- **n78:** The air-variant cross-solver result is DIVERGENT (or the Day 2 improvement threshold was not met), so the positive verdict remains insufficient_evidence; the disagreement is retained as an anomaly signal.
- **wifi24:** The air-variant cross-solver result is DIVERGENT (or the Day 2 improvement threshold was not met), so the positive verdict remains insufficient_evidence; the disagreement is retained as an anomaly signal.
- **wifi58:** The air-variant cross-solver result is DIVERGENT (or the Day 2 improvement threshold was not met), so the positive verdict remains insufficient_evidence; the disagreement is retained as an anomaly signal.

A CONFIRMED row means only that GP found a design better than the classic reference and that the preregistered air-variant cross-solver check agreed. It is not a claim that a new antenna was invented.

## Pre-decision failed attempts

- `day2-wifi24-gp-s505` design index 0: nec2c exited with 255: nec2c: Input file name too long - aborting (no numeric decision; thresholds were not applied).
- `day2-wifi24-gp-s505` design index 0: nec2c produced no parseable FREQUENCY blocks before the execution-card fix (no numeric decision; thresholds were not applied).
- `day2-wifi24-gp-s505` design index 0: nec2c produced no parseable FREQUENCY blocks before the execution-card fix (no numeric decision; thresholds were not applied).
