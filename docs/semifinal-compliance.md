# GOAI semifinal compliance and provenance disclosure

## Scope of the submission

The submitted result is an auditable exploration environment and a bounded NEC2-only paired-state
computational study. The final verdict is `insufficient_evidence`. The submission does not claim a
confirmed invention, YAF-M1, dual-solver candidate confirmation, manufacturability, physical
measurement, or autonomous real-time adaptation.

The terminal conditional-completion study observed H1/H2 = 702/0 in its frozen conditional space:
paired-state validity was observed, while no accepted record crossed the preregistered numerical
effect line. A separate preregistered A-span probe diagnosed an active space boundary. Its positive
doses are counterfactual-only and do not belong to the original H1/H2 or candidate population.

## Numerical authority

- Archived electromagnetic values come from solver subprocess output or deterministic metrics
  computed from archived curves.
- NEC2 was the frozen search/reference instrument for the paired-state studies.
- openEMS was reserved as an independent confirmation instrument. Its 5.8 GHz rod harness failed
  its preregistered observability gate, so candidate openEMS runs were not authorized.
- No LLM, image model, Blender scene, Matplotlib figure, fallback analytical path, or human-edited
  number is allowed to create or replace a scientific result.
- Display images are deterministic views of archived data and are non-evidentiary.

## Public-history sanitation

The public repository is a new root snapshot of the final cleaned tree. It intentionally omits the
private 144-commit chronology and all excluded prompt/config blobs, so historical prompt
transcripts and local tool configuration cannot be recovered through Git. Original commit IDs in
reports remain provenance labels; they are not resolvable public commits, and their ordering cannot
be independently replayed from this GitHub repository.

The trade-off is recorded in `docs/provenance/PUBLIC-SNAPSHOT-RECEIPT.json`. Public assurance is
provided by the 255-entry SHA-256 ledger, frozen-file hashes, and the history-independent snapshot
verifier. The private source repository is neither pushed nor packaged as a Git bundle.

## Human and AI roles

- The sole human creator and entrant is `1ove9`; `source sequence` is the GOAI team name.
- The human entrant selected the scientific objective, accepted preregistered stopping rules,
  supplied compute, and owns publication decisions.
- Codex assisted with repository inspection, typed implementation, tests, execution orchestration,
  evidence archiving, report generation, and public-snapshot sanitation.
- Claude/Fable assisted with planning and audit framing; Grok was used for adversarial plan review.
- AI assistants did not replace candidates after seeing results and did not alter frozen scientific
  thresholds, scores, seeds, budgets, or archived evidence bytes.
- Report prose is AI-assisted and constrained by machine-readable evidence. Quantitative headlines
  are mapped in the evidence index.

## Data and experiment provenance

The paired-state study uses no external training or observational dataset. Proposals were generated
inside frozen search spaces and evaluated by electromagnetic solver subprocesses. Accepted
evaluations, rejections, configuration, seed, solver mode, and summary are archived as JSONL/JSON.
The manifest binds each run's evidence files by SHA-256.

The terminal B-parent conditional-completion matrix contains 20 runs and 6,000 accepted records.
Its report and appendix are under
`artifacts/analysis/semifinal-paired-b-completion-v1/`. The independent diagnostic consists of 32
archived NEC2 calls and is under
`artifacts/analysis/semifinal-a-span-support-causal-probe-v1/`.

## Third-party software and licenses

- YAF-authored source is released under the repository's MIT `LICENSE`.
- The reused Antenna Forge code base is MIT-licensed; this repository preserves an MIT license.
- openEMS archival output reports openEMS v0.0.36 and CSXCAD v0.6.3. These executables and
  libraries retain their upstream licenses; this repository does not relicense them.
- NEC2 is invoked through a local `nec2c` subprocess. The archive records solver name and
  `subprocess` mode but does not persist the executable's upstream build identifier; this remains a
  disclosed reproducibility limitation.
- Python dependencies are declared in `pyproject.toml`; the minimal review set is in
  `requirements-semifinal.txt`.

Downstream users must review upstream solver and library terms for their distribution context.

## Generated-media disclosure

Scientific charts are deterministic transforms of archived numeric rows. Any geometry render,
Blender composition, or edited video is presentation-only and must carry this statement:

> Visualization reconstructed from archived parameters; it does not participate in scientific
> scoring or validation.

No generated media is presented as a measurement, simulation result, or physical prototype.

## Known limitations

- H1 was observed in a conditional space, but H2 remained zero; the preregistered effect line was
  not crossed.
- The A-span probe used a finite, ES-only source queue and is a model-internal counterfactual
  diagnostic, not an unbiased population experiment.
- The candidate population has no authorized openEMS cross-check.
- The 21-point trajectory audit is discrete and does not prove continuous mechanics.
- Sleeve overlap, contact resistance, actuator volume, material loss, stress, tolerances, control
  electronics, sensing, and feedback are outside the ideal PEC model.
- The public snapshot proves current bytes and terminal analysis facts, but not the private Git
  chronology.

These limitations are part of the result, not hidden exceptions.
