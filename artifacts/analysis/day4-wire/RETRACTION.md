# Retraction of the Day 4 wire conclusion

The `confirmed_improvement` conclusion in the original Day 4 wire report is
withdrawn and reclassified as `invalid_metric_artifact`. The original report
and archived run files remain byte-for-byte unchanged so the failed reasoning
path stays auditable.

## Evidence

1. The selected GP design was severely mismatched. Step 38 of
   `day4-wire-v4-wifi24-gp-s303` reports `min_s11_db=-0.0558654713 dB` and
   `vswr=316.9070101`. The straight reference
   `day4-wire-v4-wifi24-classic-s0` reports `min_s11_db=-0.0190998173 dB` and
   `vswr=1012.6586822`. These values describe nearly complete reflected power,
   not useful in-band radiation.
2. The invalid composite-score increase was dominated by an unqualified gain
   term. `day4-wire-v4-wifi24-gp-s303` reports `gain_dbi=6.23` and
   `efficiency=1.0`, versus `gain_dbi=0.01` and `efficiency=1.0` for
   `day4-wire-v4-wifi24-classic-s0`. Lossless NEC2 makes the efficiency term
   non-discriminating, and the 6.23 dBi value requires a gain-path audit before
   it can be used.
3. The score was effectively saturated. Across the five archived random runs
   `day4-wire-v4-wifi24-random-s101` through
   `day4-wire-v4-wifi24-random-s505`, the best-score mean was 0.750747 with
   sample SD 0.000514. The comparison therefore did not carry meaningful
   geometry sensitivity.
4. Both apparent confirmations were boundary-minimum artifacts.
   `day4-wire-v4-crosscheck-top1` reported NEC2/openEMS S11 depths
   -0.055865/-0.105010 dB and Pearson 0.993573; both minima were sample index 0.
   `day4-wire-v4-crosscheck-top2` reported -0.053851/-0.108057 dB and Pearson
   0.999417; both minima were also sample index 0. The reported zero resonance
   gaps were therefore trivial agreement between flat, non-resonant curves.

The valid `day4-dipole-anchor` evidence is unaffected: the same NEC2 chain
found a real -15.3 dB half-wave-dipole resonance. Protocol-v2 anchor and grid
convergence attribution evidence also remains unchanged.

## Corrective action

Protocol v2.1 adds an in-band resonance-validity precondition before any
cross-solver verdict. Wire scoring will use mismatch-adjusted realized gain,
will assign zero weight to lossless-NEC2 efficiency, and will be validated
against a real half-wave-dipole known answer before a replacement batch is
allowed to start.
