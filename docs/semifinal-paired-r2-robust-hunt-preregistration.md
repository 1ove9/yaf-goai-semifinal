# Robust Hunt R2: bounded parent-return ES gate reproduction

本任务是 v3.4 科学冻结与提交包 bdfb9c1 之后的新研究附录。
它不回改 a19684b / 4a8222e / bdfb9c1 的任何数字、三类候选或 verdict。

## Scientific scope

R2 is a bounded parent-return ES gate-reproduction study. It asks whether the
unchanged ideal telescopic meander, global seven-dimensional box, NEC2 score,
and 10% reflected-power gate can reproduce a gate crossing across five seeds
when every restart returns to the same archived NEC2-valid parent. R2 changes
only that restart destination.

This is not an exhaustive topology search and no endpoint proves a physical
matching ceiling. openEMS remains unreleased and the verdict ceiling remains
`insufficient_evidence`. A positive endpoint is at most an "NEC2-only,
cross-seed reproducible gate-crossing signal" and its selected design remains
a computational hypothesis. R2 cannot produce `CONFIRMED`, `YAF-M1`, an
invention claim, a manufacturable-antenna claim, or a robust physical claim.

## Frozen parent and effect gate

The parent is frozen without recomputation:

- source run: `semifinal-paired-es-warm-s101`
- source step / proposal index: `213` / `658`
- source commit: `a19684b5449774db82b21907cc11c7874287f838`
- source log SHA-256:
  `af5b158d487577d7a07f26186ff66222b34abe05e36bd58596849dc4e3ff6c65`
- source summary SHA-256:
  `52cd3ad16c3db5b2f3d98ab2bf394e69d4f6af0381d595d88edd3de3f98e25b7`
- source config hash:
  `7ed5e6758e8ffd554fa2bcd9e323611f46e0e099a5b2fdd9c74f6ec4401e9cde`
- candidate-freeze commit:
  `4a8222eb7528a24acaa5879e7afa2398f0413740`
- candidate document SHA-256:
  `0e814e2cc85ae0fe361c91a4d7338ae2175369b494eb49cdef8bd165338695d5`
- pair hash:
  `8a4ad18c710ec185728fd5bff0e6f16461aea29362024893e1bb6ddd3dcc73ca`
- hardware hash:
  `b6f72349504b6994a10ff9d32ffb7059424073fb25bc2900860f7e1348b9340c`
- state-A geometry hash:
  `4d8c585c7e4112d1d8aad9d8c33b55642549008cec6649075a75ffa4a4b15b55`
- state-B geometry hash:
  `84566f8b6ab538d6ff1ae730b2ecd74f445fc127f877f8edb1a53530e509c33e`
- parent search/base scores: `1.0445832225323137` / `0.7945832225323137`
- parent worst reflected-power fraction: `0.20541677746768625`

The proposal is turn count `3`, feed-gap ratio `58388` ppm, terminal ratio
`87831` ppm, state-A length/span `70731` um / `998536` ppm, and state-B
length/span `26057` um / `760951` ppm. Its manual-grid indices are null.

```text
L_manual   = 0.21548949210811824
L_required = 0.9 * L_manual = 0.19394054289730642
```

The reference is read from the committed candidate document, not recomputed.
`repr(L_required)` must equal `"0.19394054289730642"` exactly.

## Configuration and immutable evidence gates

The base `PairedRunConfig`, `PairedRunSummary`, and `PairedRunState` remain
byte-for-byte unchanged. R2 uses a subclass whose `agent` field is narrowed to
`Literal["es-r2"]`; all R2 provenance enters its config hash. Inherited
`manual_baseline_commit` and every inherited `warm_parent_*` field are null.
The subclass freezes all parent values above, proposal index `658`, budget
`400`, seeds `(101, 202, 303, 404, 505)`, run IDs
`semifinal-paired-r2-es-warm-s{seed}`, `anchor_released=False`,
`openems_cross_check_authorized=False`, rejection limit `100`, proposal-attempt
limit `6000`, and full 40-character preregistration and execution commits.

The budget evidence commit is
`253090b80df23184cb8521cbbe77af1e38a9b734`, reusing
`paired_batch.BUDGET_SOURCE_COMMIT`. Before solver construction it must be an
ancestor of execution HEAD. Its committed preflight summary must equal the
workspace bytes and have SHA-256
`b0a7f612e98064a3cf415731d89a917872fbc3931ee6d1f0116d8de8aaff6138`,
config hash
`d618134588d0db607e21638fdffed4ebff3627a669d281b3dfef456bafc43f92`,
`result_status="completed"`, `raw_budget=907`, `budget=300`,
`t_pair_p95_seconds=3.7018278000032296`, `p95_method="higher"`, and
`parallel_workers=1`. R2's budget of 400 is this preregistration's constant,
not a value derived from the archived capped budget.

The source manifest at `a19684b` must have the frozen whole-file SHA already
pinned by `SOURCE_MANIFEST_SHA256`. Only the unique source-run entry is compared
with the current append-only manifest; whole current-manifest bytes are never
compared. Canonical entry SHA-256 is
`5bf1b83868ff96dfa22528b4e245513d3dd964c8fb461c22edc0bb60dea90724`.
Its config hash, two file hashes, seed `101`, 300 completed steps, and
`overwritten=False` must agree in both manifests.

The candidate document is loaded from `4a8222e`, and the parent log and summary
from `a19684b`. Blob bytes must equal the workspace bytes. The unique source
event, reconstructed proposal, hashes, score, and encoded-parent round trip
must match every frozen value above before any solver object or run directory
is created.

The execution commit must descend from `bdfb9c1`. These scientific files remain
identical to the following `bdfb9c1` blobs:

| Path | Frozen blob |
|---|---|
| `yaf_ai/exploration/paired_runner.py` | `d2ece9096be6daa86de6b281bb64a8b1150c782e` |
| `yaf_ai/exploration/paired_solver.py` | `96efa9fe3e755fbca9b31315d96a330bef7291b9` |
| `yaf_ai/exploration/paired_meander.py` | `98fd67154d5f6a512fdf46b99da1fc273ba8eced` |
| `yaf_ai/exploration/day65_batch.py` | `5944f5c2f9c892aa0a6860b2ef443f914f6baecc` |
| `scripts/day65_batch.py` | `365a9ab2ef07de82915931099edc7b9d6f821791` |
| `yaf_ai/exploration/paired_agents.py` | `0b8b8046611bca0fd2e0c0649277e5594f439f99` |

The R2 modules and script must equal their execution-commit blobs, and the code
tree under `yaf_ai`, `scripts`, `tests`, and `pyproject.toml` must be clean.

## Parent-return ES and matrix

`R2ParentReturnES` is isolated in a new module and subclasses the unchanged
`PairedRestartedES`. It inherits the frozen seven-dimensional encoding, global
box, Gaussian-reflection mutation, 1/5 sigma rule, and constants:

```text
initial sigma 0.15; minimum 0.01; maximum 0.30
adaptation block 20; success target 0.20; factor 1.5
restart stagnation 75
```

After the inherited observer reaches 75 consecutive non-improvements, the R2
observer immediately restores the frozen encoded parent and score, clears the
pending global restart, restores initial sigma and block counters, increments
`restart_count`, and returns. The next inherited draw is therefore exactly
`reflect(frozen_parent + Normal(0, 0.15, 7))`. It never evaluates the frozen
parent itself and never consumes the old global-uniform restart draw.

Each of seeds `101, 202, 303, 404, 505` runs sequentially in one process for
400 accepted paired evaluations. Geometry rejections do not consume budget.
The frozen limits remain 100 consecutive rejections and 6000 total proposal
attempts. Run ID and archive note are:

```text
semifinal-paired-r2-es-warm-s{seed}
batch=semifinal-paired-r2 agent=es-r2 seed={seed}
```

The proposer label in evaluation records remains `es`. Solver execution uses
the existing NEC2 paired solver, lambda/20 segmentation, subprocess mode,
`YAF_NO_FALLBACK=1`, and no realized-gain value. No openEMS call is authorized.

```text
min(400, 907) = 400 accepted pairs per seed
5 * 400 * 3.7018278000032296 = 7403.655600006459 seconds
7403.655600006459 < 0.70 * 43200 = 30240 seconds
```

The v3.4 nine-cell `min(300, ...)` cap applies only to that archived matrix and
is not changed retroactively.

## Resume, failures, and restart diagnostics

R2 resume uses the same proposer construction and deterministic event replay.
A replay crossing a restart must generate the same next proposal as
uninterrupted execution. At a terminal run, two independent fresh R2 proposers
replay the persisted log and must report the same `restart_count`. When the
current process actually ran the terminal evaluation, its live count is a third
check. An idempotent load of an existing terminal summary has no live-proposer
comparison.

Any solver error, non-subprocess mode, evidence mismatch, config mismatch,
replay drift, or log-write error aborts the matrix. Only an exact same-config
resume is permitted. No new run ID, seed, budget, threshold, or result-driven
retry is allowed. A not-yet-terminal run is not archived.

Per-seed appendix status is one of `completed`,
`insufficient_feasible_proposals`, `execution_failed`, or
`not_run_after_matrix_abort`. Only the first two are legal scientific
terminals. `proposal_sequence_exhausted`, `anchor_not_released`, missing
summary, and all failures are non-terminal for this study. An abort produces
an atomic LF-only diagnostic appendix with exception type and message and must
be exactly resumed; it produces no scientific endpoint and does not use the
five-seed evidence commit message.

## Gate definitions and mutually exclusive endpoints

A seed passes only if at least one accepted record simultaneously has
`valid_pair_search=true`, worst reflected-power fraction no greater than
`0.19394054289730642`, and a pair hash different from the frozen parent.

The study is `complete` only when all five seeds reach one of the two legal
terminal statuses. Otherwise it is `study_incomplete`, and `pass_count`,
`valid_pair_seed_count`, `cross_seed_gate_pass`, and `scientific_endpoint`
are all null. No positive or negative scientific conclusion may be written.

For a complete study, `valid_pair_seed_count` is diagnostic only and endpoints
depend only on the number of passing seeds:

| Pass count | Endpoint |
|---:|---|
| 4--5 | `cross_seed_gate_crossing` |
| 1--3 | `seed_local_gate_crossing` |
| 0 | `no_gate_crossing_observed_under_frozen_r2` |

The zero-pass statement is limited to: "No gate crossing was observed under
the frozen parent, global bounds, algorithm, budget, and five seeds." It is not
a topology or physics ceiling.

Per-seed and global top ordering is deterministic over accepted records:
valid first, lowest worst reflected-power fraction, hardware hash, pair hash,
seed, then step index. Each seed records a valid-pool top, or otherwise its
highest-base-score diagnostic top. R2 run IDs remain excluded from the archived
three-class candidate pool.

## Required diagnostics and appendix invariants

For each terminal seed, the appendix records accepted and valid counts, best
valid reflected-power fraction and record identity, pass flag, restart count,
the accepted/effective turn-count distribution, rejection reasons, and the
fraction of values within 1% of each frozen continuous boundary. Boundary
fractions use valid pairs when available and all accepted pairs otherwise, with
the denominator disclosed. The archived warm-101 log is analyzed with the same
method as a pre-R2 baseline, without changing any search bound.

The frozen Pydantic appendix model requires exactly the five unique seeds and
matching run IDs. `complete` is equivalent to all five being `completed` or
`insufficient_feasible_proposals`. For complete studies the model recomputes
`pass_count`, `valid_pair_seed_count`, and `cross_seed_gate_pass` from the
five seed rows and requires the endpoint mapped from that pass count.
`study_incomplete` is equivalent to at least one non-terminal status; all
aggregate scientific fields are null. Invalid combinations, duplicate or
missing seeds, and unknown endpoints are rejected. JSON is written atomically
with LF-only bytes.

## Frozen stop and reporting rules

After five legal terminals, or immediately after an abort record is written,
R2 stops. It does not start SE1, openEMS, another seed, a larger budget, a local
48-point box, or any other candidate. It does not modify the `bdfb9c1`
submission package, old runs, old manifest entries, or frozen candidate files.

Successful completion produces only
`artifacts/analysis/semifinal-paired-r2-robust-hunt/{appendix.json,report.md}`
plus five archived runs and append-only manifest entries. Worktree and fresh
clone manifest verification are both required. Local settings and initial-round
GOAI documents remain uncommitted.
