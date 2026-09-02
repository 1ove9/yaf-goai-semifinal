# Semifinal A-span support causal probe preregistration

Status: frozen before implementation and before every new numerical result.

Study ID: `semifinal-a-span-support-causal-probe-v1`

Source evidence commit: `e5f36fd971a7266531a6d124f553f121379ad889`

## 1. Motivation and scope

The completed B-parent A-only study contains 702 H1 records and no H2 crossing.
A post-hoc descriptive audit found that state A is the worst state in all 702 H1
records and that many state-A controls lie near the frozen
`span_ratio_ppm <= 1_000_000` support limit. That audit does **not** establish a
physical 40 mm box limit. In the frozen centerline equation, `span` is an
intermediate control quantity: at `span_ratio_ppm=1_000_000` the actual
centerline width is approximately 30.49 mm, not 40 mm.

This prospective diagnostic asks one bounded question: holding each selected
hardware identity, state-A wire length, frozen state B, solver, frequency table,
score, and physical 40 mm box fixed, does an isolated extension of the state-A
span-control support produce a consistent NEC2 response and, in at least some
frozen counterfactual blocks, cross the old numerical reference line?

This is a finite-set, model-internal causal probe. Source-unit selection is
motivated by already-observed results and is not an unbiased sample from antenna
space. It cannot establish a real-world causal effect, physical feasibility,
independent-solver confirmation, or a new antenna.

## 2. Frozen source evidence

Before a solver object is constructed, execution must establish all of the
following:

- the source commit is an ancestor of both the preregistration and implementation
  commits;
- the committed and workspace `artifacts/runs/manifest.json` bytes are equal to
  the source blob, contain 254 unique entries, and have SHA-256
  `9f205ae20da00e383750e3fd84acd9b75b824aa9f27e83e002960d93a89204b5`;
- the committed B-completion appendix and report are byte-identical to the
  workspace files and have SHA-256
  `9eb3786fd016e7e314e4c266b13e3d6a03513db5d5e00b202b8732fd3e93aa24`
  and `1d1900d1e1841930e7110dd16363cec470be56e764fb2f0d6f2740cacf9230da`;
- replaying all twenty source logs yields 6,000 accepted records, H1=702,
  H2=0, with p01=267 and p02=435 H1 records;
- the seven frozen runtime paths in section 10 have the listed source blobs and
  workspace bytes equal those blobs;
- every source run log and summary hash equals its unique, non-overwritten
  source-manifest entry.

Any mismatch is a terminal source-gate failure and prohibits all solver calls.

## 3. Frozen ten-block cohort

The cohort is deliberately ES-only so that proposer type is constant and each
of the five preregistered seeds contributes exactly one record for each frozen B
parent. Within each `(parent_id, seed)` ES run, retain H1 records and select the
minimum tuple

```text
(worst_reflected_power_fraction, pair_hash, run_id, step_index, proposal_index)
```

The selection is performed only on source bytes and is frozen below before any
counterfactual solve. Random records are not eligible for this diagnostic and no
algorithm comparison is authorized.

| parent | seed | source run | step/proposal | source pair SHA-256 | A length (um) | A span (ppm) | source A loss |
|---|---:|---|---:|---|---:|---:|---:|
| p01 | 101 | `semifinal-paired-b-completion-p01-es-s101` | 286/286 | `fb98e3539cb47e05d15fd42c16ddbb8a9f6ecf55c51f4b3ea942bbd295835bf3` | 71001 | 981858 | 0.24551036781205307 |
| p01 | 202 | `semifinal-paired-b-completion-p01-es-s202` | 24/24 | `cc678757386ca5cbe25c34b818a151e4556b40a12e4a7ff1f7a4ff02638b40b9` | 70973 | 992531 | 0.23755180106137028 |
| p01 | 303 | `semifinal-paired-b-completion-p01-es-s303` | 265/265 | `59a7e7df8fe7b8c3e6a07333e84ef12099886c5971a9815891ef63e1d041f259` | 70775 | 999881 | 0.23010531242953516 |
| p01 | 404 | `semifinal-paired-b-completion-p01-es-s404` | 209/209 | `d9aa2b8bad62c71b6da2cc988c131de1415333ddbcf2085d53f65c004d551e96` | 70816 | 999368 | 0.23092841432431088 |
| p01 | 505 | `semifinal-paired-b-completion-p01-es-s505` | 109/109 | `6ace3129ef9005e3d3d2ea804e4799f41145a7bda2719f470dcf9f7fe5b1009b` | 70856 | 999628 | 0.23120053766167860 |
| p02 | 101 | `semifinal-paired-b-completion-p02-es-s101` | 164/164 | `754e66368ce1de867994b541a21aa5cbb07d6ef65b13536c2a00cd345d64a8c8` | 70860 | 999705 | 0.23269669380050187 |
| p02 | 202 | `semifinal-paired-b-completion-p02-es-s202` | 283/283 | `efa222ede3e10524564cf438b57c4a45e2def304836db7476aefde8d2f03aece` | 70825 | 999581 | 0.23237516833229716 |
| p02 | 303 | `semifinal-paired-b-completion-p02-es-s303` | 204/204 | `5f68b76c738956d271dc194022591a1a157a552416d9fde997a6f3273f72e239` | 70788 | 999102 | 0.23229511875494777 |
| p02 | 404 | `semifinal-paired-b-completion-p02-es-s404` | 268/268 | `9666760505ce32f0aa3ce7138f449931895ece5ac252bd089d5a9c2e47131733` | 70824 | 999816 | 0.23219805776354677 |
| p02 | 505 | `semifinal-paired-b-completion-p02-es-s505` | 293/293 | `0216ff4394e6ec4f42e26189aa50b86985c681cde410b4b4b499276a289995fc` | 70833 | 999921 | 0.23223486715570588 |

The implementation additionally freezes and verifies each row's raw LF line
SHA-256, state-A geometry SHA-256, and canonical state-A curve SHA-256. A
different reconstructed cohort is a terminal failure, not a reason to edit this
table.

## 4. Single intervention and fixed doses

For every frozen source unit:

```text
dose_ppm in {0, 50000, 100000}
effective_A_span_ratio_ppm = source_A_span_ratio_ppm + dose_ppm
```

The intervention is additive. It is not multiplication, clamping, resampling,
optimization, or a change to `box_size_um`. The positive doses increase the
centerline equation's intermediate `span` by 1 mm and 2 mm respectively. For
these turn-3, zero-terminal-ratio geometries, actual full centerline width rises
by 1.5 mm and 3 mm respectively.

Only `effective_A_span_ratio_ppm` may change. The following remain frozen:

- `HardwareSpec`, including `box_size_um=40000`, turn count, feed-gap ratio,
  terminal ratio, and 50 um wire radius;
- the absolute feed gap derived from the original 40 mm equation;
- state-A total wire length;
- the complete state-B control, geometry, curve, and source loss;
- topology, vertex walk, 21-point integer interpolation, collision and
  manufacturability checks;
- the 101-point state-A frequency table, edge guard, and `S11 <= -6 dB`
  validity rule;
- NEC2 lambda/20, no far field request, `YAF_NO_FALLBACK=1`, and real
  `solver_mode=subprocess`.

Production `StateControl`, `paired_meander.py`, and the original
`span_ratio_ppm <= 1_000_000` constraint are not modified. A diagnostic-only
builder accepts state-A span through 1,100,000 ppm while retaining every physical
40 mm geometry and trajectory check.

## 5. Solver-free geometry release gate

Before numerical execution, all `10 x 3 x 21 = 630` diagnostic geometries must
be generated with the original binary64 equations and integer interpolation.
Every geometry must be connected, non-self-intersecting, inside the original
40 mm box, have positive height, pitch at least 1.5 mm, every segment and
nonadjacent clearance at least 0.2 mm, and reconstruct its requested length to
1e-9 m.

The preregistration-time audit found zero failures. Across the three dose levels,
the A-end full-width ranges are 29.945750--30.486440 mm,
31.445750--31.986440 mm, and 32.945750--33.486440 mm. The complete trajectory
minimum pitch is 3.612745 mm and minimum clearance is 0.203343 mm. The latter is
only 0.003343 mm above the frozen limit; runtime must recompute it and fail closed
on any discrepancy.

Failure of this gate ends v1 before the solver is constructed. There is no
dose substitution or r2 retry.

## 6. Numerical order and 32-call ceiling

Run ID: `semifinal-a-span-support-causal-probe-v1`.

The order and call budget are fixed:

1. replay frozen B once for p01 and once for p02; each canonical curve SHA-256
   must match `399b85ea2b8d63faa60743e8534450949bbc9846908c8cdbe995a81794c42181`
   and `f4be9ba23a08b745a1e5f48a0a7bf075eb656a43df0a625a046933886b23b949`;
2. run all ten dose-zero A controls in table order; every canonical curve
   SHA-256 must match the byte-addressed source record;
3. run all ten `+50000` A interventions in table order;
4. run all ten `+100000` A interventions in table order.

This is exactly 32 NEC2 subprocess calls. A counter different from 32 is a
terminal invariant failure. No B cache is described as a new solve, no existing
A curve is reused in place of the fresh control, and no openEMS call is allowed.

All log and summary writes are LF-only and atomic. A process interruption without
a terminal marker may resume only from the exact committed config and exact
validated prefix. A solver error, timeout, non-subprocess result, fallback,
frequency drift, source replay mismatch, output collision, or evidence-write
failure terminates v1 and forbids a numerical retry.

## 7. Metrics and interpretation

For each source unit and dose, compute the unchanged state-A metrics and:

```text
L_A(d) = 10 ** (selected_S11_A(d) / 10)
L_hybrid(d) = max(L_A(d), frozen_source_L_B)
T_ref = 0.19394054289730642
diagnostic_pair_valid = trajectory_valid and A_valid_search(d) and frozen_B_valid_search
diagnostic_reference_crossing = diagnostic_pair_valid and L_hybrid(d) <= T_ref
```

`T_ref` is the frozen old-support numerical reference line. Positive-dose
records are outside the original A-span support and therefore are never H1/H2,
never inserted into the old candidate pool, and never used for an algorithm
comparison. Every positive-dose row records:

```text
counterfactual_only = true
source_box_size_um = 40000
outside_original_span_support = true
physical_40mm_trajectory_valid = true
eligible_for_original_candidate_pool = false
eligible_for_original_h1_h2 = false
eligible_for_original_agent_comparison = false
```

For each block define high-dose improvement as `L_A(+100000) < L_A(0)` and
monotonic response as `L_A(0) >= L_A(+50000) >= L_A(+100000)`.

## 8. Mutually exclusive endpoint

Only a complete 32-call run may receive one scientific endpoint, in this order:

1. `span_support_sufficient_in_frozen_counterfactuals` if high-dose improvement
   occurs in at least 9/10 blocks, monotonic response in at least 8/10 blocks,
   and reference crossing in at least 5/10 blocks with at least 2/5 crossings
   under each parent;
2. `span_support_contributor_not_sufficient` if high-dose improvement occurs in
   at least 9/10 blocks and monotonic response in at least 8/10 blocks, but rule 1
   is not satisfied;
3. `span_support_association_not_supported` if high-dose improvement occurs in
   at most 5/10 blocks and no positive-dose reference crossing occurs;
4. `span_support_inconclusive` otherwise.

No p-value or independent-sample claim is authorized. Report all ten paired
trajectories, both parent strata, actual width, resonance, S11, reflected-power
loss, deltas, validity, and crossings. The verdict ceiling remains
`insufficient_evidence` regardless of endpoint.

## 9. Outputs, archive, and stopping rule

Outputs are:

- `runs/semifinal-a-span-support-causal-probe-v1/{log.jsonl,summary.json}`;
- `artifacts/runs/semifinal-a-span-support-causal-probe-v1/` through the existing
  archive tool with `role=other` and note
  `study=semifinal-a-span-support-causal-probe-v1 calls=32`;
- `artifacts/analysis/semifinal-a-span-support-causal-probe-v1/` containing
  `summary.json`, `report.md`, and a deterministic PNG of the ten dose-response
  traces.

The existing 254 manifest entries remain byte-identical; successful archival
adds exactly one non-overwritten entry, producing 255/255. Workspace and fresh
no-local clone verification are mandatory. Existing submission drafts remain
untracked and unchanged.

Commit sequence:

1. `Pre-register the A-span support causal probe`
2. `Implement the A-span support causal probe`
3. `Run and archive the A-span support causal probe`

After the third commit and clean-clone verification, stop. Do not revise the
semifinal package automatically. Whether this independent appendix is included
in the submission is decided only after reviewing its frozen endpoint and the
remaining submission risk.

## 10. Frozen source runtime blobs

| path | source git blob |
|---|---|
| `yaf_ai/exploration/paired_meander.py` | `98fd67154d5f6a512fdf46b99da1fc273ba8eced` |
| `yaf_ai/exploration/paired_solver.py` | `96efa9fe3e755fbca9b31315d96a330bef7291b9` |
| `yaf_ai/exploration/paired_runner.py` | `d2ece9096be6daa86de6b281bb64a8b1150c782e` |
| `yaf_ai/exploration/paired_b_completion_coordinates.py` | `a1679885fbc01b33e41de7d769dd1c9cdd3b60df` |
| `yaf_ai/exploration/paired_b_completion_gates.py` | `54fe49c9825f9e1df8147a28b2be7a128a7bfd5f` |
| `yaf_ai/analysis/paired_b_completion.py` | `19d30cd88730ed1354abbdebed9c0ea397fec406` |
| `scripts/archive_run.py` | `b532036632d9603c500313fb2a481a009da2c6e7` |

## 11. Frozen claims discipline

Allowed positive wording:

> In ten source-selected, frozen NEC2 counterfactual blocks, changing only the
> state-A span-control support produced the preregistered finite-set response.
> This is consistent with the old span-control cap contributing to the observed
> numerical gap and motivates a separately preregistered support redesign.

Allowed negative wording:

> Under the ten frozen blocks and two positive A-span doses, the preregistered
> finite-set response did not support span-cap contribution strongly enough.

Forbidden wording includes “the 40 mm box caused the failure”, “physical limit”,
“feasibility barrier solved”, “confirmed”, “new antenna”, “invention”, “YAF-M1”,
“manufacturable”, or any statement that positive-dose records improve the old
702/0 result.
