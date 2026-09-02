# GOAI semifinal reproducibility guide

This guide verifies the public submission without running NEC2 or openEMS. The public GitHub
repository is a sanitized root snapshot: it contains the final tracked tree and all 255 archived
runs, but deliberately omits the original commit/tree chronology and all excluded prompt/config
blobs from the private research history.

## Ten-minute reviewer path

Use Python 3.11 or newer from a clean clone. The minimal Python dependencies are required, but Git
history, GPU, database, web service, and electromagnetic solvers are not:

```powershell
git clone https://github.com/1ove9/yaf-goai-semifinal yaf
cd yaf
python -m venv .venv-review
.venv-review\Scripts\python.exe -m pip install -r requirements-semifinal.txt
.venv-review\Scripts\python.exe scripts/archive_run.py --verify
.venv-review\Scripts\python.exe scripts/semifinal_public_snapshot_verify.py
```

The first command recomputes the SHA-256 of every `log.jsonl` and `summary.json` named by the
current manifest. It must report 255 `OK` entries, no `MISMATCH`, and exit zero.

The second command verifies the publication receipt, frozen analysis-file hashes, the complete
B-parent conditional-completion matrix, and the counterfactual A-span probe. Its terminal output is:

```text
solver_calls=0
history_mode=sanitized_root_snapshot
original_history_replay=not_available
archive_verify=255/255 OK
b_completion_h1_h2=702/0
a_span_probe_solver_calls=32
a_span_probe_monotonic=10/10
a_span_probe_endpoint=span_support_sufficient_in_frozen_counterfactuals
support_certificate=480002/480002 OK
final_verdict=insufficient_evidence
```

Both commands are read-only. The reported 32 solver calls are frozen historical evidence; the
public verifier does not execute them.

## What the public commands prove

1. The 255-entry manifest has unique run IDs and every archived run file matches its frozen hash.
2. The conditional-completion matrix is exactly two parents × two agents × five seeds, with
   20/20 completed runs, 6,000 accepted evaluations, zero rejections, and subprocess-only curves.
3. Recalculation from the 20 matrix rows gives H1/H2 = 702/0 and the frozen endpoint
   `b_completion_pair_validity_without_effect_crossing`.
4. The A-span diagnostic contains 10 parent×seed blocks on the frozen three-dose grid, 10/10
   monotonic responses, p01/p02 crossing counts of 5/5, and 32 subprocess calls.
5. Positive-dose probe records remain `counterfactual_only` and ineligible for the original H1/H2,
   candidate-pool, or agent-comparison populations.
6. Both studies retain the verdict ceiling `insufficient_evidence`.

These checks establish byte integrity and deterministic analysis facts. They do not independently
rerun search agents or electromagnetic solvers, prove manufacturability, or provide dual-solver
candidate confirmation.

## Sanitized-history disclosure

The original internal science freeze is identified by provenance label
`18b1d20d35ec1cb0c401bd951c64f202c3dd67bd` and contained 144 research commits. To ensure that
excluded local tool state and historical prompt transcripts cannot be recovered from GitHub, their
blobs and the original commit/tree chronology were not copied into this repository. Consequently:

- original commit identifiers appearing in reports are labels, not resolvable public objects;
- the preregistration commit ordering cannot be replayed from public Git alone;
- `scripts/semifinal_demo.py --verify` remains historical internal tooling and is not the public
  reviewer entry because it expects the omitted commits;
- the public substitute is the 255-entry byte ledger plus
  [`PUBLIC-SNAPSHOT-RECEIPT.json`](provenance/PUBLIC-SNAPSHOT-RECEIPT.json).

This limitation is explicit rather than hidden. The original repository remains private and is not
included as a bundle, hidden ref, alternate object store, or release attachment.

## Evidence locations

- Current run ledger: `artifacts/runs/manifest.json`
- Conditional-completion report and appendix:
  `artifacts/analysis/semifinal-paired-b-completion-v1/`
- Solver-free support certificate:
  `artifacts/analysis/semifinal-paired-b-completion-v1-certificate/`
- A-span causal-probe report, summary, and plot:
  `artifacts/analysis/semifinal-a-span-support-causal-probe-v1/`
- Reviewer narrative and reference frame: `docs/submission/`
- Public snapshot receipt: `docs/provenance/PUBLIC-SNAPSHOT-RECEIPT.json`

## Developer quality checks

The original science freeze recorded 795 passing tests, Ruff success, and mypy strict success over
165 source files. Those historical QA facts are bound to the source identifier in the receipt. A
developer who installs the full project dependencies may additionally run:

```powershell
python -m pytest tests\ -q
python -m ruff check .
python -m mypy yaf_core yaf_ai yaf_solvers yaf_api yaf_db yaf_worker --strict
```

The public root intentionally lacks the commits required by a subset of historical ancestry/blob
gate tests. Running the entire historical `tests/` tree in this snapshot therefore produces
expected early ancestry failures in those tests; the release does not relabel or suppress them.
Public CI runs the history-independent snapshot regression explicitly:

```powershell
python -m pytest tests\unit\test_semifinal_public_snapshot_verify.py -q
```

Code-quality checks cannot turn a failed scientific gate into a positive verdict.
