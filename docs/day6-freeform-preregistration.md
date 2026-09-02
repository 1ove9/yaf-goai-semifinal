# Day 6 free-form 3D wire dual-band preregistration

Status: frozen before every Day 6 numerical solver run.

## Scientific question

Can a single-feed, free-form three-dimensional wire inside a 40 x 40 x 40 mm
box beat a fairly optimized off-center-fed dipole (OCFD) on simultaneous
2.40--2.50 GHz and 5.725--5.875 GHz matching, and can the result be reproduced
by converged native NEC2 and openEMS instruments?

The answer may be positive or negative. A free-form loss to the optimized OCFD
is a valid result and does not authorize a change to the score, candidate set,
reference grid, or cross-check thresholds.

## Frozen geometry family

`freeform-wire-3d-v1` is one continuous centerline with one central feed. One
arm starts at the positive side of a fixed 0.6 mm x-directed feed gap and visits
N free control nodes. The other arm is its central inversion through the feed
midpoint. Thus the model is a symmetric dipole with 3N continuous coordinates;
independent asymmetric arms are excluded from v1. Coordinates are bounded by
the closed cube [-20, 20] mm on every axis. The wire radius is the unchanged Day
5 value, 0.05 mm.

The numerical choice N in {5, 6, 7} is not selected from an optimization
result. It is selected by this frozen preflight:

1. Construct three deterministic valid probe centerlines for each N, from
   random seeds 6101, 6102, and 6103, with identical rejection rules.
2. Run each probe once in real NEC2 on the frozen 1.5--6.5 GHz / 251-point
   sweep at lambda/160 segmentation.
3. A value of N is instrument-valid only if all three probes finish in
   subprocess mode, produce 251 finite S11 samples, and take no more than 10
   seconds each. Select the largest instrument-valid N. If none is valid, stop
   Day 6. The measured table and selected N must be committed before the OCFD
   scan or exploration batch starts.

Every proposed control polyline is validated before numerical subdivision.
The feed gap is an explicit port and is exempt from radiating-segment length
checks. Every radiating control segment must be at least
`max(3 mm, 4 * wire_radius) = 3 mm`; every pair of non-adjacent radiating
segments must remain at least `4 * wire_radius = 0.2 mm` apart; all nodes must
remain in the cube. Longer segments are divided into collinear numerical edges
no longer than `lambda(6.5 GHz)/10 = 4.6121917 mm`. Subdivision does not change
the physical centerline. An invalid proposal is logged as `rejected` and does
not consume the evaluation budget.

NEC2 receives the subdivided centerline as native GW wires. openEMS must receive
the same ordered points as a native CSXCAD Curve/thin-wire primitive; the legacy
axis-aligned thin-box meander path and the generic diagonal bounding-box path
are prohibited for Day 6. A fixture test must prove point-for-point XML
serialization before any openEMS Day 6 run.

## Frozen references

The primary human reference is a body-diagonal OCFD, which uses the 3D box
fairly rather than limiting a straight reference to one 40 mm side. The scan is
the Cartesian product of exactly 20 equally spaced total lengths from 45.0 to
69.0 mm inclusive and exactly 20 equally spaced non-negative feed offsets from
0.0 to 0.35 of total length inclusive. Mirror-equivalent negative offsets are
not duplicated. A fixed 0.6 mm feed gap is centered at the offset location.
All 400 cells use real NEC2, lambda/160 segmentation, and the same 251-point
sweep and score as exploration. The maximum score is the OCFD reference; ties
are resolved by lower length and then lower offset.

The secondary reference is a center-fed straight dipole of total length
`c/(2*2.45 GHz) = 61.182134 mm`, placed on the same body diagonal. It receives
one evaluation under identical settings. It is a single-frequency control, not
the classic comparator used by the 10% discovery gate.

## Frozen dual-band score and preflight gate

For each target band independently, find the most negative sampled S11 and
convert it to accepted-power fraction

`FoM_band = 1 - |Gamma_min|^2 = 1 - 10^(S11_min_dB/10)`.

The score is `min(FoM_2.4, FoM_5.8)`. It lies in [0, 1], gives neither band a
weight advantage, and cannot be raised by excellent matching in only one band.
It is the matching component of the Day 4.5 realized-gain correction; no raw
NEC2 accepted-power gain or lossless efficiency enters this dual-band score,
because the current solver result does not contain frequency-resolved gain.
Band minima, their frequencies and indices, S11 depths, mismatch efficiencies,
and the aggregate are all logged.

Before the exploration batch, the archived reference scan must show both
`OCFD_score > straight_score` and a strictly better OCFD worst-band S11 depth.
Failure stops the batch and is reported as `invalid_scoring_preflight`; it does
not authorize score revision under this batch ID. The exact numbers are appended
to this document and committed before the batch starts.

## Frozen exploration matrix and optimizer policy

The matrix is agents {GP, Random} x seeds {101, 202, 303, 404, 505}. Both agents
read the same selected 3N-dimensional `ProposalSpace`. A real-NEC2 preflight
evaluation and a 300-observation GP suggestion benchmark determine the budget.
Try budget 300, then 250, then 200; select the first whose conservative estimate
for all ten cells is at most 10,800 seconds. The estimate uses the measured
solver time plus the measured GP suggestion time per evaluation. If a GP
suggestion with 300 stored observations exceeds 5 seconds, GP is frozen to the
most recent 200 accepted observations; otherwise it retains all observations.
The choice, times, and reason are committed before the first batch evaluation.

All accepted evaluations must report NEC2 `solver_mode=subprocess`. No fallback
value may enter a score. Batch state and configuration include the selected N,
space version, sweep, score version, references, budget, seeds, optimizer
window, and discovery rules in their hash.

## Frozen discovery and candidate rules

Unique accepted GP records are ordered by score descending, then source run ID
ascending, then step index ascending. Geometry hash removes duplicates. Exactly
the first two are selected before any cross-check output is observed; neither
may be replaced and no third candidate may be added.

A positive discovery requires all of the following:

- the best free-form score is at least 1.10 times the optimized OCFD score;
- in each target band, both solver curves contain a local minimum whose global
  wide-sweep index is outside the first and last three samples and whose depth
  is at most -6 dB;
- in each band, the NEC2/openEMS resonance-frequency difference is at most 5%;
- Pearson correlation across the complete common 1.5--6.5 GHz / 251-point
  sweep is at least 0.8.

The thresholds and resonance-validity semantics are inherited from protocol
v2.1; matching-depth difference remains descriptive only. Each candidate gets
an independent verdict. `confirmed_improvement` is permitted only when the 10%
reference gate and every listed two-solver gate pass.

## Frozen instruments and convergence

Final NEC2 uses lambda/160. openEMS mesh resolution is governed by 6.5 GHz, not
by the lower band. Before either candidate verdict, candidate rank 1 is run at
adjacent openEMS refinements 1x and 2x. The instrument is self-converged only if
the 5.8 GHz resonance moves by at most 3%. If not, 4x is run only when the 2x
runtime is at most 1800 seconds; otherwise the instrument is
`infeasible_at_current_compute`. No frequency point or sweep-width reduction is
allowed. The finest self-converged setting is then frozen for both candidates.

The same geometry, feed, sweep, and 50 ohm reference impedance are used in both
solvers. Any missing high-band resonance, non-converged instrument, solver
failure, or agreement failure is recorded under the existing five-type anomaly
taxonomy; it never triggers a result-driven retry.

## Frozen reporting

The report includes every reference cell's source, per-seed GP/Random results,
the two candidate decisions, three-view 3D geometry, wide-sweep paired curves,
best-so-far trajectories, and planarity residual. The existing Chu method is
reused descriptively at both resonances; the double-frequency addition changes
no Chu formula or confidence rule. Every number carries a source run ID. No
claim of novelty or invention is made from shape alone.

## Execution record

### Instrument-cost amendment before any reference or batch run

The initial lambda/160 dimension preflight was completed and archived before an
OCFD or batch evaluation. All nine probes were genuine subprocess results with
251 finite samples, but every one failed the initially frozen 10 second
exploration-cost gate:

| N | seed 6101 | seed 6102 | seed 6103 |
|---:|---:|---:|---:|
| 5 | 17.390 s | 63.922 s | 84.031 s |
| 6 | 19.938 s | 65.250 s | 173.735 s |
| 7 | 50.328 s | 195.859 s | 226.109 s |

Sources are the nine `day6-freeform-preflight-r2-*` runs. The original rule was
therefore applied literally: no N passed, and the script stopped before the
reference scan. These runs are retained as an aborted instrument-cost path.

This amendment corrects a scope error in the initial execution text. Protocol
v2.1 requires lambda/160 for the **final cross-check instrument**; the Day 6
request requires a real NEC2 exploration oracle but does not require every one
of roughly 3000 search evaluations to use the final instrument. The corrected,
frozen execution uses lambda/20 for the N-selection probes, the OCFD/straight
references, and every GP/Random exploration evaluation. This is the established
Day 5 pattern: a cheaper real oracle explores, then lambda/160 independently
verifies the two frozen winners. The 10 second per-probe gate, the largest-valid
N rule, the three-hour matrix gate, all geometry and score definitions, the
20x20 OCFD grid, the top-2 rule, and every discovery threshold remain unchanged.
The corrected probes use new `day6-freeform-preflight-r3-*` run IDs. Final
cross-check NEC2 remains lambda/160 without exception.

The mechanical r3 N-selection, optimizer timing, reference-sanity numbers, and
frozen batch choice will be appended and committed before the first exploration
batch evaluation.

### Frozen r3 selection and reference result

All nine r3 probes returned exactly 251 finite S11 samples in subprocess mode.
The measured lambda/20 times were N=5: 0.844/1.860/2.079 s; N=6:
0.984/1.719/3.734 s; and N=7: 1.688/3.937/4.594 s for seeds
6101/6102/6103 respectively. Every N passed 10 seconds, so the frozen rule
selects the largest, N=7. The batch space is therefore
`freeform-wire-3d-v1-n7`, with 21 continuous coordinates.

One GP suggestion after 300 stored 21-dimensional observations took 0.018513
seconds, below 5 seconds, so all observations are retained. Using the slowest
selected-N probe plus that GP cost, budget 300 and 250 exceed the 10,800 second
limit; budget 200 estimates 9225.025 seconds and is selected. The matrix remains
GP/Random x five preregistered seeds.

The 400-cell OCFD scan winner is `day6-freeform-ocfd-grid` step 152: total
length 53.842105 mm, feed-offset ratio 0.221052632, score 0.617137421,
2.4 GHz-band minimum -4.315946 dB, and 5.8 GHz-band minimum -4.169571 dB.
The straight control `day6-freeform-straight-control` scored 0.100343450 with
-12.845878/-0.459233 dB band minima. Thus OCFD has both a higher score and a
deeper worst-band minimum, so the preregistered scoring sanity gate passes.

The self-hashed batch configuration is
`f01bcf4de5b136fe096b10b9f658e28e4ab402f473c80d3eca5125ee7e4a0a89`.
These choices are frozen before the first batch evaluation.

### Final-instrument timeout execution note

After the top two source addresses were committed, candidate A's first final
NEC2 lambda/160 call reached the adapter's generic 300 second subprocess timeout.
No curve was produced and `YAF_NO_FALLBACK=1` prevented an analytical value from
entering the evidence. The failed attempt is retained under the distinct run ID
`day6-freeform-final-crosscheck-top1-timeout300`.

Before retry, the permitted process timeout is raised to 1800 seconds. Candidate
identity, geometry bytes, lambda/160 segmentation, 1.5--6.5 GHz/251-point sweep,
openEMS 2x setting, score, reference gate, and every dual-band v2.1 threshold remain
unchanged. The retry therefore changes execution capacity only and was authorized
without observing any lambda/160 numeric result.
