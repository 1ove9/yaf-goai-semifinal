# From a static dual-band negative result within a frozen search space, budget, and seed set to a shared-hardware two-state computational hypothesis

## Technical summary

Within the frozen search space, budget, and seed set, YAF found one NEC2-valid, 21-point-audited paired-state computational hypothesis, but the 4.674% descriptive reduction missed the frozen 10% effect gate, cross-seed stability was not established, and independent openEMS confirmation was not authorized.

The final verdict is `insufficient_evidence`. The scientific asset is a source-addressed,
falsifiable hypothesis plus an auditable explanation of why it was not upgraded to a discovery.

## Key findings

The frozen matrix executed 2,700 paired evaluations and 5,400 real NEC2 subprocess curves. Geometry validation rejected 3,510 proposals before they could spend accepted budget. Only 48 valid pairs appeared, all in one of nine cells.

| Agent | Seed | Accepted | Valid | Valid rate | Rejected |
| --- | --- | --- | --- | --- | --- |
| random | 101 | 300 | 0 | 0.00% | 479 |
| random | 202 | 300 | 0 | 0.00% | 562 |
| random | 303 | 300 | 0 | 0.00% | 491 |
| es-cold | 101 | 300 | 0 | 0.00% | 153 |
| es-cold | 202 | 300 | 0 | 0.00% | 624 |
| es-cold | 303 | 300 | 0 | 0.00% | 193 |
| es-warm | 101 | 300 | 48 | 16.00% | 536 |
| es-warm | 202 | 300 | 0 | 0.00% | 218 |
| es-warm | 303 | 300 | 0 | 0.00% | 254 |

The prior static Day 6 study is historical context bound to commit `acbf4736b8755b682d215e16fe479ffff534360d`; its committed summary verdict was `insufficient_evidence`. It supports only a bounded negative result within its frozen search space, budget, and seed set. It does not show that static dual-band operation is impossible.

A raw-score leader appeared to improve the manual reference by 20.583%, but its two minima
were at sweep endpoints and the preregistered internal-minimum gate excluded it. The frozen
validity-first candidate improved the worse-state reflected-power fraction by only 4.674341%.

## Candidate and gate ledger

The manual comparator assembled 5,184 pairs, scored 756, and produced 0 valid pairs. Its selected A minimum was index 100, so it is a frozen diagnostic comparator, not a strongest-baseline claim.
| Gate | Status | Evidence |
| --- | --- | --- |
| Shared hardware hash | PASS | b6f72349504b6994a10ff9d32ffb7059424073fb25bc2900860f7e1348b9340c |
| Distinct A/B geometry | PASS | state hashes differ |
| 21-point discrete trajectory | PASS | clearance 0.202752 mm |
| NEC2 state A internal minimum and S11<=-6 dB | PASS | 2.4930 GHz / -6.874 dB |
| NEC2 state B internal minimum and S11<=-6 dB | PASS | 5.7355 GHz / -16.090 dB |
| Reflected-power reduction >=10% | FAIL | 4.674341% |
| Cross-seed stability | NOT ESTABLISHED | 1/9 cells valid |
| Manual comparator validity | NOT VALID | 0/5,184 assembled pairs valid; selected A index 100 |
| 5.8 GHz openEMS rod instrument | NOT RELEASED | repair_not_confirmed |
| Candidate openEMS cross-check | NOT AUTHORIZED | not run |
| Continuous mechanics / manufacturing | OUT OF SCOPE | ideal PEC model only |

## Instrument outcome

The terminal thin-box anchor reached 0.680% last-step movement, 1.361% NEC2/openEMS frequency gap, and Pearson 0.969483, but its 32x minimum was just above the frozen band edge, so the anchor was not released.

The bounded rod-renderer repair then produced both repaired probe files but zero parseable
samples. The instrument was NOT RELEASED before NEC2 or the openEMS science ladder could
run. This is an instrument failure record, not evidence for or against the candidate geometry.

## Scope, data, and metric definitions

The search object is one shared, quantized ideal telescopic PEC meander hardware identity
with two actuator states. State A targets 2.40-2.50 GHz; state B targets 5.725-5.875 GHz.
For each state, L=10^(S11/10) and state FoM=1-L. The paired base_score is
min(FoM_A,FoM_B)=1-max(L_A,L_B). The effect gate is a separate comparison of
max(L_A,L_B): it requires max(L_candidate)<=0.90*max(L_manual) in the NEC2
reference instrument. A high base_score is therefore not itself an effect-gate pass.

Search validity additionally requires S11<=-6 dB and selected index 3..97 inclusive.
The frozen candidate uses A index 93 and B index 7; each is four bins inside the nearest edge guard.

## Methodology and reproducibility

Candidates were selected from archived JSONL only after the 9-cell matrix completed. Selection
was validity-first, then score, then deterministic hash/run/step tie-breakers. The freeze
recomputes metrics, geometry hashes, the pair hash, and the 21-point trajectory from committed
source bytes. `scripts/semifinal_demo.py --verify` performs this reconstruction and verifies
the full SHA-256 archive without invoking any solver.

## Limitations and uncertainty

Only ES-warm seed 101 produced valid pairs; cross-seed stability was not established. The candidate's
minimum clearance is only 2.752 um above the frozen boundary. Realized gain, lambda/40 effect
direction, continuous motion, material loss, sleeve overlap, contact resistance, stress,
actuator volume, and manufacturing tolerance were not established. Independent openEMS
candidate curves do not exist because the instrument gate blocked them. The manual comparator
was nonvalid and is not evidence that it is the strongest achievable baseline.

## Recommended next steps

1. Treat the current object as a hypothesis-library entry, not a discovery.
2. Start a new preregistered study around the sparse warm-101 feasible region with robustness
   and clearance margins in the objective; do not alter this batch retrospectively.
3. Any future rod repair must be a separate preregistered study; no rod-r3 is authorized in
   this submission cycle. Release a 5.8 GHz port instrument before any candidate cross-check.
4. Add lossy telescoping contacts and actuator geometry, then fabricate and measure only after
   the simulation gate chain passes.

## Further research question

Can a prospectively registered robust search find this paired-state feasible region across
multiple seeds while passing the unchanged 10% effect gate and an independently released
openEMS instrument?
