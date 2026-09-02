# Day 4 patch divergence attribution

The openEMS reference curve is reused byte-for-byte from archived run `day3-crosscheck-wifi24`; it was not rerun.

| grid intervals | NEC2 f_res (GHz) | gap | min spacing/radius | segments | solve s |
|---:|---:|---:|---:|---:|---:|
| 6 | 6.447600 | 31.111% | 7.726 | 169 | 0.500 |
| 12 | 4.207300 | 14.445% | 7.886 | 625 | 7.610 |
| 24 | 4.480500 | 8.889% | 7.583 | 2401 | 295.125 |

## Frozen-rule attribution

Verdict: `instrument_boundary`. Gap(24)/gap(6) is 0.285728; monotonic narrowing is True. The preregistered log-log trend estimate for reaching 5% is grid_intervals=44.

## Day 3 reclassification appendix

- `day3-crosscheck-wifi24`: reclassified by the v2 convergence verdict above; the original v1 DIVERGENT record remains unchanged.
- `day3-crosscheck-wifi58`: `inconclusive_needs_spec_specific_grid_study`; wifi24 convergence is not silently generalized across frequency and geometry.
- `day3-crosscheck-n78`: `inconclusive_needs_spec_specific_grid_study`; the archived v1 DIVERGENT result remains valid as a v1 observation.

S11-depth differences remain descriptive only under protocol v2.
