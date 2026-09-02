# B-parent conditional completion study

Status: preregistration only; numerical execution is blocked until this document and the matching DECISIONS entry are committed, the isolated implementation is committed, and every pre-run gate and quality check passes.

Study ID: `semifinal-paired-b-parent-conditional-completion-v1`

Run family: `semifinal-paired-b-completion-{p01|p02}-{random|es}-s{seed}`

## 1. Scientific question and scope

The exact-support balanced Stage-B study completed all 6,000 paired evaluations without a geometry rejection or fallback, but observed no pair for which both frozen narrow-band validity gates passed. It nevertheless contains exactly two evaluations whose state B independently passed its frozen 5.8 GHz search-validity gate. This prospective study asks a narrower, falsifiable question:

> With each of those two hardware identities and state-B controls frozen byte-for-byte, can a new search over state A alone complete a valid 2.45/5.8 GHz two-state pair, and can any such pair cross the already-frozen reflected-power effect threshold?

This is a conditional completion study, not a continuation of an unfinished Stage-B cell and not a third attempt at an archived candidate. It may produce a source-addressed NEC2-only computational hypothesis. It cannot produce `CONFIRMED`, `YAF-M1`, a manufacturable-antenna claim, or an invention claim because openEMS is forbidden and the final verdict ceiling is `insufficient_evidence`.

The source state-A controls and metrics are provenance only. They are not used to select parents, initialize ES, narrow bounds, define the coordinate map, rank results, or stop execution.

## 2. Immutable source evidence

The only source-evidence commit is `8fb865005791a3f1fa53d212d0f0a1e813f19558`. It must be an ancestor of the implementation execution commit. Before a solver factory is constructed, the implementation must read the following blobs from that commit, require byte equality with the workspace files, and verify these SHA-256 values:

| Evidence | SHA-256 |
|---|---|
| `artifacts/runs/manifest.json` (234 entries) | `fb5163a33753b4c8aed50c03e1244c22072be7477a69b234848a7aeaa285c9b2` |
| Stage-B `appendix.json` | `1513885a474b74cdd7ae9873d642fee698bb4c74e3f9e450c875ccd6f6a690c6` |
| Stage-B `report.md` | `5911f7eba34653954c7bcb00c8533ff4f47577651cb373754930dc96c9d01d64` |
| source ES-s404 `log.jsonl` | `f7039126f8be54ec5d601b13153c80bad067e8f63ef308e04c1d7f803dd5af34` |
| source ES-s404 `summary.json` | `ceaaa863249a438ecd2224a459b59c1c63d91364980e5b288f79b00b0dabce16` |

The source run is `semifinal-paired-stratified-v2-es-s404`, with config hash `d51ea414bbedbc7913e28966224d91e786e87a7b896f2b81b3a1340da4c2fedb`. The committed source log blob is `6c6a5bdc61172dcb422cabb5863216270584e50d`.

The gate must replay all ten Stage-B logs and all 6,000 accepted records. Parent eligibility is exactly `evaluation.metrics.state_b.valid_search is true`; no state-A field, pair score, worst-state score, or proximity measure may enter selection. The eligible set must contain exactly two records. Missing, extra, duplicated, or changed records stop before solver construction.

## 3. Frozen B-parent identities

The complete eligible set is used. Canonical order is ascending `(pair_hash, run_id, step_index, proposal_index)`, which yields P01 then P02.

### P01

- Source run: `semifinal-paired-stratified-v2-es-s404`
- Step/proposal index: `52 / 52`
- Source pair hash, provenance only: `3f197f201833d90efa3d8aea6e9bd1d18cd49e264908f9c34237639c2057dae4`
- Raw LF source-line SHA-256 / bytes: `14f152d6aa3d817426d2170bd80662b6329b8cf83604084af1308efce65c0fb6` / `10307`
- Hardware hash: `52cc0dfe93a241643f2089bbd67f4d674edede0dfd38617983d9841a530a302b`
- Frozen hardware: schema `1`; mechanism `ideal-symmetric-telescopic-PEC-meander-v1`; quantization `integer-um-ppm-v1`; turn count `3`; feed-gap ratio `49001` ppm; terminal ratio `0` ppm; maximum total wire length `100000` um; box size `40000` um; wire radius `50` um
- Frozen B control: total wire length `26090` um; span ratio `785552` ppm
- State-B geometry hash: `c9b3f991597ee1bb7082b5f2fe5ffb41f78bf0b8723bac8d6d57bb1eff9a4ee1`
- State-B selected point: index `16`; `5749000000.0` Hz; `-15.904209685014912` dB; reflected-power fraction `0.025679054646815754`; FoM `0.9743209453531843`
- Canonical state-B curve SHA-256: `399b85ea2b8d63faa60743e8534450949bbc9846908c8cdbe995a81794c42181`, where canonical bytes are UTF-8 JSON with sorted keys, separators `(',', ':')`, `ensure_ascii=True`, `allow_nan=False`, and no trailing newline
- Source A, provenance only and excluded from initialization: length `78679` um; span `879296` ppm

### P02

- Source run: `semifinal-paired-stratified-v2-es-s404`
- Step/proposal index: `136 / 136`
- Source pair hash, provenance only: `b8180493c7212ca0c8a3165e3aaa26cde542cbc153d01ddb6f009ae9204e8ad3`
- Raw LF source-line SHA-256 / bytes: `ca216c46bdcc57bc16c2092e29becd42549e7922b6076c4d300177554f12153c` / `10197`
- Hardware hash: `2c2283aa418160650b84e8849574531cb7816f8845874952b1a0ba2c4a1b65f1`
- Frozen hardware: schema `1`; mechanism `ideal-symmetric-telescopic-PEC-meander-v1`; quantization `integer-um-ppm-v1`; turn count `3`; feed-gap ratio `48021` ppm; terminal ratio `0` ppm; maximum total wire length `100000` um; box size `40000` um; wire radius `50` um
- Frozen B control: total wire length `26646` um; span ratio `770570` ppm
- State-B geometry hash: `dea79fb9a94126ec2406840ff973973c66bec9c1230badf438c3db8f781c4d7d`
- State-B selected point: index `19`; `5753500000.0` Hz; `-17.132086268706082` dB; reflected-power fraction `0.019354919667848212`; FoM `0.9806450803321518`
- Canonical state-B curve SHA-256: `f4be9ba23a08b745a1e5f48a0a7bf075eb656a43df0a625a046933886b23b949` under the same canonicalization
- Source A, provenance only and excluded from initialization: length `72618` um; span `848975` ppm

## 4. Frozen hypotheses and metrics

All geometry, scoring, frequency grids, edge guards, depth threshold, trajectory interpolation, and solver settings remain those of the source Stage-B study.

- H1, pair validity: `valid_pair_search is true`; both states must have an internal selected index in the frozen `3..97` edge guard and selected `S11 <= -6 dB`.
- H2, effect crossing: H1 is true and `worst_reflected_power_fraction <= 0.19394054289730642`.
- The H2 threshold is the existing NEC2 effect threshold `0.90 * L_manual`; it is not recalculated from these parents.
- ES observes the unchanged `search_score`, including the existing validity bonus. Reporting separates H1 from H2 and never treats search score alone as an effect pass.

No metric from openEMS, a wide sweep, a new manual reference, or a source A state is allowed.

## 5. Exact A-only coordinate support

Mapping version: `b-parent-a-only-exact-support-v1`.

Each raw vector has exactly two binary64 coordinates in this fixed order: `(state_a_span_ratio_ppm_raw, state_a_total_wire_length_um_raw)`, each in inclusive `[0.0,1.0]`.

For inclusive integer bounds `(lo,hi)`, half-up mapping is `q(x;lo,hi)=min(hi,max(lo,floor(lo+x*(hi-lo)+0.5)))`. The canonical inverse of integer `v` is binary64 conversion of exact Fraction `(v-lo)/(hi-lo)`; for a singleton interval it is `0.5`. Decoding the inverse must reproduce `v` exactly.

For each frozen parent independently:

1. Decode A span as `q(raw[0];760000,1000000)`.
2. Hold the complete parent hardware and B control byte-for-byte fixed.
3. Exact legality uses the existing `exact_nominal_failure_reason` semantics: 21 integer-interpolated trajectory points indexed `0..20`, exact `Fraction` pitch/height arithmetic, minimum pitch `1500` um, minimum height `400` um, maximum height `40000` um, and minimum nonzero terminal segment `200` um.
4. Integer interpolation from A to B at index `i` is `((20-i)*A+i*B+10)//20`, separately for length and span.
5. Find the smallest legal A length in inclusive `[50000,100000]` by deterministic lower-bound binary search. First require `100000` legal; use `mid=(left+right)//2`, move `right=mid` when legal, otherwise `left=mid+1`. An empty interval is an invariant failure.
6. Decode A length as `q(raw[1];minimum_legal_length,100000)`.
7. Construct the proposal from exact frozen hardware, decoded A, exact frozen B, and the frozen proposer label.
8. Require both exact nominal predicate and unchanged binary64 `audit_trajectory` to pass, and require hardware/B geometry hashes to equal the frozen parent. Failure stops before solver construction; reject-and-resample is forbidden.

Before numerical execution, a solver-free exhaustive certificate evaluates every A span integer in `[760000,1000000]` for both parents, proves its length interval nonempty, and checks lower boundary, lower-minus-one when in range, upper boundary, canonical round trip, exact predicate, and binary64 audit. The decoder may not read S11, score, frequency, source-A metrics, or solver output.

## 6. Frozen matrix, budget, random streams, and B reproduction

The run family is
`semifinal-paired-b-completion-{p01|p02}-{random|es}-s{101|202|303|404|505}`.
All twenty runs execute in this fixed order: P01 before P02, Random before ES
within a parent, and seeds `101,202,303,404,505` in ascending order within an
agent. Each run is bound to one parent. There is no cross-run reallocation,
adaptive stopping, extra seed, extra run, or extra parent.

Each run has exactly `300` accepted evaluations. Every accepted evaluation
solves state A and state B as two real NEC2 subprocess curves, for `600` curves
per run and `6,000` pairs / `12,000` curves over the complete matrix.
The decoder is total on its frozen raw support, so
`max_total_proposal_attempts = 300` and `rejected_proposals = 0`. The first
rejection is an invariant failure rather than a reject-and-resample event.
The inherited field remains `max_consecutive_rejections = 100`, but the new
strict proposer wrapper raises before that generic limit can authorize a
second proposal.

The random contract is fully frozen:

- `rng_version = numpy-pcg64-seedsequence-v1`;
- one stream per run is
  `np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, agent_code, parent_code, 1])))`;
- agent codes are `random-b-completion = 3` and `es-b-completion = 4`;
- parent codes are `p01 = 1` and `p02 = 2`, assigned independently by
  ascending `(state_b_geometry_hash, hardware_hash, run_id, step_index,
  proposal_index)` over the complete eligible set; this B-only order yields
  the frozen values and is not derived from section 3's source `pair_hash`
  display order;
- `stream_format_version = canonical-json-float-hex-lf-v1`;
- the raw vector is exactly two binary64 values in the section 5 order.

Random consumes exactly one `rng.random(2, dtype=np.float64)` call per proposal
and consumes no random values in decoding, rejection handling, or observation.
ES is one cold two-dimensional island with byte-frozen constants imported from
`day65_batch.py`: initial/minimum/maximum sigma, adaptation block, success
target, sigma factor, and restart stagnation are unchanged. Its first proposal
and every pending restart consume one `rng.random(2, dtype=np.float64)` call.
Otherwise it consumes one `rng.normal(0.0, sigma, 2)` call and applies unchanged
`reflect_normalized`. The first accepted evaluation becomes the parent;
replacement uses strict `search_score > parent_search_score`; adaptation occurs
after the frozen block; and restart occurs after the frozen stagnation count.
Observation consumes no random value. Tests freeze the first draws of all
twenty streams and state-transition known answers before solver construction.

Agent identities are `random-b-completion` and `es-b-completion`. ES is cold
from its run stream. Source-A controls and metrics never initialize, rank,
bound, or stop it.

Every accepted record must reproduce the bound parent byte-for-byte:
`hardware_hash`, `state_b_geometry_hash`, and the canonical state-B curve
SHA-256 must equal the frozen values in section 3. The curve payload is exactly
`record.evaluation.state_b_curve.model_dump(mode="json")`, serialized as
UTF-8 JSON with sorted keys, separators `(',', ':')`, `ensure_ascii=True`,
`allow_nan=False`, and no trailing newline. A parent-bound strict solver
wrapper checks B geometry before NEC2 and the B curve before returning the
evaluation to the frozen runner. A mismatch raises before an accepted row is
appended, atomically writes `matrix_failure.json` with expected/actual hashes
and partial-log diagnostics, classifies the study as
`state_b_reproduction_failed`, and terminates without retry.

## 7. Frozen endpoints, selection, and interpretation

`H1` is the number of accepted matrix records for which
`valid_pair_search is true`. `H2` is the number of H1 records for which
`worst_reflected_power_fraction <= 0.19394054289730642`. The existing
`L_REQUIRED` value is used verbatim and is not re-derived from either parent.

Only after all twenty runs complete is exactly one mutually exclusive
scientific endpoint assigned:

- `b_completion_effect_crossing_observed` when `H2 >= 1`;
- `b_completion_pair_validity_without_effect_crossing` when `H1 >= 1` and
  `H2 = 0`;
- `no_b_completion_pair_observed` when `H1 = 0`.

When `H1 >= 1`, one descriptive hypothesis is selected by this complete key:
H2 members before H1-only records, then
`worst_reflected_power_fraction` ascending, `pair_hash` ascending, `run_id`
ascending, and `step_index` ascending. This is an NEC2-only descriptive
endpoint, not a release decision.

For every parent-by-agent cell, the report gives the number of five seeds with
at least one H1 record and the number with at least one H2 record, plus the
complete parent-by-agent-by-seed table. A result supported by one seed is
reported as a one-seed fact and never as stable. Random remains the comparison
baseline. The verdict ceiling is always `insufficient_evidence`; this study
cannot emit `CONFIRMED`, `YAF-M1`, manufacturability, or invention language.
Independent-solver confirmation requires a separate preregistration.

## 8. Solver-free support certificate

Before the matrix and without constructing a solver, the certificate exhausts
all `240,001` span integers in `[760000,1000000]` for each parent. For every
span it requires a non-empty length interval, finds deterministic lower bound
`lo`, proves `lo` legal and `lo-1` illegal when the latter is in bounds,
requires `hi == 100000` legal, round-trips both `lo` and `hi` through the
canonical inverse, and compares the exact predicate with binary64
`audit_trajectory` on both boundary geometries.

Lower-bound inference is allowed only after checking its frozen suffix
preconditions: pitch is independent of A length, trajectory height is affine
and non-decreasing in A length for the frozen parent, and the legal upper
endpoint passes every exact constraint. Thus no unverified interior
non-monotonicity is assumed. The certificate traverses all
`2 * 240001 = 480002` spans even when a witness fails, records each failure
class and its first witness, and only then assigns the certificate result.

Outputs are
`artifacts/analysis/semifinal-paired-b-completion-v1-certificate/report.md`
and `summary.json`; they do not enter the run manifest. The summary records
checked-span counts, failure counts, and first witnesses.
`support_certificate_failed` is a legitimate terminal result and forbids the
matrix. The matrix validates committed certificate bytes and never recomputes
the certificate.

## 9. Config, provenance, and pre-run gates

Every field below enters the immutable run config and therefore appears
unchanged under `summary.config`; the frozen top-level `PairedRunSummary`
schema is not extended:

- `study_id = semifinal-paired-b-parent-conditional-completion-v1`;
- `spec_revision = 1.0-b-parent-a-only-exact-support`;
- `mapping_version = b-parent-a-only-exact-support-v1`;
- agent, agent code, parent ID/code, and seed;
- `source_evidence_commit = 8fb865005791a3f1fa53d212d0f0a1e813f19558`;
- source manifest SHA-256
  `fb5163a33753b4c8aed50c03e1244c22072be7477a69b234848a7aeaa285c9b2`
  and entry count `234`;
- Stage-B appendix SHA-256
  `1513885a474b74cdd7ae9873d642fee698bb4c74e3f9e450c875ccd6f6a690c6`
  and report SHA-256
  `5911f7eba34653954c7bcb00c8533ff4f47577651cb373754930dc96c9d01d64`;
- source run `semifinal-paired-stratified-v2-es-s404`, log SHA-256
  `f7039126f8be54ec5d601b13153c80bad067e8f63ef308e04c1d7f803dd5af34`,
  summary SHA-256
  `ceaaa863249a438ecd2224a459b59c1c63d91364980e5b288f79b00b0dabce16`,
  and config hash
  `d51ea414bbedbc7913e28966224d91e786e87a7b896f2b81b3a1340da4c2fedb`;
- the complete bound-parent identity block from section 3, including source
  run, step/proposal, LF-line SHA/length, hardware/B hashes, and B-curve SHA;
- `preregistration_commit` and document SHA-256, `implementation_commit`,
  `certificate_evidence_commit`, and `execution_commit`, all full hashes.

Inherited batch provenance is frozen for schema conformance:
`budget_source_commit =
253090b80df23184cb8521cbbe77af1e38a9b734`,
`budget_source_summary_sha256 =
b0a7f612e98064a3cf415731d89a917872fbc3931ee6d1f0116d8de8aaff6138`,
and `budget_source_config_hash =
d618134588d0db607e21638fdffed4ebff3627a669d281b3dfef456bafc43f92`.
The committed preflight blob must be ancestor-sourced and byte-identical. Its
repository-relative path is
`artifacts/runs/semifinal-paired-budget-preflight/summary.json`. Its
parsed fields are `result_status == "completed"`, `raw_budget == 907`,
`budget == 300`, the frozen config hash,
`t_pair_p95_seconds == 3.7018278000032296` by binary64 equality,
`p95_method == "higher"`, and `parallel_workers == 1`. This study's budget is
the preregistered constant `300`, not a value re-derived at execution.

The config subclass also freezes `evaluation_budget = 300`,
`anchor_released = false`, `openems_cross_check_authorized = false`,
`max_consecutive_rejections = 100`,
`max_total_proposal_attempts = 300`, and requires
`manual_baseline_commit` plus every inherited `warm_parent_*` field to be
`None`. Commit fields match `[0-9a-f]{40}\Z`.

Commit semantics are:

1. `preregistration_commit` is commit 1;
2. `implementation_commit` is commit 2 and is HEAD while the certificate runs;
3. the certificate summary records commit 2;
4. `certificate_evidence_commit` and `execution_commit` both equal commit 3,
   which is HEAD when the matrix starts and remains HEAD during execution.

There is no Git self-reference: a later stage discovers and records an earlier
commit hash; a commit never embeds its own not-yet-existing identity.

Before certificate or solver construction, gates require:

1. all named commits are ancestors and all committed inputs equal workspace
   bytes and their frozen SHA-256 values;
2. the current manifest is byte-identical to the pinned 234-entry source
   manifest before the certificate and again at matrix start; source entries
   are unique and none is overwritten;
3. the pinned source manifest contains exactly the ten unique Stage-B run
   entries; for each, committed log and summary blobs equal workspace bytes
   and their manifest SHA-256 values, with 600 paired-evaluation rows each and
   6,000 total;
4. every logged B-valid flag equals a recomputation from only the state-B
   curve, using the frozen earliest-global-minimum, `3..97` edge guard, and
   `S11 <= -6 dB` rule; the eligible set is exactly the two LF-line-addressed
   section-3 rows. No A field is read for eligibility;
5. section 3's `pair_hash` ordering is source display provenance only. Numeric
   `parent_code` assignment is independently recomputed by the B-only key
   frozen in section 6 and must yield P01=1/P02=2; therefore source A cannot
   alter stream allocation, bounds, stopping, or a numerical result;
6. source commit, implementation/execution commit, and workspace bytes have
   these exact frozen Git blobs:

| Path | Git blob |
|---|---|
| `yaf_ai/exploration/paired_meander.py` | `98fd67154d5f6a512fdf46b99da1fc273ba8eced` |
| `yaf_ai/exploration/paired_solver.py` | `96efa9fe3e755fbca9b31315d96a330bef7291b9` |
| `yaf_ai/exploration/paired_runner.py` | `d2ece9096be6daa86de6b281bb64a8b1150c782e` |
| `yaf_ai/exploration/paired_agents.py` | `0b8b8046611bca0fd2e0c0649277e5594f439f99` |
| `yaf_ai/exploration/day65_batch.py` | `5944f5c2f9c892aa0a6860b2ef443f914f6baecc` |
| `yaf_ai/exploration/paired_feasible_coordinates.py` | `6d120cd8110a95b8d66e036b9c9ed104b247eb5f` |
| `yaf_ai/exploration/paired_feasible_agents.py` | `50d885f687285fc516456911602741622e5e5212` |
| `yaf_ai/exploration/paired_feasible_batch.py` | `c7d290326e6c80f153e25341d0c456bd2618ea96` |
| `yaf_ai/exploration/paired_feasible_gates.py` | `b6f767dc5330ffb6f0edbb3bbf8f72102e1e00a3` |
| `yaf_ai/analysis/paired_feasible_stage_b.py` | `080bdbde95917939535526423a74936e56a3dc1f` |
| `scripts/paired_feasible_batch.py` | `387306bea448ffbb1fddbe521f1275ec043d4ca9` |
| `scripts/paired_feasible_stage_b_report.py` | `cc51df39f4611ad74c92b68abf08189bf31c5d6b` |

Only new conditional-completion modules, scripts, tests, and artifacts may be
added. The tracked science/code tree must otherwise be clean.

The runtime implementation path set is frozen before implementation:

- `yaf_ai/exploration/paired_b_completion_coordinates.py`;
- `yaf_ai/exploration/paired_b_completion_agents.py`;
- `yaf_ai/exploration/paired_b_completion_gates.py`;
- `yaf_ai/exploration/paired_b_completion_batch.py`;
- `yaf_ai/analysis/paired_b_completion.py`;
- `scripts/paired_b_completion_certificate.py`;
- `scripts/paired_b_completion_batch.py`;
- `scripts/paired_b_completion_report.py`.

Commit 3 may add only certificate artifacts and may not change a runtime path.
For every path, the Git blob in `implementation_commit`,
`certificate_evidence_commit`, and `execution_commit` must equal the workspace
`git hash-object` value. The complete
`conditional_implementation_blobs: dict[path, blob_sha]` enters every run
config hash and the certificate summary. Before the matrix, the gate requires
the certificate map, commit-2 blobs, commit-3 blobs, execution-HEAD blobs, and
workspace bytes all to agree. This makes the implementation certified in
commit 2 byte-identical to the implementation that executes the matrix.

## 10. Failure and exact-resume rules

`support_certificate_failed`, `state_b_reproduction_failed`, a mapping
invariant failure, solver error/timeout, a non-subprocess curve, source
replay/config/hash drift, evidence-write failure, and log corruption are
terminal outcomes for this v1 study. They may not be retried under this
preregistration.

Exact-config resume is permitted only after an external host/process
interruption before a terminal marker that leaves the persisted prefix
internally consistent. Resume replays the proposer to that exact prefix,
verifies every config/evidence/hash invariant, and continues without changing
a config byte. It never resumes past `matrix_failure.json` and is not a
scientific retry.

For terminal matrix failure, the batch atomically records failed run ID,
accepted/rejected/attempt counts, partial-log SHA-256/bytes/lines, exception
class/message, expected/actual B hashes when applicable, and the frozen
completed-prefix list. A partial failed run is not placed in the manifest.

## 11. Outputs, commits, branch outcomes, and stop

The success branch produces this preregistration, the certificate directory,
`artifacts/analysis/semifinal-paired-b-completion-v1/{report.md,appendix.json}`,
twenty archived run directories, and an append-only manifest transition from
`234` to `254`.

The commit messages and order are frozen:

1. `Pre-register the B-parent A-only conditional completion study`
   (this document plus exactly one `DECISIONS.md` row dated 2026-08-31);
2. `Implement B-parent A-only completion gates`;
3. `Run and archive the B-parent A-only completion certificate`;
4. `Run and archive the B-parent A-only completion matrix`.

Before commits 3 and 4, all commands below must pass:

```text
ruff check .
mypy yaf_core yaf_ai yaf_solvers yaf_api yaf_db yaf_worker --strict
pytest tests/ -x -q
python scripts/archive_run.py --verify
```

Branch outcomes are frozen:

- certificate pass plus 20/20 completed runs: commit 4 has manifest `254`,
  workspace and fresh no-local clone verify `254/254`, and section 7 assigns
  the scientific endpoint;
- certificate failure: commit 3 preserves the failure certificate, manifest
  remains `234`, verify is `234/234`, no run is produced, and final analysis
  under commit-message 4 records `study_status =
  support_certificate_failed` with null scientific endpoint;
- terminal matrix failure: only the completed fixed-order prefix of `k` runs
  is archived, manifest is `234+k`, commit 4 records terminal study status and
  a null scientific endpoint.

Each evidence commit is checked out in a fresh no-local clone; its archive
verification count must equal the workspace count and tracked status must be
clean. Adds are path-specific. `.claude/settings.local.json`, `GOAI初赛-*`,
`tmp/`, and workspace `runs/` are excluded.

After commit 4 and its round-trip verification, this bounded one-time study
stops. It has no study-local r2, starts no subsequent experiment or
preregistration, and never invokes openEMS.
