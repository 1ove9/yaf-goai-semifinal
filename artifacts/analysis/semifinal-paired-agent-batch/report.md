# Semifinal paired-state NEC2 candidate freeze

## A NEC2-valid two-state computational hypothesis emerged, but it is not a confirmed discovery

The frozen nine-cell matrix completed 2,700 paired evaluations (5,400 real NEC2 subprocess curves) and recorded 3,510 geometry rejections without spending evaluation budget. es-warm seed 101 (48) supplied 48 NEC2-valid paired proposals; the remaining 8 cells produced none.

The preregistered eligibility-first rule froze one auditable NEC2-only hypothesis. The same ideal telescopic meander model predicts state A at 2.4930 GHz with S11=-6.874 dB and state B at 5.7355 GHz with S11=-16.090 dB; its 21-point discrete trajectory passes the geometry audit.

The preregistered NEC2 effect comparison failed: worst-state reflected power changed by 4.674% versus the frozen manual template against a 10.0% reduction threshold. Cross-seed stability, lambda/40 direction, gain guardrails, and openEMS confirmation are not established. The verdict ceiling is `insufficient_evidence`.

## Candidate card: paired-state hypothesis 8a4ad18c710e...

**Status:** `NEC2-only / insufficient_evidence`
**Claim boundary:** this catalog label is not `YAF-M1`, a confirmed improvement, a new invention, or a manufacturable antenna.

| Frozen field | Value |
| --- | --- |
| Source | `semifinal-paired-es-warm-s101`, step 213 |
| Pair SHA-256 | `8a4ad18c710ec185728fd5bff0e6f16461aea29362024893e1bb6ddd3dcc73ca` |
| Hardware SHA-256 | `b6f72349504b6994a10ff9d32ffb7059424073fb25bc2900860f7e1348b9340c` |
| Turn count | 3 |
| Feed-gap ratio | 58388 ppm |
| Terminal ratio | 87831 ppm |
| State A wire length / span | 70.731 mm / 0.998536 |
| State B wire length / span | 26.057 mm / 0.760951 |
| Discrete trajectory | 21 points; valid=true |
| Minimum clearance | 0.202752 mm |
| Minimum pitch | 3.512815 mm |
| Minimum height | 0.405504 mm |

The endpoint states share one quantized hardware identity. The ideal model changes total wire length from 70.731 mm to 26.057 mm and span ratio from 0.998536 to 0.760951. It does not model sleeve overlap, contact resistance, actuator volume, stress, conductor loss, or a continuous-motion proof.

## Eligibility, not raw score, determined the frozen objects

Each pool is first restricted to valid pairs when any exist, then sorted by base score. The ES candidate is therefore not replaced by a higher raw score whose minima sit at sweep boundaries.

| Category | Source | Valid pool | Base score | Worst reflected power | Status |
| --- | --- | ---: | ---: | ---: | --- |
| top-es | `semifinal-paired-es-warm-s101` step 213 | 48/1800 | 0.794583 | 0.205417 | eligible |
| top-random | `semifinal-paired-random-s202` step 130 | 0/900 | 0.534009 | 0.465991 | diagnostic only |
| manual-baseline | `semifinal-paired-manual-baseline` step 288 | 0/756 | 0.784511 | 0.215489 | diagnostic only |

| Category | State | Selected frequency | S11 | Index | Valid internal minimum |
| --- | --- | ---: | ---: | ---: | --- |
| top-es | A | 2.4930 GHz | -6.874 dB | 93 | true |
| top-es | B | 5.7355 GHz | -16.090 dB | 7 | true |
| top-random | A | 2.5000 GHz | -3.316 dB | 100 | false |
| top-random | B | 5.7250 GHz | -3.555 dB | 0 | false |
| manual-baseline | A | 2.5000 GHz | -6.666 dB | 100 | false |
| manual-baseline | B | 5.8525 GHz | -16.690 dB | 85 | true |

## The preregistered effect gate failed

The comparison is `L_candidate <= 0.90 * L_manual`, where `L` is the worse state's reflected-power fraction in the NEC2 lambda/20 search reference.

| Quantity | Value |
| --- | ---: |
| Top-ES L | 0.205416777468 |
| Manual L | 0.215489492108 |
| Required maximum L | 0.193940542897 |
| Observed reduction | 4.674341% |
| Required reduction | 10.0% |
| Gate | FAIL |

Because this frozen gate failed, even future cross-solver agreement cannot turn this candidate into `confirmed_improvement` without a new, prospectively registered study.

## The validity gate rejected the invalid raw-score leader

The highest raw ES score came from `semifinal-paired-es-warm-s303` step 214: base score 0.828864 and an apparent 20.583% reduction in L. Its minima were at state-A index 100 and state-B index 0. The preregistered internal-minimum condition excluded it from the eligible pool.

## NEC2-valid paired proposals appeared in 1 of 9 cells

| Agent | Seed | Accepted | Valid | Valid rate | Best raw | Best valid | Rejections |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| random | 101 | 300 | 0 | 0.00% | 0.402942 | - | 479 |
| random | 202 | 300 | 0 | 0.00% | 0.534009 | - | 562 |
| random | 303 | 300 | 0 | 0.00% | 0.480203 | - | 491 |
| es-cold | 101 | 300 | 0 | 0.00% | 0.807749 | - | 153 |
| es-cold | 202 | 300 | 0 | 0.00% | 0.682302 | - | 624 |
| es-cold | 303 | 300 | 0 | 0.00% | 0.781984 | - | 193 |
| es-warm | 101 | 300 | 48 | 16.00% | 0.799312 | 0.794583 | 536 |
| es-warm | 202 | 300 | 0 | 0.00% | 0.828340 | - | 218 |
| es-warm | 303 | 300 | 0 | 0.00% | 0.828864 | - | 254 |

1 of 9 cells contained at least one NEC2-valid pair. The combined ES pool had 48 valid records out of 1,800 accepted pairs. The frozen top-ES source cell (es-warm seed 101) contributed 48. Raw-score differences in cells with zero valid pairs are descriptive only.

## Every number is bound to committed evidence

The freeze reads 2,700 accepted records directly from Git commit `a19684b5449774db82b21907cc11c7874287f838`. It binds each source log and summary to manifest SHA-256 `6de538d4ec44931eda14cd4ce1828b2962176c8af500106f48bb0fbba331ffcb`, recomputes metrics from archived curves, reconstructs selected geometry hashes and the 21-point trajectory, and binds the manual row to its committed warm-parent document. Draft `runs/` files are not inputs.

The G5 supersession prospectively authorized NEC2 hypothesis generation while keeping openEMS locked. The three objects were frozen before any later cross-check output. Exact tables are used instead of a chart because this artifact is a categorical freeze; the full 101-point curves remain in the cited source logs.

## Remaining gates and next action

- `lambda/40` effect direction: not evaluated.
- Realized-gain guardrails: not evaluated; search curves contain no gain.
- Independent openEMS cross-check: not authorized or evaluated.
- Cross-seed stability: limited to 1 of 3 warm seeds and 1 of 6 ES runs.
- Continuous mechanics and manufacturing: outside the ideal-PEC model.

No new solver run is authorized by this freeze. A later study must first preregister and release both 5.8 GHz and 2.45 GHz rod-renderer anchors, then separately authorize exactly the frozen 3 objects times two states. Because the 10.0% effect gate has already failed, cross-checking could establish solver consistency but cannot retroactively produce the frozen positive verdict.

## Further research question

Can a new, prospectively registered search target this apparently seed-local valid region while exceeding the unchanged 10.0% reflected-power gate across multiple seeds? That must be a separate study; it cannot add or swap candidates in this frozen batch.
