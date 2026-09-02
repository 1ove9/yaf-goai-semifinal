# Day 5 wire-v6 v2-space abort

`day5-wire-v6` failed before a numeric result because the execution sandbox
blocked WSL (`E_ACCESSDENIED`). That failed preflight is archived as
`day5-wire-v6-wifi24-classic-s0`.

The real-solver retry `day5-wire-v6r1` was stopped after its preregistered sanity
check failed. Four GP seeds completed 400 real NEC2 subprocess evaluations each.
Their best rows were:

| Seed | Source step | Score | S11 | Narrow-band minimum | Total length | Valid internal target resonance |
|---:|---:|---:|---:|---:|---:|---|
| 101 | 11 | 0.705702 | -6.074 dB | 2.500 GHz | 79.898 mm | no (edge) |
| 202 | 290 | 0.694399 | -5.976 dB | 2.500 GHz | 77.958 mm | no (edge and depth) |
| 303 | 317 | 0.700211 | -5.919 dB | 2.500 GHz | 79.900 mm | no (edge and depth) |
| 404 | 219 | 0.700211 | -5.919 dB | 2.500 GHz | 79.900 mm | no (edge and depth) |

Seed 505 was stopped after 132 logged evaluations and is archived as failed with
the explicit sanity-failure reason. No Random run was started. All numeric rows
use solver mode `subprocess`; no fallback result was accepted.

The fixed top-1 diagnostic `day5-wire-v6r1-crosscheck-top1` measured 2.560 GHz
in lambda/20 NEC2 and 2.720 GHz in 2x openEMS, a 5.882353% gap with Pearson
0.578559. Protocol v2.1 classified it `DIVERGENT`. Inverse-length estimates put
2.45 GHz at 83.484 mm (NEC2) or 88.703 mm (openEMS), outside v2's 80 mm limit.
The batch is therefore an honest `invalid_search_boundary` result, not a GP vs
Random comparison and not a discovery verdict.

