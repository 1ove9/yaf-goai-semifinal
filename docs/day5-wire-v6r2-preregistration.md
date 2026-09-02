# Day 5 wire-v6r2 recovery preregistration

Status: frozen before the first `day5-wire-v6r2` numeric run.

## Why a new batch and space version are required

`day5-wire-v6r1` was stopped under its preregistered sanity rule after four
complete GP seeds. None of the four had a target-band minimum both internal and
at most -6 dB. Three seed winners pressed against the direct 80 mm length upper
boundary. The source-addressed rows are retained in the archive; the interrupted
seed 505 is also retained as a failed partial run rather than deleted.

The fixed diagnostic design is `day5-wire-v6r1-wifi24-gp-s101`, step 11,
geometry hash `a3915875b0190b2f90319cda65fa24c7abac48afae046c6cace20d2fd3d80769`,
total length 79.898028 mm. Run `day5-wire-v6r1-crosscheck-top1` measured a
2.560 GHz lambda/20 NEC2 resonance and a 2.720 GHz 2x-openEMS resonance. Its
frequency gap was 5.882353%, Pearson correlation 0.578559, and v2.1 verdict
`DIVERGENT`. This diagnostic is not a confirmation claim.

An inverse-length estimate for a 2.45 GHz resonance is 83.484 mm from NEC2 and
88.703 mm from openEMS. The new `meander-dipole-v2.1-5d` therefore changes only
the direct total-length upper bound from 80 to 100 mm. Its range is 50--100 mm;
turns 2--6 and every other bound remain identical to v2. An exhaustive scan of
its 80 bound cases must pass geometry validation before execution.

## Frozen retry

The retry batch is `day5-wire-v6r2`, with the unchanged matrix GP/Random x seeds
101, 202, 303, 404, 505, budget 400, plus classic. The score remains
`wire-realized-gain-v2`; NEC2 exploration remains lambda/20; v2.1 resonance and
agreement thresholds are unchanged. The top-2 sorting key and lambda/20, /40,
/80 plus 2x-openEMS convergence plan are inherited byte-for-byte in meaning from
`docs/day5-wire-v6-preregistration.md`.
