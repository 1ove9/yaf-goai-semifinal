# Feasibility-Preserving Stratified-Turn Study v1

Status: `PREREGISTERED_WHEN_COMMITTED`

Study ID: `semifinal-paired-feasibility-stratified-turn-v1`

Numeric execution is prohibited until the preregistration commit and the
separate implementation commit both exist and every pre-execution gate below
passes.

## 1. Scope and non-retroactivity

This is an independent post-frozen-package follow-up study intended for the
current semifinal evidence appendix. It is motivated by, but is not a retry or
reclassification of, Robust Hunt R2. The archived R2 endpoint remains:

```text
study_status = complete
scientific_endpoint = no_gate_crossing_observed_under_frozen_r2
pass_count = 0/5
valid_pair_seed_count = 4/5
```

R2 evaluated 2,000 accepted paired geometries and logged 6,313 geometry-only
rejections. A post-hoc read-only diagnosis of the committed rows attributes
4,001 rejections to a first arm segment below 0.2 mm and 2,312 to a positive
terminal segment below 0.2 mm. Accepted turn counts were 1,928 / 71 / 1 / 0
for turns 3 / 4 / 5 / 6. These observations motivate a prospective
representation hypothesis; they are not themselves a new endpoint and do not
show that turns 5 or 6 are physically infeasible.

This study changes only the proposal measure and the allocation of accepted
evaluations across the already-frozen turn strata. It does not change the
physical integer domain, centerline equations, trajectory audit, NEC2
instrument, frequency grids, score, validity gate, effect threshold, or any
archived byte. It uses only new modules, run IDs, config hashes, and analysis
directories.

## 2. Immutable provenance

The motivating evidence is pinned to:

- source/evidence commit:
  `66a4325d9bc07ca97a8ec4e6ddf86b2854663a45`;
- source manifest: 224 unique entries, raw SHA-256
  `f747e908ffadbdb7eb3a6eb8ed4809dc21ffcaec63bb97a533f526c5a6913674`;
- R2 appendix SHA-256:
  `42ff2d13b5dbb09680a47dd90dfcca83a093811a1a1db950c24557c1a7f4156d`;
- R2 report SHA-256:
  `d9abefb0dd4c0e5e709552bd22a36d0bf8f15daf7093e33a38dccbe4ad85bdc0`;
- R2 endpoint: `no_gate_crossing_observed_under_frozen_r2`;
- manual reflected-power reference:
  `L_manual = 0.21548949210811824`;
- unchanged crossing threshold:
  `L_required = 0.19394054289730642`.

The budget source remains commit
`253090b80df23184cb8521cbbe77af1e38a9b734`, summary SHA-256
`b0a7f612e98064a3cf415731d89a917872fbc3931ee6d1f0116d8de8aaff6138`,
config hash
`d618134588d0db607e21638fdffed4ebff3627a669d281b3dfef456bafc43f92`,
`t_pair_p95_seconds=3.7018278000032296`, `p95_method="higher"`, and
`parallel_workers=1`.

Before a solver object is constructed, the execution entry point must prove
that the source, budget, preregistration, Stage-A-evidence, and implementation
commits required for that stage are ancestors of execution HEAD; validate the
pinned blobs from Git rather than trusting workspace values; require the
current manifest to be an append-only successor of the pinned 224 entries; and
require the committed R2 appendix, report, five manifest entries, logs, and
summaries to remain byte-identical.

The following scientific files must equal their source-commit blobs at the
source commit, execution commit, and workspace:

| Path | Frozen blob |
|---|---|
| `yaf_ai/exploration/paired_runner.py` | `d2ece9096be6daa86de6b281bb64a8b1150c782e` |
| `yaf_ai/exploration/paired_solver.py` | `96efa9fe3e755fbca9b31315d96a330bef7291b9` |
| `yaf_ai/exploration/paired_meander.py` | `98fd67154d5f6a512fdf46b99da1fc273ba8eced` |
| `yaf_ai/exploration/paired_agents.py` | `0b8b8046611bca0fd2e0c0649277e5594f439f99` |
| `yaf_ai/exploration/day65_batch.py` | `5944f5c2f9c892aa0a6860b2ef443f914f6baecc` |

New code must live in isolated feasibility/stratified modules. No frozen R2 or
v3.4 implementation file may be edited.

## 3. Frozen physical and scoring object

The object remains `ideal-symmetric-telescopic-PEC-meander-v1`:

- `turn_count in {3,4,5,6}`;
- feed-gap ratio `[0.02,0.06]`;
- terminal ratio `[0.0,1.0]`;
- state-A length `[50000,100000]` um;
- state-B length `[22000,45000]` um;
- both span ratios `[760000,1000000]` ppm;
- box `40000` um; wire radius `50` um;
- the frozen section-4.3 centerline equations and vertex walk;
- integer-um/ppm half-up quantization and existing canonical hashes;
- the existing 21-point integer-interpolated actuator trajectory audit;
- all height, pitch, segment, box, connection, collision, clearance,
  feed-edge, and reconstruction checks;
- state A: 2.400--2.500 GHz, 101 equal bins;
- state B: 5.725--5.875 GHz, 101 equal bins;
- real NEC2 subprocess mode, lambda/20 segmentation, no fallback and no
  realized-gain value;
- `valid_search = (3 <= argmin_index <= 97) and (S11 <= -6 dB)`;
- `L = max(10^(S11_A/10), 10^(S11_B/10))`;
- `anchor_released=False` and
  `openems_cross_check_authorized=False`.

No openEMS value, wide sweep, realized gain, archived candidate score, or R2
result may enter proposal generation or fitness.

## 4. Prospective representation hypothesis

The representation question is:

> With the physical support and audit held fixed, does a conditional integer
> coordinate map remove avoidable short-segment rejection and provide balanced
> access to all four turn strata?

The search question is:

> Under equal accepted-evaluation quotas, does a cold restarted ES outperform
> stratified Random in finding NEC2-valid paired-state designs, and does either
> produce a gate crossing reproducible across seeds within a fixed turn?

Neither question is a proof of a topology or physical ceiling.

## 5. Conditional integer coordinate map

Each turn is fixed externally. The six normalized coordinates preserve the
original physical-field order:

```text
z_gap, z_terminal, z_a_length, z_a_span, z_b_length, z_b_span
```

All feasibility arithmetic uses exact `Fraction` values in micrometres. Let:

```text
n = fixed turn
G = 40000 * feed_gap_ppm / 1000000
S_i = 20000 * span_i_ppm / 1000000
P_i = (S_i - G/2) / (n + 1)
T = terminal_ratio_ppm / 1000000
H_i = (((L_i - G)/2) - (n + T)*P_i) / (n - 0.5)
```

For trajectory index `i=0..20`, integer length and span use the existing rule:

```text
interpolate(start,end,i) = ((20-i)*start + i*end + 10) // 20
```

The scalar legality conditions at all 21 points are:

```text
P_i >= 1500 um
400 um <= H_i <= 40000 um
terminal_ratio_ppm == 0 or T*P_i >= 200 um
```

Feed gap and both spans use the existing inclusive half-up maps. Terminal uses
a prospectively frozen zero-inflated map with exact cutoff `1/16`:

```text
z_terminal < 1/16  -> terminal_ratio_ppm = 0
z_terminal >= 1/16 -> rescale to [0,1] and half-up map over
                       [ceil(200*1000000/min(P_i)), 1000000]
```

The minimum is over all 21 interpolated pitches. The zero branch represents
the distinct omitted-terminal topology; the positive branch covers every
integer terminal ratio that can satisfy the frozen 0.2 mm segment rule.

After `n`, gap, spans, and terminal are fixed, the decoder finds length bounds
with exact monotone integer bisection:

1. With `L_A=100000`, find the smallest `L_B` in `[22000,45000]` for which all
   21 scalar conditions hold; map `z_b_length` inclusively to
   `[L_B_min,45000]`.
2. With the decoded `L_B`, find the smallest `L_A` in `[50000,100000]` for
   which all 21 scalar conditions hold; map `z_a_length` inclusively to
   `[L_A_min,100000]`.
3. Construct the ordinary `PairedProposal` and call the unchanged
   `audit_trajectory`.

The height upper bound is inactive over the frozen global length box, so the
scalar legal set is monotone upward in each length. The construction therefore
retains every legal integer length tuple for fixed turn/gap/spans/terminal; it
changes sampling density, not the physical integer support.

Any empty conditional interval or final audit failure is a
`FeasibleCoordinateInvariantError`. It aborts before solver construction or a
run endpoint; it is not an ordinary geometry rejection that may be skipped.

The canonical encoder must invert this same dependency order. Terminal zero
encodes to `1/32`; a positive terminal encodes through the positive branch.
For every accepted archived proposal and all boundary witnesses,
`decode(encode(proposal)) == proposal` byte-for-byte.

## 6. Support-equivalence release gate

Stage A and Stage B remain blocked until all of the following pass:

1. an algebraic derivation and tests establish conditional-map outputs are a
   subset of the old legal integer support and every old legal integer tuple
   has a canonical preimage;
2. every accepted proposal in the five archived R2 logs and the frozen warm
   source round-trips byte-for-byte through the new encoder/decoder;
3. each turn passes terminal-zero, minimum-positive-terminal, maximum-terminal,
   lower-length, upper-length, and interior boundary witnesses, with explicit
   turn-6/state-B narrow-domain coverage;
4. property samples pass all 21 exact scalar checks and the unchanged
   trajectory audit;
5. decoder source has no solver, S11, score, frequency, candidate-ranking, or
   archived-metric dependency;
6. mapping failures occur before any solver object or run directory exists;
7. frozen file blobs and old archive hashes remain unchanged.

Failure yields `mapping_support_equivalence_not_established`; no numerical run
under this study ID is authorized. A restricted replacement space requires a
new study ID and preregistration.

## 7. Stage A: solver-free representation ablation

Stage A uses no NEC2 or openEMS object and produces no antenna score:

```text
representations = (legacy-fixed-turn-v1, conditional-feasible-turn-v1)
turns           = (3,4,5,6)
seeds           = (101,202,303,404,505)
cells           = 20 paired-representation cells, ordered turn then seed
raw_draws       = 10000 shared vectors per cell
```

Each cell identity is exactly `(turn,seed)`. It generates 10,000 raw vectors
and applies both representations to every same-position vector, producing one
raw digest, two status digests, and exactly 10,000 statuses per representation.
The Stage-A summary has exactly 20 unique rows in turn-major, seed-ascending
order. A cell failure stops later Stage-A cells; an exact same-config resume is
the only continuation.

For each turn and seed, one `PCG64` stream generated from
`SeedSequence([seed,0,turn,1])` supplies the same ordered six-coordinate vectors
to both representations. Python `hash()` is forbidden. The output records raw
stream SHA-256, status-stream SHA-256, counts and fixed boundary witnesses; it
need not duplicate 400,000 raw vectors because the seed, algorithm and digests
make the stream exactly reproducible.

`legacy-fixed-turn-v1` sets `turn_count` to the cell's turn, then applies the
old independent `_half_up_map` to the six raw coordinates in this exact order:

```text
feed_gap_ppm       over [20000,60000]
terminal_ratio_ppm over [0,1000000]
state_A_length_um  over [50000,100000]
state_A_span_ppm   over [760000,1000000]
state_B_length_um  over [22000,45000]
state_B_span_ppm   over [760000,1000000]
```

It performs no conditional terminal bound or length bisection; the ordinary
proposal and unchanged trajectory audit alone decide feasibility.

Stage-A stream format is frozen as `canonical-json-float-hex-lf-v1`. For each
draw the raw stream concatenates one UTF-8, LF-terminated canonical JSON object
with sorted keys, separators `(',', ':')`, `ensure_ascii=True`, and schema:

```json
{"draw_index":0,"z":["0x1.0000000000000p-1","...five more float.hex strings..."]}
```

The status stream uses the same byte rules and schema:

```json
{"draw_index":0,"rejection_reason":null,"representation":"legacy-fixed-turn-v1","status":"valid"}
```

Allowed status values are exactly `valid` and `trajectory_infeasible`; a valid
row has null rejection reason and an infeasible row has the unchanged audit
reason string. The matching legacy and conditional cells have one identical
raw-stream digest and separate status-stream digests. Decoder/invariant errors
abort the cell and do not receive another status label.

The conditional representation must have zero decoder errors and 100% audit
validity. Otherwise the mapping invariant failed and Stage B is blocked.

For turn `t` and seed `s`:

```text
coverage_pass(t,s) =
    conditional_feasible_rate == 1.0
    and conditional_feasible_rate - legacy_feasible_rate >= 0.20
```

At least four of five seeds makes a turn reproducibly improved. The mutually
exclusive representation endpoints are:

| Reproducibly improved turns | Endpoint |
|---:|---|
| 4 | `coverage_improved_all_turns` |
| 1--3 | `coverage_improved_some_turns` |
| 0 | `coverage_improvement_not_observed` |

Stage A never selects a turn or changes Stage B. Once support equivalence and
the mapping invariant pass, Stage B runs in full regardless of this endpoint.
Stage A is written, verified, committed as version-controlled analysis
evidence, and checked out from that commit before the first Stage B run. It is
not a run-manifest entry because it invokes no solver.

## 8. Stage B: balanced search matrix

The two arms share the conditional map and accepted-quota scheduler:

```text
agents             = (random-stratified-v1, es-stratified-v1)
seeds              = (101,202,303,404,505)
turn_order         = (3,4,5,6)
quota_per_turn     = 150 accepted pairs per run
evaluation_budget  = 600 accepted pairs per run
matrix_order       = Random seeds ascending, then ES seeds ascending
max_consecutive_rejections  = 100
max_total_proposal_attempts = 9000
parallel_workers            = 1
```

The scheduler chooses `turn_order[evaluations_completed % 4]`. A geometry
rejection would remain in the same stratum and consume no accepted quota, but
the conditional-map invariant requires such a rejection to abort instead of
being silently sampled around. Every completed run must contain exactly 150
accepted evaluations for each turn.

Run IDs are:

```text
semifinal-paired-stratified-random-v1-s{seed}
semifinal-paired-stratified-es-v1-s{seed}
```

Each run owns four independent `PCG64` generators, derived only from
`SeedSequence([seed,agent_code,turn,1])`, where agent codes are frozen as
Random `1` and ES `2`. Each ES island is cold, has an independent parent and
state, never mutates across turns, and inherits the existing constants:

```text
initial sigma 0.15; minimum 0.01; maximum 0.30
adaptation block 20; success target 0.20; factor 1.5
restart stagnation 75
```

The first proposal and every restart are uniform conditional-coordinate draws
within the same turn. There is no warm parent or cross-turn parent. Random is
non-adaptive under the same map and scheduler.

The complete matrix is 10 runs, 6,000 accepted paired evaluations and 12,000
NEC2 subprocess curves. The frozen P95 upper bound is:

```text
6000 * 3.7018278000032296 = 22210.966800019378 seconds < 12 hours
```

No result can stop later cells, change quota, add a seed, or redirect budget
between turns.

## 9. Config, replay and failure contract

Each config hash includes study/version, agent, agent code, seed, run ID, turn order,
quota, budget, scheduler/RNG/mapping versions, zero-branch cutoff, cold-parent
mode, Stage-A stream-format version, attempt limits, source/R2/budget
provenance, full 40-character
preregistration/Stage-A/implementation/execution commits, and frozen science
blob identities. All inherited manual/warm-parent fields are `None`.

Four island RNG states, ES parent vectors/scores, sigma/block/stagnation/restart
state, and scheduler state are reconstructed only by deterministic log replay;
no opaque RNG pickle is persisted. A run starts by validating the old state
identity, rebuilding state from the contiguous log, replaying two fresh
proposers, atomically reconciling `state.json`, and only then continuing. A log
one row ahead of state must resume without duplication. A terminal load replays
twice and calls no solver. Live and replayed per-island state must agree.

Any solver error, fallback/non-subprocess curve, config/evidence mismatch,
mapping invariant failure, replay drift, corrupt log, or evidence-write failure
aborts the ordered matrix. Only exact same-config resume is allowed. A matrix
error records agent, seed, whether the cell started, and the exact prefix of
confirmed prior cells. Stale later run directories are never promoted.

## 10. Frozen pass, selection and endpoints

An accepted record passes only when:

```text
valid_pair_search is true
and L <= 0.19394054289730642
```

Within a cell, a valid-record top uses the exact key
`(L ascending, hardware_hash ascending, pair_hash ascending, step_index
ascending, proposal_index ascending)`. If the cell has no valid record, its
diagnostic top uses `(-base_score, hardware_hash, pair_hash, step_index,
proposal_index)`, all fields after `-base_score` ascending. Duplicate hashes
remain in the log but count once in unique-candidate diagnostics.

For each agent and turn, count seeds with at least one passing record. The ES
arm is the primary scientific arm; Random is the mandatory equal-budget
comparator and cannot replace the primary candidate after results are seen.

Primary endpoints are mutually exclusive:

| ES result | Endpoint |
|---|---|
| any turn passes in 4--5 seeds | `turn_stratified_cross_seed_gate_crossing` |
| none reaches 4, but any turn passes in 1--3 seeds | `turn_stratified_seed_local_gate_crossing` |
| every turn passes in 0 seeds | `no_gate_crossing_observed_under_frozen_stratified_study` |

If one or more turns reach the cross-seed endpoint, the reporting-hypothesis
pool contains only passing ES records from ES turns with pass count at least
four. Its exact key is `(L, hardware_hash, pair_hash, turn, seed, step_index,
proposal_index)`, all ascending. If the endpoint is seed-local, the diagnostic
pool is all passing ES records and uses the same key. If no ES record passes
but at least one is valid, the diagnostic pool is all valid ES records and uses
the same key. If no ES record is valid, the diagnostic pool is all accepted ES
records and uses `(-base_score, hardware_hash, pair_hash, turn, seed,
step_index, proposal_index)`, all fields after `-base_score` ascending. Random
crossings are reported as comparator signals only.

Each of the 20 paired-representation Stage-A cells has exactly one legal
terminal: `completed` after exactly 10,000 shared draws, 10,000 legacy statuses,
10,000 conditional statuses, one raw digest and two status digests. Stage B has
exactly one legal cell terminal: `completed` after exactly
600 accepted evaluations, 150 per turn, 1,200 subprocess curves, and zero
mapping-invariant failures. `insufficient_feasible_proposals`, execution
failure, config/evidence mismatch, replay drift, corrupt or missing summary,
and every partial cell are non-terminal for this study. The study is complete
only when Stage A has a legal endpoint and all ten Stage-B cells have the sole
legal terminal. Otherwise all aggregate scientific fields and the selected
hypothesis are null. Results are descriptive; no significance claim is allowed
for five seeds.

## 11. Claim ceiling and stop rule

This study authorizes no openEMS call. The high-frequency independent-solver
anchor remains unreleased. The verdict ceiling is always
`insufficient_evidence`.

Even a cross-seed positive endpoint may be stated only as:

> Under the preregistered feasibility-preserving representation, balanced turn
> quotas, budget and five seeds, an NEC2-only gate-crossing signal reproduced
> across seeds. The selected geometry is an unconfirmed computational antenna
> hypothesis pending an independently released solver instrument.

It cannot produce `CONFIRMED`, `YAF-M1`, a manufacturable-antenna claim, an
invention claim, a continuous-motion proof, or a physical ceiling. After the
complete Stage B evidence commit, this study stops. Any future independent
solver work requires a new preregistration and cannot alter this selection.

## 12. Required outputs and commit sequence

Stage A writes machine-readable summary plus report under
`artifacts/analysis/semifinal-feasibility-stratified-stage-a/`. Stage B writes
full per-cell/per-turn diagnostics, source hashes and report under
`artifacts/analysis/semifinal-feasibility-stratified-stage-b/`; every run is
archived append-only with its agent, seed, turn quotas, study ID and
`openems=false` in the note.

Required prospective commits are:

1. `Pre-register feasibility-preserving stratified-turn study` -- this exact
   commit must contain this document and its single matching `DECISIONS.md`
   row, and its full hash enters every Stage-A and Stage-B config
2. `Implement feasibility-preserving stratified-turn gates`
3. `Run solver-free feasibility representation ablation`
4. `Run and archive balanced turn-stratified NEC2 search`

Before commits 3 and 4, pytest, Ruff, strict mypy and archive verification must
pass. Each evidence commit also requires a fresh no-local clone, checkout of
that commit, full archive verification, and clean tracked status. No amend,
rebase, old-evidence rewrite, local setting, or initial-round GOAI document is
allowed.

The preregistration commit must precede all Stage A output; the implementation
commit must precede all Stage A output; the Stage A evidence commit must
precede every Stage B run. No solver is authorized before commit 2 and all
support-equivalence tests are green.

Allowed wording reports representation coverage, balanced per-turn NEC2
signals, bounded negative results, and the named limits. Prohibited wording
includes physical impossibility from zero crossings, omission of losing cells,
or any confirmed/invention claim before independent-solver release.
