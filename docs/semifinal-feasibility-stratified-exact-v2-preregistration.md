# Feasibility-Preserving Stratified-Turn Exact-Support Study v2

Status: `PREREGISTERED_WHEN_COMMITTED`

Study ID: `semifinal-paired-feasibility-stratified-exact-v2`

Spec revision: `2.0-exact-nominal-support`

Numeric execution is prohibited until this document and its matching
`DECISIONS.md` row are committed, the separate implementation commit exists,
and every support and provenance gate below passes.

## 1. Supersession and observed-information boundary

This is a new study ID, as required by section 6 of
`docs/semifinal-feasibility-stratified-study-preregistration.md`. The v1
support-equivalence implementation gate found that v1's exact nominal
Fraction constraints are not identical to the frozen binary64 validator's
one-picometre comparison-tolerance sliver. Two deterministic witnesses are
old-audit-valid but exact-nominal-invalid. Therefore v1 remains unexecuted with
`mapping_support_equivalence_not_established`; it has no Stage-A artifact,
Stage-B run, scientific endpoint, solver result, score, or candidate.

Before this v2 preregistration, unit development had exercised short
solver-free prefixes of the already-preregistered PCG64 streams solely to test
coordinate, digest, and interface mechanics. Reduced test summaries also
instantiated endpoint-plumbing branches, but they were nonterminal,
nonpersistable fixtures and are not preregistration-valid scientific
endpoints. No complete 10,000-draw cell, 20-cell Stage-A evidence set,
persistable coverage endpoint, Stage-B metric, or antenna solver result was
generated or inspected. The decision to supersede v1 was triggered only by
the named deterministic tolerance witnesses. No observed prefix count, rate,
digest, status, or fixture endpoint value is used to choose any v2 seed, draw
count, threshold, map, quota, agent, endpoint, or budget.

The v2 scientific distinction is prospective and explicit: both Stage-A
representations and both Stage-B agents operate on the same exact nominal
integer support. Binary64 validator tolerance remains a numerical
implementation guard, not part of v2's design support. This restricted support
requires and receives this new study ID; it is not described as byte-identical
to the old audit-accepted support.

## 2. Incorporated immutable specification

The following document remains the base specification:

```text
path: docs/semifinal-feasibility-stratified-study-preregistration.md
commit: dcf9b28797ec0a97ba9b05ed9f8b1710d447b28c
```

Its sections 2 and 3, Stage-A and Stage-B seeds and ordering, RNG derivations,
raw/status digest format, coverage threshold, accepted quotas, ES constants,
budget arithmetic, score, validity gate, candidate keys, endpoints, failure
contract, claim ceiling, and no-openEMS rule are incorporated without change,
except for the exact substitutions enumerated in this v2 document. In a
conflict, this document controls. No unenumerated inference may alter the base
specification.

Immutable upstream evidence remains:

- source/evidence commit
  `66a4325d9bc07ca97a8ec4e6ddf86b2854663a45`;
- 224-entry source manifest SHA-256
  `f747e908ffadbdb7eb3a6eb8ed4809dc21ffcaec63bb97a533f526c5a6913674`;
- R2 appendix SHA-256
  `42ff2d13b5dbb09680a47dd90dfcca83a093811a1a1db950c24557c1a7f4156d`;
- R2 report SHA-256
  `d9abefb0dd4c0e5e709552bd22a36d0bf8f15daf7093e33a38dccbe4ad85bdc0`;
- `L_manual=0.21548949210811824` and unchanged crossing threshold
  `L_required=0.19394054289730642`; and
- the budget commit, summary, hash, P95, method, and single-worker setting
  pinned in base section 2.

The five scientific source blobs listed in base section 2 remain frozen at
source commit, execution commit, and workspace. No old run or artifact byte
may change.

## 3. Exact nominal integer support

The physical fields and equations remain base section 3. For a fixed turn and
each of the 21 frozen integer-interpolated trajectory points, calculate `G`,
`P_i`, `T`, and `H_i` with exact `Fraction` arithmetic exactly as written in
base section 5. The v2 exact nominal support is defined by:

```text
P_i >= Fraction(1500) um
Fraction(400) um <= H_i <= Fraction(40000) um
terminal_ratio_ppm == 0 or T*P_i >= Fraction(200) um
```

All global integer field bounds, half-up quantization, the `1/16` terminal-zero
cutoff, terminal positive-branch map, B-then-A dependency order, monotone
integer bisection, and canonical inverse remain exactly as in base section 5.

The unchanged `audit_trajectory` is still mandatory for every proposal and is
the final authority for binary64 reconstruction, box, topology, collision,
clearance, and connection checks. A v2 proposal is legal only when both the
exact nominal predicate and the frozen audit pass. The audit may not enlarge
the exact nominal support.

For the frozen axis-aligned family, `P`, `H/2`, terminal length, gap, and the
fixed builder provide the algebraic segment and box bounds. The final frozen
audit remains authoritative for numerical and geometric implementation
details. Any decoder output that fails either predicate is a
`FeasibleCoordinateInvariantError` before solver construction, run-directory
creation, or evidence output.

## 4. Disclosed support difference from v1's claimed old support

The source validator compares binary64 values to nominal limits minus or plus
`1e-12 m`. V2 intentionally does not translate that tolerance into its design
support. At minimum, these deterministic tuples demonstrate the difference:

```text
terminal tolerance witness:
  turn=5, feed_gap_ppm=27302, terminal_ppm=77650
  A=(length_um=100000, span_ppm=800000)
  B=(length_um=45000, span_ppm=800000)
  exact terminal segment=199.999999 um
  old audit=valid; v2 exact support=invalid

height tolerance witness:
  turn=3, feed_gap_ppm=27933, terminal_ppm=449231
  A=(length_um=50000, span_ppm=951144)
  B=(length_um=34961, span_ppm=951144)
  exact state-B height=399.999998518... um
  old audit=valid; v2 exact support=invalid
```

These exclusions are disclosed mathematical boundary differences, not a claim
of physical significance. V2 makes no inference about structures admitted
only by the old validator tolerance.

## 5. Two representations with one support

Stage A representation names are frozen as:

```text
legacy-exact-fixed-turn-v2
conditional-exact-feasible-turn-v2
```

`legacy-exact-fixed-turn-v2` uses the six independent inclusive half-up maps
and fixed turn from base section 7. It then applies the v2 exact predicate and
the unchanged audit. A row is `valid` only if both pass.

`conditional-exact-feasible-turn-v2` uses the base section-5 conditional map
with the exact thresholds in section 3 above, then applies the same unchanged
audit. It must have zero decoder errors and 100% validity.

The first exact-predicate failure is deterministic in trajectory-index order
and rule order `pitch`, `height_min`, `height_max`, `terminal`. Its frozen
rejection string is:

```text
exact_nominal_constraint_failed:<rule>:trajectory_index=<00..20>
```

If the exact predicate passes but the frozen audit fails, use the audit's
unchanged rejection reason. The allowed statuses, canonical JSON byte format,
shared raw vector, per-representation status digest, cell order, and all
Stage-A counts remain base section 7.

Because both arms use one exact support, the algebraic release obligation is:

1. every conditional decoder output belongs to the v2 exact support and passes
   the frozen audit;
2. every v2-exact-and-audit-legal integer tuple has a canonical conditional
   preimage;
3. the independent legacy maps have a canonical preimage for every same legal
   integer field tuple; and
4. neither representation gains access to a tuple denied to the other.

Boundary/property tests and archived proposals are machine checks of this
algebraic obligation, not the definition of the support universe.

## 6. Support release tests

Stage A and Stage B remain blocked until all of the following pass:

1. a checked derivation proves the four obligations in section 5;
2. every accepted proposal in the five archived R2 logs and frozen warm source
   that belongs to v2 exact support round-trips byte-for-byte; the gate reports
   exact-support and tolerance-only-excluded counts without using them to alter
   any later rule;
3. the two section-4 witnesses are old-audit-valid, v2-exact-invalid, and
   rejected before solver construction;
4. each turn covers terminal zero, minimum-positive minus one, minimum,
   minimum plus one, and maximum; conditional length minimum minus one,
   minimum, minimum plus one, and maximum; feed-gap/span boundaries; and
   explicit turn-6/state-B narrow-domain witnesses;
5. property samples across all 21 points prove decoder output satisfies both
   predicates, while every sampled v2-legal legacy tuple round-trips;
6. decoder source has no solver, S11, score, frequency, candidate-ranking, or
   archived-metric dependency;
7. mapping failures occur before a solver object or run directory exists; and
8. frozen source blobs and old evidence hashes remain unchanged.

Any failure produces
`mapping_support_equivalence_not_established_under_exact_v2` and authorizes no
Stage-A evidence or solver run. The gate report must disclose the v1 failure
and may not imply v1 ever passed.

## 7. Frozen Stage A v2

Stage A retains all base section-7 values:

```text
turns=(3,4,5,6)
seeds=(101,202,303,404,505)
raw_draws=10000 shared vectors per (turn,seed)
20 cells in turn-major, seed-ascending order
SeedSequence([seed,0,turn,1]) with PCG64
coverage delta threshold=0.20
four/some/none endpoint table unchanged
```

The finite unit-test prefixes disclosed in section 1 do not change, skip, or
offset any formal draw. Every formal cell starts at the frozen stream origin
and runs all 10,000 draws. No prefix result is imported.

Outputs are written only after this v2 preregistration and the separate
implementation commit to:

```text
artifacts/analysis/semifinal-feasibility-stratified-v2-stage-a/
```

Stage A invokes no NEC2 or openEMS object and is not a run-manifest entry.

## 8. Frozen Stage B v2

All base section-8 quotas, scheduler, order, seeds, attempt limits, RNG island
derivations, cold ES behavior/constants, 10-run count, 6,000 accepted pairs,
12,000 NEC2 subprocess curves, and P95 upper bound remain unchanged.

The only identity substitutions are:

```text
agents:
  random-stratified-v2  # agent code 1
  es-stratified-v2      # agent code 2

run IDs:
  semifinal-paired-stratified-v2-random-s{seed}
  semifinal-paired-stratified-v2-es-s{seed}

mapping version:
  conditional-exact-feasible-turn-v2
```

Random seeds run ascending before ES seeds ascending. Every completed run has
exactly 600 accepted pairs, 150 per turn, 1,200 real NEC2 subprocess curves,
zero mapping-invariant failures, and no fallback. No result can stop or resize
another cell.

The pass gate, within-cell ordering, cross-seed endpoint table, hypothesis
selection keys, exact resume/replay contract, legal terminal, descriptive-only
five-seed interpretation, and Random-as-comparator role remain base sections
9 and 10 without change.

## 9. Config and immutable provenance additions

Every Stage-A summary and Stage-B config/summary includes:

```text
study_id=semifinal-paired-feasibility-stratified-exact-v2
spec_revision=2.0-exact-nominal-support
superseded_v1_preregistration_commit=dcf9b28797ec0a97ba9b05ed9f8b1710d447b28c
superseded_v1_preregistration_document_sha256=d5e5c02f9ad86cd09015d1a400af7f0b8aae31a9b7cba2ed3ff35438d6dd47f9
v2_preregistration_commit=<full 40-character commit containing this document>
v2_preregistration_document_sha256=<pinned SHA-256>
implementation_commit=<full 40-character implementation commit>
stage_a_evidence_commit=<full 40-character Stage-A evidence commit, Stage B only>
execution_commit=<full 40-character execution HEAD>
```

All source/R2/budget/frozen-blob fields from base section 9 remain included.
Before output or solver construction, the gate validates both preregistration
commits as ancestors; reads both documents from their exact Git commits;
requires workspace bytes and pinned SHA-256 equality; proves the current
manifest is an append-only successor of the source 224 entries; verifies the
R2 appendix, report, five manifest entries, logs, and summaries byte-for-byte;
and proves every frozen science blob at source, execution commit, and
workspace. The implementation code tree must be committed and clean.

Stage B receives `stage_a_evidence_commit` as a required full-hash API/CLI
input, validates its committed summary/report blobs and ancestry, reads the
implementation commit from that validated Stage-A provenance, and records all
three commits in the config hash. `UNSET`, short hashes, workspace-only
evidence, or discovery by commit-message guessing are forbidden.

## 10. Failure, endpoint, and claim ceiling

Base sections 9--11 remain active. A solver error, non-subprocess curve,
config/evidence mismatch, support invariant failure, replay drift, corrupt
log, or evidence-write failure aborts the ordered matrix. Only exact same-
config resume is allowed. Aggregate endpoints and selected hypotheses remain
null until Stage A has its sole legal endpoint and all ten Stage-B cells have
their sole legal completed terminal.

This study authorizes no openEMS call. The high-frequency independent-solver
anchor remains unreleased. The verdict ceiling is always
`insufficient_evidence`. Even a cross-seed NEC2 gate crossing is only an
unconfirmed computational antenna hypothesis pending an independently
released solver instrument; it is not `CONFIRMED`, `YAF-M1`, a manufacturable
antenna, or an invention claim.

## 11. Outputs, commits, and stop rule

Outputs are:

```text
artifacts/analysis/semifinal-feasibility-stratified-v2-stage-a/
artifacts/analysis/semifinal-feasibility-stratified-v2-stage-b/
artifacts/runs/semifinal-paired-stratified-v2-*/
```

The prospective commit sequence is:

1. `Pre-register feasibility-preserving stratified-turn study` -- retained as
   the unexecuted v1 audit trail;
2. `Pre-register exact-support stratified-turn study v2` -- this document and
   one matching DECISIONS row only;
3. `Implement exact-support stratified-turn gates`;
4. `Run solver-free exact-support representation ablation`;
5. `Run and archive balanced exact-support NEC2 search`.

Before commits 4 and 5, pytest, Ruff, strict mypy, and archive verification
must pass. Each evidence commit requires a fresh no-local clone, checkout of
that commit, full archive verification, and clean tracked status. Git add is
path-scoped; local settings, initial-round GOAI documents, and unrelated files
remain uncommitted. No amend, rebase, old-evidence rewrite, adaptive stop,
extra seed, extra candidate, or openEMS call is authorized.

After the complete Stage-B evidence commit, this study stops. Any independent
solver confirmation or revised physical support requires another prospective
preregistration and cannot alter the frozen v2 selection.
