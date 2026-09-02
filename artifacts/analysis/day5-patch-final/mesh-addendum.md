# Mesh-count addendum for the Day 5-2 openEMS self-check

## Audit conclusion

The pre-fix 2x/1x cell ratio was 1.000000000, classified `ineffective` by the preregistered rule. The archived 2x XML was byte-identical to 1x, so the original self-convergence claim is retracted as `self_convergence_not_established` for that run.

Root cause: The parametric patch XML builder did not read openems_mesh_refinement; both archived diagnostic settings therefore produced the same XML. The repair scales only the non-default patch bulk and metal-edge resolution by the requested refinement.

## Mesh evidence

Line and cell-count triples are x/y/z. Cell-size triples are x/y/z in mm.

| stage | refinement | grid lines | axis cells | total cells | min cell mm | max cell mm | XML SHA-256 |
|---|---:|---:|---:|---:|---:|---:|---|
| pre-fix audit | 1x | 53/63/37 | 52/62/36 | 116064 | 1.055121 / 1.055121 / 0.400000 | 3.016406 / 2.541094 / 2.110242 | `facda569a7662662a4982be1a33d2f9310d77e9a3320b42e9e8db77d63f4379a` |
| pre-fix audit | 2x | 53/63/37 | 52/62/36 | 116064 | 1.055121 / 1.055121 / 0.400000 | 3.016406 / 2.541094 / 2.110242 | `facda569a7662662a4982be1a33d2f9310d77e9a3320b42e9e8db77d63f4379a` |
| post-fix verification | 1x | 53/63/37 | 52/62/36 | 116064 | 1.055121 / 1.055121 / 0.400000 | 3.016406 / 2.541094 / 2.110242 | `facda569a7662662a4982be1a33d2f9310d77e9a3320b42e9e8db77d63f4379a` |
| post-fix verification | 2x | 102/121/58 | 101/120/57 | 690840 | 0.527561 / 0.527561 / 0.400000 | 1.271939 / 1.055121 / 1.579899 | `19a6d94ff0a83e7bb2596d3d1b667d3d15a6d2d3ebcea78eb7f5c4a29176b5c6` |

The repaired 2x/1x ratio is 5.952233251, which is `effective` (effective threshold >=3). The post-fix 1x SHA-256 exactly matches the immutable pre-fix 1x evidence, proving the repair did not change refinement=1.0 output.

## One-shot real 2x recheck

| predicted wall s | actual wall s | f_res GHz | S11 dB | movement | threshold | final claim | source |
|---:|---:|---:|---:|---:|---:|---|---|
| 65.488 | 16.640 | 4.917649228 | -26.357706 | 0.000000000% | <=3% | `established_after_refinement_repair` | `day5-patch-final-openems-2x-mesh-recheck` |

The repaired movement is within 3%; no additional uncertainty footnote is required for the historical resonance-gap ladder.

## Scope

The restored claim applies to the repaired openEMS patch mesh path. It does not reopen or alter the final cross-solver verdict: `DIVERGENT` remains unchanged because the archived grid-44 comparison missed the 5% resonance and 0.8 Pearson gates. No historical run or Day 5-2 analysis file is edited; this addendum and its two source runs are new evidence only.
