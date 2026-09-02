# Day 6.5 v2 cross-check instrument execution note

Status: pre-registered before the first `day65-freeform-v2` solver run.
This note does not change the Day 6 dual-band score, the v2.1 validity and
agreement thresholds, the optimizer, the batch matrix, or the frozen top-two
selection rule.

## Why the final openEMS setting is fixed at 6x

Rotation run `day65-freeform-rotation-invariance-r12` is the first repaired
free-form instrument that passed every pre-registered orientation gate. It
used openEMS refinement 6x, 240,000 maximum time steps, the full 1.5--3.5 GHz
known-answer sweep, and the sphere-ended finite-radius native wire. Coarser
free-form instruments were explicitly not released for claims. Therefore a
Day 6.5 v2 final cross-check uses 6x/240k even if a source-specific 1x-to-2x
diagnostic happens to move by no more than 3%.

## Frozen v2 execution tree

After the six NEC2 exploration runs are complete and archived, the deterministic
unshaped-score selector is run once and its two source addresses are committed.
Only then may solver work on those designs begin.

Candidate top 1 is evaluated with repaired openEMS at 1x and 2x over the full
1.5--6.5 GHz/251-point sweep. Adjacent high-band self-convergence is defined
exactly as before: both levels need valid internal minima at or below -6 dB and
the frequency shift must be at most 3%. If 1x-to-2x fails, the sequence extends
to 4x and then 6x. A missing valid resonance is a failed convergence comparison,
not zero movement. All completed levels and elapsed times are retained.
Regardless of an earlier diagnostic pass, the released 6x/240k curve is the
claim instrument; a byte-identical completed 6x convergence curve may be reused
as top 1's final openEMS curve.

The two final run IDs are `day65-freeform-v2-final-crosscheck-top1` and
`day65-freeform-v2-final-crosscheck-top2`. Each uses real NEC2 at lambda/160
and repaired openEMS at 6x/240k, with the unchanged 1.5--6.5 GHz/251-point
sweep. The final gates remain: a local internal minimum at or below -6 dB in
each target band for each solver, at most 5% resonance-frequency difference in
each band, and whole-sweep Pearson correlation at least 0.8. Discovery also
requires unshaped base score at least 1.10 times archived OCFD score
0.617137421. Both frozen candidates are always reported and no third candidate
or result-driven retry is permitted.
