# Final patch cross-check: frozen converged-instrument execution note

Status: **frozen before every Day 5-2 numeric run**
Execution ID: `day5-patch-final`

## Candidate and representation

The only candidate is archived run `day2-wifi24-gp-s505`, top-design index 0
(evaluation step 16), geometry hash
`61d215dd9b4e463e7d067f90f1612655ebed0a066f580f9817460c3d6659def1`.
The controlled object is its air variant from `day3-crosscheck-wifi24`.
`build_air_variant` and the equal-exposed-area `build_wire_grid` mapping remain the
Day 3 v1 implementations byte-for-byte; no geometry or feed parameter may be retuned.
Wifi58 and n78 remain `inconclusive_needs_spec_specific_grid_study` and are outside
this execution.

## Unchanged scientific decision

Protocol v2.1 is unchanged: each curve needs a minimum outside the first/last three
samples and at or below -6 dB, followed by resonance difference at or below 5% and
Pearson correlation at or above 0.8. The sweep is exactly the archived Day 3 range
4,098,041,023.321768--6,830,068,372.202946 Hz with 51 samples. S11 depth difference
remains record-only. There is one final comparison and no outcome-driven retry.

## Instrument ladder and resource stop

The archived openEMS 1x curve is reused. OpenEMS runs 2x first; adjacent resonance
movement at or below 3% selects 2x. Otherwise 4x is run only after recording a
fourth-power time estimate from the completed 2x run. The sweep cannot be shortened.

NEC2 uses grid 32, then 36, then 44. Before each run, the exact unknown count
`N=4*g*(g+1)+1`, cubic time prediction from the latest completed grid, and one
complex128 dense-matrix estimate `16*N^2` are recorded. A run is allowed when its
predicted time is at most 10,800 seconds and matrix memory is at most 80% of physical
memory currently available. Equality passes; exceeding either limit stops at the
previous grid and records `infeasible_at_current_compute`. Grid 44 has 7,921 unknowns
and a 957.3 MiB single-matrix estimate. Every completed grid is archived immediately.

After each new NEC2 point, all completed positive monotonically narrowing gaps are
refit to `gap=A*grid**(-p)` in log-log least squares and the upward-rounded grid for 5%
is updated. If frequency passes but Pearson fails, a descriptive Pearson roadmap is
also reported: Pearson is linear in log(gap) between the frozen wire observations
(4.478%, 0.719342) and (1.181102%, 0.955299); its Pearson=0.8 gap is mapped through
the patch power law. This does not modify either verdict threshold.

## Result scope fixed in advance

If the unique final comparison is CONFIRMED, the confirmed object is solver-chain
agreement for the air variant. The Day 2 wifi24 verdict becomes
`confirmed_improvement` with this mandatory scope statement:

> FR4 原设计的性能数字仍以 openEMS 为准，互证确认的是该几何类上 openEMS
> 仪器的可信度。

If frequency passes and Pearson fails, the verdict is DIVERGENT and the report gives
the frozen attribution and Pearson-density roadmap. Protocol completion, not a
preferred verdict, is the acceptance condition. Existing Day 2/3/4 artifacts remain
byte-for-byte unchanged; any resolution is written only under
`artifacts/analysis/day5-patch-final/`.
