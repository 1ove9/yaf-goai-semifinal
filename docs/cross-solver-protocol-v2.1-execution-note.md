# Protocol v2.1 execution note: converged-instrument final check

Status: frozen before every Day 5-1b simulation run.

## Unchanged scientific criteria

This execution note changes no protocol-v2.1 criterion. Each final curve must
still have an internal minimum outside the first/last three samples, depth at
most -6 dB, resonance-frequency difference at most 5%, and Pearson correlation
at least 0.8. The sweep remains 1.5--3.5 GHz with 201 points. Only numerical
instrument discretization is refined under the already registered requirement
to select instrument settings from convergence evidence.

## Frozen instrument sequence

- openEMS uses the existing 1x and 2x evidence, then runs 4x. Adjacent resonance
  movement at most 3% selects the finer level as converged. If 4x still fails
  and its measured runtime is at most 1800 seconds, exactly one 8x run is made.
  If 4x exceeds 1800 seconds, exactly one 3x run replaces further refinement.
  Failure of the final feasible adjacent pair is recorded as
  `infeasible_at_current_compute`; sweep width and point count are never reduced.
- NEC2 appends exactly lambda/160 to the existing lambda/20, /40, /80 sequence.
  Lambda/80 to lambda/160 movement must be at most 3%. Gaps are compared against
  the final feasible openEMS curve and must remain monotonically non-increasing.
- Final attribution is `instrument_boundary` when both instruments converge,
  gaps narrow monotonically, and the final gap is at most 5%; `genuine_anomaly`
  when both instruments converge but the residual gap exceeds 5%; otherwise it
  is `infeasible_at_current_compute`.

## Candidate freeze before simulation

The source batch contains exactly 4001 archived evaluation records. No new
batch or candidate search is permitted.

### Candidate A: score-ranked top-1

- source: `day5-wire-v6r2-wifi24-gp-s202`, step 255
- geometry hash: `e3bcb25f8878021a281d458e2d94821c8a7bf79da8116b2618d4623a5dc66ca8`
- parameters: turns 5.906579656565064, span ratio 0.9986467443505643,
  total length 0.0815119207459139 m, feed-gap ratio 0.05166008263178219,
  terminal ratio 0.9988334244935697
- archived target-band evidence: score 0.7061724619536333,
  S11 -6.128246308767721 dB at 2.478 GHz (index 39), realized gain
  0.7259098925184921 dBi

### Candidate B: deepest logged target-band S11

The frozen rule scans every evaluation event from all eleven v6r2 runs, keeps
records whose logged minimum frequency is within 2.40--2.50 GHz inclusive, then
sorts by `min_s11_db` ascending. Ties use score descending, run ID ascending,
then step ascending. No internal-minimum or -6 dB filter is applied during
selection; those remain final protocol gates.

- source: `day5-wire-v6r2-wifi24-gp-s202`, step 253
- geometry hash: `e580526705b059e0064bc3b4d0d432927bcb6ec67f788607ca2086ded2391ebe`
- parameters: turns 5.527146757163459, span ratio 0.9934845182961476,
  total length 0.0809817061866214 m, feed-gap ratio 0.059112582048279946,
  terminal ratio 0.9091394724253632
- archived target-band evidence: score 0.7061332002813302,
  S11 -6.175476786386045 dB at 2.498 GHz (index 49), realized gain
  0.7110347354033257 dBi

The geometries are distinct. Both candidates are reported regardless of result;
no third candidate may be added. Each receives an independent v2.1 verdict.
Before observing either final verdict, the environment-level decision is frozen
as: if either candidate is `CONFIRMED`, the environment has its first confirmed
finding; otherwise the final result remains divergent or infeasible exactly as
the two recorded verdicts and convergence evidence require.

