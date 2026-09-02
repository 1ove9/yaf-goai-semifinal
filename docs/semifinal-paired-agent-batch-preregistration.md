# Semifinal paired-agent batch and warm-parent binding preregistration

Date: 2026-08-29

Status: frozen before any Random, ES-cold, or ES-warm numerical evaluation.

## Scope and inherited invariants

This task executes the three NEC2-only search arms already defined by
`docs/YAF-semifinal-plan-v3.4-final-freeze.md` sections 9 and 14. It supersedes
only the earlier statement that `scripts/paired_batch.py` is a validation-only
skeleton. It does not change the paired centerline, parameter bounds,
quantization, score, frequency tables, trajectory audit, candidate order,
cross-solver protocol, budget formula, ES constants, or any threshold.

The search instrument remains real NEC2 at lambda/20 through
`PairedNEC2Solver`, with `realized_gain_dbi=None`, `YAF_NO_FALLBACK=1`, and
`solver_mode=subprocess` required for every returned curve. The openEMS flag is
the literal value `false`, `anchor_released` remains false, and the verdict
ceiling remains `insufficient_evidence`. No openEMS or anchor run is authorized
by this document.

## Archived budget source

The immutable source is
`artifacts/runs/semifinal-paired-budget-preflight/summary.json`, committed in
`253090b80df23184cb8521cbbe77af1e38a9b734` with summary SHA-256
`b0a7f612e98064a3cf415731d89a917872fbc3931ee6d1f0116d8de8aaff6138`
and config hash
`d618134588d0db607e21638fdffed4ebff3627a669d281b3dfef456bafc43f92`:

- `t_pair_p95_seconds = 3.7018278000032296`, using the frozen higher method;
- `raw_budget = 907`;
- capped `budget = 300`;
- classification `three_seed_descriptive_statistics`;
- `parallel_workers = 1`.

Every agent run therefore has exactly 300 accepted paired evaluations unless a
frozen proposal-attempt terminal condition is reached. Rejected geometry costs
no evaluation budget. The budget is not reduced or increased after seeing any
result.

## Frozen matrix, run IDs, and order

The execution order is exact and sequential:

1. `semifinal-paired-random-s101`
2. `semifinal-paired-random-s202`
3. `semifinal-paired-random-s303`
4. `semifinal-paired-es-cold-s101`
5. `semifinal-paired-es-cold-s202`
6. `semifinal-paired-es-cold-s303`
7. `semifinal-paired-es-warm-s101`
8. `semifinal-paired-es-warm-s202`
9. `semifinal-paired-es-warm-s303`

The agent labels are respectively `random`, `es-cold`, and `es-warm`; the seeds
are exactly 101, 202, and 303. Each run has its own directory, config hash,
LF-only JSONL, atomic state, and archive entry. Execution is single-process so
the preflight's `parallel_workers=1` assumption remains true.

Random uses `PairedRandomProposer(seed)`. Cold ES uses
`PairedRestartedES(seed)` with no parent. Warm ES uses the same frozen ES and
seed but begins from the single committed parent below; its first budgeted
proposal is a mutation and the parent itself is not re-evaluated. Warm is an
additional discovery arm and is not used to claim optimizer superiority.

## Unique warm-parent binding

The parent source is immutable evidence:

- baseline run: `semifinal-paired-manual-baseline`;
- baseline evidence commit:
  `906835eceeae2e48a652e2b7fa891fd3e8461440`;
- parent pair hash:
  `e9f13ba6ede326e3adc4a48ba0a7658c0ca712434550ed98bffab681d262b321`;
- source paired-evaluation step: `288`;
- hardware hash:
  `d8d7e70ee2f085ca4c9a73b37c9c69a63bd02b97bdb0307d4fda0934642ca933`;
- state-A geometry hash:
  `cc6d3d8b48d03d8843c4663eb3018b55c10cec15f5066c8975537b01019c69e9`;
- state-B geometry hash:
  `371fb99d21536e5de565755d55599e778ae9b0cf3fb277c0a155adde4071e783`;
- parent JSON SHA-256:
  `5d1aef64ac367db741834d94fb42735d4d8670269df376637b52785e59557f08`;
- archived `search_score = 0.7845105078918817`;
- `hardware_grid_index = 6`, `pair_grid_index = 963`;
- `valid_pair_search = false`, `positive_eligible = false`.

The source JSON's nullable `baseline_commit` field is an intentional pre-commit
placeholder and is not rewritten. Before constructing any warm config, the
batch entry point must prove that Git commit `906835e...` contains the exact
parent blob above and source log row, that it is an ancestor of the batch
execution commit, and that the working-tree bytes match it. Every warm
`PairedRunConfig` carries the full baseline commit, parent run ID, source step,
parent artifact SHA-256, pair hash, hardware hash, both state geometry hashes,
both grid indexes, and archived search score. Every field enters its config
hash. Random and cold configs carry none of this manual-parent provenance. The
batch config also carries the full execution commit and the archived preflight
summary SHA-256/config hash so source code and budget provenance are explicit.

All three warm seeds share this one parent. Agent or openEMS output can never
replace it.

## Resume and failure semantics

`run_paired_adaptive` is the only numerical runner. On restart it reconstructs
state from the append-only log, deterministically replays the proposer, verifies
every proposal identity, and resumes without duplicating an accepted row. A
completed matching summary is idempotently reused.

A geometry rejection is logged, advances the proposer RNG, consumes no solver
call and no accepted-evaluation budget, and remains subject to the frozen
consecutive and total-attempt limits. If a run reaches one of those limits, its
`insufficient_feasible_proposals` summary is a legitimate terminal negative
result and the next independent matrix cell still runs.

Any solver exception, non-subprocess result, geometry/hash/radius mismatch,
config mismatch, replay drift, or log/state write failure stops the entire
matrix immediately. It authorizes only an exact same-config resume, never a new
run ID, seed, budget, threshold, proposer setting, or skipped failure point.
No result-driven retry or fallback is allowed.

## Candidate freeze after the matrix

Only after all nine cells have terminal summaries may candidate selection run.
It reads archived NEC2 logs only and freezes exactly three objects under v3.4
section 11:

1. top ES from the combined ES-cold and ES-warm records;
2. top Random from the three Random records;
3. the already frozen manual diagnostic parent.

For each agent pool, eligibility is `valid_pair_search` first, followed by
`base_score` descending, `hardware_hash`, `run_id`, and `step_index` ascending.
If a pool contains no valid pair, its selected row is diagnostic and has no
positive eligibility. The manual row remains excluded from agent pools. The
three selections must be committed before any later openEMS output; this task
does not authorize those cross-checks.

## Test and release gates

Before real NEC2 execution, tests must prove:

1. the matrix contains exactly the nine ordered cells above and budget 300;
2. run IDs, agent labels, and seeds cannot drift;
3. Random and cold configs reject warm provenance;
4. each warm config binds the exact full baseline commit, run ID, and pair hash;
5. the committed parent blob and working-tree parent bytes match the frozen SHA;
6. all three warm seeds start with a mutation rather than parent re-evaluation;
7. true Random, cold ES, and warm ES interruption/resume traces equal their
   uninterrupted traces after removing timestamps, with no duplicate row;
8. frozen proposal-limit termination continues to the next independent cell;
9. a solver or evidence-integrity exception stops later cells;
10. every mock solver result is subprocess-only and uses the exact A/B tables;
11. malformed matrix, parent SHA/field/commit ancestry, or config provenance
    fails before solver construction, run-directory creation, or evaluation;
12. exact and prefix forms of both manual and preflight run IDs are excluded
    from every agent candidate/statistics pool;
13. candidate freezing separates ES, Random, and manual pools and obeys section 11;
14. the preflight, manual baseline, rod-r1, and meander anchor archives retain
    their committed SHA-256 values.

Full pytest, Ruff, strict mypy, and `archive_run.py --verify` must pass before the
first agent evaluation. The preregistration commit must be embedded in every
run config and precede every run timestamp.

## Evidence and stopping point

Each completed or frozen-limit run is archived immediately after the matrix:
Random uses role `baseline-random`; both ES arms use role `other`. Notes contain
`batch=semifinal-paired agent=<agent> seed=<seed>`. The worktree and a fresh
clone must both pass the full manifest verifier. Existing artifacts are not
rewritten, and `.claude/settings.local.json` plus GOAI draft documents remain
uncommitted.

After the nine runs and NEC2-only three-object freeze are committed, execution
stops. No openEMS, rod anchor, 2.45 GHz anchor, or cross-check is started without
a later preregistration.
