# Day 5 meander solver attribution

Source design: `day5-wire-v6r2-wifi24-gp-s202`, step 255, selected by the
preregistered target-band-valid/score/run-ID/step ordering before any
cross-solver result. Numeric evidence is archived in
`day5-wire-v6r2-convergence-top1`.

| Solver | Discretization | f_res | S11 | Gap to openEMS 2x |
|---|---|---:|---:|---:|
| NEC2 | lambda/20 | 2.520 GHz | -6.369 dB | 5.970% |
| NEC2 | lambda/40 | 2.520 GHz | -6.547 dB | 5.970% |
| NEC2 | lambda/80 | 2.560 GHz | -6.532 dB | 4.478% |
| openEMS | 1x mesh | 2.840 GHz | -9.594 dB | n/a |
| openEMS | 2x mesh | 2.680 GHz | -7.887 dB | reference |

The NEC2 gaps narrow monotonically, but `gap(80) / gap(20) = 0.75`. This is
neither below the exclusive 0.5 instrument-boundary threshold nor at/above the
0.8 plateau threshold. The frozen result is therefore
`inconclusive_needs_finer_segmentation`. Lambda/80 already reaches the 5%
frequency-agreement gate, so no density beyond 80 is needed merely to cross
that gate; the extrapolated-density field is consequently null. Finer density
would still be required to resolve the attribution category.

openEMS moves from 2.840 to 2.680 GHz between 1x and 2x, a 5.970% shift. It
fails the preregistered 3% self-convergence check and is mesh-sensitive at the
tested resolutions. The final top-2 checks still use the frozen lambda/80 NEC2
and 2x openEMS settings. Both frequency gaps pass 5%, but Pearson correlations
0.719342 and 0.718527 fail 0.8, producing two `DIVERGENT` decisions. This
evidence does not permit `confirmed_improvement`.
