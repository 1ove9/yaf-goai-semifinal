# Day 5-2 patch instrument convergence

The candidate, air transformation, 51 samples, and 4.098041023--6.830068372 GHz sweep are frozen in `docs/patch-crosscheck-final-execution-note.md`.

## openEMS self-check

| refinement | f_res GHz | S11 dB | predicted s | actual wall s | shift/action | source |
|---:|---:|---:|---:|---:|---|---|
| 1x | 4.917649 | -36.086940 | n/a (archived) | 4.093 | baseline | `day3-crosscheck-wifi24` |
| 2x | 4.917649 | -36.107923 | 65.488 | 4.112 | 0.000000% / selected | `day5-patch-final-openems-2x` |

Selected openEMS refinement: 2x. The final adjacent shift is at or below the frozen 3% threshold.

## Patch NEC2 ladder

| grid | segments | f_res GHz | S11 dB | gap to Day3 openEMS | predicted s | actual wall s | matrix MiB | grid for 5% | source |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 6 | 169 | 6.447600 | -3.516596 | 31.111425% | n/a | 0.500 | n/a | n/a | `day4-attribution-wifi24` |
| 12 | 625 | 4.207300 | -17.922365 | 14.444894% | n/a | 7.610 | n/a | n/a | `day4-attribution-wifi24` |
| 24 | 2401 | 4.480500 | -18.987327 | 8.889394% | n/a | 295.125 | n/a | n/a | `day4-attribution-wifi24` |
| 32 | 4225 | 4.589800 | -18.212608 | 6.666788% | 1608.087 | 1626.614 | 272.379 | 44 | `day5-patch-final-nec2-grid32` |
| 36 | 5329 | 4.589800 | -18.291499 | 6.666788% | 3263.936 | 3091.771 | 433.323 | 47 | `day5-patch-final-nec2-grid36` |
| 44 | 7921 | 4.644500 | -18.411526 | 5.554467% | 10153.371 | 9301.312 | 957.371 | 48 | `day5-patch-final-nec2-grid44` |

The fixed-reference patch gap sequence is `g6:31.111% -> g12:14.445% -> g24:8.889% -> g32:6.667% -> g36:6.667% -> g44:5.554%`; monotonically non-increasing: True. Grid 44 remains above 5%, so the current power-law roadmap is grid 48. The wire-reference Pearson roadmap is grid 94 and is descriptive only.

## Two native-geometry convergence studies

| geometry study | fixed independent reference | resolution/gap sequence | monotonic non-increasing |
|---|---|---|---|
| patch air variant | archived openEMS 1x (`day3-crosscheck-wifi24`) | g6:31.111% -> g12:14.445% -> g24:8.889% -> g32:6.667% -> g36:6.667% -> g44:5.554% | True |
| meander wire | openEMS 2x (`day5-wire-v6r2-convergence-top1`) | lambda/20:5.970% -> lambda/40:5.970% -> lambda/80:4.478% | True |

These fixed-reference studies show the same discretization-driven narrowing in two geometry classes. This statement does not conceal the later Day 5-1b re-reference to converged openEMS 8x, whose final NEC2 gap sequence was not strictly monotonic; that separate attribution remains unchanged.

![Patch and wire fixed-reference convergence](convergence-comparison.png)
