# A-span support probe: pre-numerical Windows checkout conformance note

Status: frozen after the first committed preflight inspection and before every
NEC2 or openEMS call in this study.

Study ID: `semifinal-a-span-support-causal-probe-v1`

Preregistration commit: `5a6e778f57d37511be7b442ef890024079d81f63`

Implementation commit inspected: `5d5b7792f9f56931c435ec6661ae82b792f428e2`

## Observed preflight condition

The source gate stopped before constructing an adapter because this Windows
checkout has `core.autocrlf=true`. Three of seven frozen Python runtime paths
were physically checked out with CRLF bytes while their committed Git blobs are
LF. Their source-commit blob IDs, implementation-commit blob IDs, current HEAD
blob IDs, and Git attribute-aware filtered worktree hashes are identical; `git
diff --exit-code` reports no code change. The remaining four frozen paths are
already raw-byte identical.

No solver object was constructed and no numerical call, log row, summary, or
analysis artifact exists. This is a portability defect in the implementation
of the workspace-code identity check, not drift in the frozen scientific code
or source evidence.

## Prospective conformance correction

For the seven frozen **text source-code paths only**, the source gate will
continue to require the exact preregistered Git blob ID at the source,
implementation, and execution commits. It will identify the current worktree
through Git''s path-aware clean filter (`git hash-object --path=<path>`), which
normalizes only the configured text line ending before comparing the blob ID.
Any non-line-ending content change still produces a different filtered blob and
terminates the study.

All archived JSON/JSONL evidence, manifest, source appendix, source report, and
preregistration document retain raw-byte equality and SHA-256 checks. The new
probe implementation itself also retains raw committed/worktree byte equality.

This correction changes no source cohort, dose, geometry, box, solver,
frequency, score, threshold, call order, endpoint, retry rule, output, or claim
boundary. The full quality gate must pass again before numerical execution.

