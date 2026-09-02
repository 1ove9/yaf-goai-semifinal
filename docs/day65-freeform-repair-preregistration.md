# Day 6.5 free-form renderer repair and dual-band hunt preregistration

Status: frozen before every Day 6.5 numerical solver run.

## Known limitation and honest target

The Day 6 candidate set remains frozen. Candidate A is
`day6-freeform-dual-gp-s202` step 193 and candidate B is the same run step 172.
Candidate A already fails the high-band resonance-validity precondition in NEC2
(-5.147263 dB versus the unchanged -6 dB threshold), and candidate B fails the
10% OCFD improvement gate. Repairing openEMS therefore cannot turn either
frozen candidate into a confirmed dual-band discovery.

Day 6.5 has three ordered outcomes. First, repair the free-form openEMS
instrument and release it only through the rotation-invariance known answer.
Second, independently re-evaluate both target bands of the two frozen Day 6
candidates; a low-band confirmation is explicitly a solver-consistency result
for one band, not a dual-band discovery. Third, run a separately identified
optimization batch whose candidates may earn a dual-band verdict. Negative
results at any stage remain reportable evidence and do not authorize threshold
changes.

## Frozen renderer repair

Only the `freeform_wire_3d` openEMS XML branch changes. Every oblique radiating
centerline edge is sampled in order and converted to a deterministic balanced
Manhattan staircase of axis-aligned subsegments. The maximum advance before a
new stair vertex is `lambda(6.5 GHz)/40 = 1.153048 mm`; endpoints and arm order
are exact. Within each sampling interval, the axis increments are interleaved
by normalized accumulated progress, with x, y, z as the deterministic final
tie-break. This avoids grouping a whole x move before a whole y or z move.

Each stair is emitted through the already exercised meander PEC `Box` path.
The existing meander mapping is retained exactly: a box has zero nominal span
on its two transverse axes, and mesh planes are placed at the centerline and at
`centerline +/- resolution`. Thus the effective FDTD conductor cross-section is
mesh-defined; the physical wire radius remains the NEC2 radius and a validation
constraint, not a falsely claimed sub-cell openEMS diameter. Day 6.5 applies
that same centerline-box and bracketing-line rule. It does not change the
meander, dipole-anchor, patch, generic-wire, NEC2, or refinement=1 fixture
paths.

The staircase is a numerical representation, not identical geometry to the
NEC2 oblique straight segment. Its acceptability is decided only by the frozen
rotation test below.

## Frozen rotation-invariance release gate

A center-fed 2.45 GHz straight half-wave dipole of total radiating length
61.182134 mm and the unchanged 0.6 mm x-directed feed gap is evaluated in three
orientations: x-axis aligned, 45 degrees in the xy plane, and 45 degrees out of
plane in the xz plane. Except for orientation, the centerline, radius, 50 ohm
port, open boundary, sweep, and sample frequencies are identical. The window is
1.5--3.5 GHz with 201 points. openEMS uses refinement 1x for the release gate;
NEC2 uses lambda/160 as an independent control.

For all three openEMS orientation pairs, all of the following must hold:

- relative resonance-frequency difference at most 2%;
- resonance-depth difference at most 1.5 dB;
- full-window Pearson correlation at least 0.95.

Each resonance must first be an internal minimum outside the first and last
three samples and at most -6 dB. All three pairwise comparisons must pass.
Failure stops candidate re-verdict and the new hunt; it permits renderer repair
under these same thresholds but never threshold relaxation. The real three-
orientation curves become a permanent fixture only after this gate passes.

## Frozen Day 6 candidate re-verdict

After release, only candidates A and B are rerun. Candidate A is used for a
repaired-renderer high-band openEMS 1x/2x adjacent-grid check. Self-convergence
still requires valid high-band resonances and at most 3% movement; shallow
minima cannot establish convergence. The finest passing instrument is frozen
for both candidates. Each candidate is then evaluated once on the unchanged
1.5--6.5 GHz / 251-point sweep against lambda/160 NEC2.

Protocol v2.1 is applied per band without modification: both solvers need an
internal minimum at most -6 dB and a resonance-frequency difference at most
5%; whole-sweep Pearson must be at least 0.8. No third candidate or result-
driven retry is allowed. If candidate A passes the low band, the only permitted
claim is: "The GP-discovered three-dimensional free-form wire (472.7 mm folded
into a 40 mm box) is cross-solver confirmed in the 2.4 GHz band under the
preregistered criteria; its high band does not meet the valid-resonance
precondition, so the dual-band objective remains unmet."

## Frozen `day65-freeform-v2` hunt

The geometry remains `freeform-wire-3d-v1-n7`: 21 coordinates, the same 40 mm
cube, symmetric single feed, radius, rejection constraints, and lambda/20 real
NEC2 exploration oracle. The matrix is agents `{es, random}` x seeds
`{101, 202, 303}`, budget 500 accepted evaluations per run. Random is unchanged
uniform sampling over the identical proposal space.

The ES is a deterministic restarted (1+1)-ES in normalized [0, 1]^21 space.
It starts from a valid uniform draw, uses independent Gaussian mutations with
initial sigma 0.15, and reflects coordinates at the bounds. Every block of 20
accepted mutations applies the 1/5 rule: multiply sigma by 1.5 when the strict
success fraction exceeds 0.2, otherwise divide by 1.5; clamp sigma to
[0.01, 0.30]. A strict shaped-score improvement replaces the local incumbent.
After 75 consecutive accepted non-improvements, the next valid uniform draw
unconditionally starts a new local trajectory and resets sigma to 0.15. Invalid
geometries are logged as rejected and consume no evaluation budget. The seed
drives one NumPy PCG64 stream, making restarts deterministic.

The scientific FoM remains exactly Day 6 accepted power:

`base_score = min(1 - 10^(S11_2.4/10), 1 - 10^(S11_5.8/10))`.

The optimizer alone observes

`search_score = base_score + 0.25 * valid_both_bands`,

where `valid_both_bands` means each target band has a sampled local internal
minimum at most -6 dB. The fixed 0.25 bonus is logged separately. Random does
not use feedback, but its rows carry the same diagnostic fields. Reports,
OCFD-relative improvement, paired comparisons, candidate ranking, and every
discovery verdict use the unshaped `base_score`; the bonus is never an effect
size.

Unique accepted ES rows are ranked by unshaped base score descending, then run
ID and step index ascending, and deduplicated by geometry hash. Exactly two are
frozen before openEMS output is observed. The repaired top-1 instrument is
checked at 1x/2x under the same valid-resonance and 3% high-band movement rule;
the finest passing setting is used once for both top candidates. A dual-band
`confirmed_improvement` still requires at least 10% over the archived OCFD
score 0.617137421, valid -6 dB resonances and at most 5% frequency gaps in both
bands, and whole-sweep Pearson at least 0.8. No score shaping changes these
gates.

## Evidence and stop rules

Every real run must report `solver_mode=subprocess`; `YAF_NO_FALLBACK=1` is
mandatory. Rotation evidence, repaired convergence, candidate re-verdict,
six hunt runs, frozen hunt selection, final cross-checks, failures, and elapsed
times are archived under new Day 6.5 IDs. Existing 177 manifest entries and all
Day 6 analysis bytes remain unchanged. The rotation release gate precedes every
other Day 6.5 solver stage. The hunt selection is committed before its first
openEMS cross-check. Any incomplete stage is reported as incomplete rather than
silently reducing sweep width, points, seeds, budget, or candidate count.

## Renderer iteration 2 amendment after the failed release gate

The first preregistered balanced-Manhattan representation was executed under
run `day65-freeform-rotation-invariance` and failed without releasing the
instrument. NEC2 returned 2.320 GHz for all orientations, whereas openEMS
returned 2.220 GHz for the axis case and 2.050 GHz for both 45-degree cases.
The axis-to-oblique pairs had 7.962529% frequency difference, about 4.70 dB
depth difference, and Pearson about 0.485. This is direct evidence that a
zero-width Manhattan path introduces an orientation-dependent electrical
length; tuning its stair pitch to the result would not be a defensible repair.

Before a second known-answer run, renderer iteration 2 is frozen as follows.
Retain the finite-radius CSXCAD `Wire`, but subdivide every true Euclidean
centerline edge into support vertices no farther apart than
`lambda(6.5 GHz)/40`. Insert every support coordinate into its corresponding
Yee-grid axis and insert `coordinate +/- resolution` on all three axes. The
serialized centerline stays collinear and retains exact source endpoints,
Euclidean length, order, and 0.05 mm radius; only its mesh support is enriched.
This directly addresses the audited failure mode (only control-node mesh lines)
without replacing a straight physical wire by a longer taxicab conductor.

The second known-answer uses the new run ID
`day65-freeform-rotation-invariance-r2` and otherwise repeats the exact same
three geometries, two solvers, 1.5--3.5 GHz/201-point sweep, 1x openEMS mesh,
lambda/160 NEC2 control, and unchanged <=2% / <=1.5 dB / Pearson>=0.95 gates.
The first failed run remains immutable. Candidate re-verdict and the v2 hunt
remain blocked unless every r2 openEMS pair passes.

## Renderer iteration 3 amendment after r2 also failed

Run `day65-freeform-rotation-invariance-r2` also failed without releasing the
instrument. Its axis case retained a 2.220 GHz / -15.733 dB resonance, while
both 45-degree finite-radius `Wire` cases were again effectively absent: their
curves stayed near 0 dB and selected sweep-edge minima. Dense collinear support
vertices therefore do not make this installed CSXCAD/openEMS combination a
reliable oblique sub-cell wire instrument.

Before a third known-answer run, renderer iteration 3 is frozen as a solid
supercover tube. Along each true Euclidean arm centerline, place overlapping
axis-aligned PEC cubes with a fixed 0.5 mm side. Cube-center spacing is at most
0.25 mm, endpoints are included exactly, and every cube face is inserted into
the Yee grid. The feed-end cubes leave the frozen 0.6 mm feed gap open. The
union is a connected, orientation-neutral voxel surrogate centered on the
original line; it neither forces current through the longer Manhattan path nor
depends on a 1D primitive that r2 showed can disappear. The 0.5 mm FDTD width
is explicitly an instrument surrogate, not the 0.05 mm NEC2 wire radius, and
the eventual two-solver 5% frequency gate remains responsible for accepting or
rejecting that modeling difference.

The third known-answer uses run ID
`day65-freeform-rotation-invariance-r3`. It repeats the same three source
centerlines, both solvers, sweep, sample count, refinement, and the unchanged
<=2% / <=1.5 dB / Pearson>=0.95 release thresholds. R1 and r2 remain immutable;
candidate and hunt execution remain blocked unless every r3 openEMS pair
passes.

## Renderer iteration 4 amendment before any r3 solver run

The r3 supercover definition was rejected by a pre-run mesh-size audit, not by
observing a numerical antenna result. Candidate A is 472.676 mm long. At the
frozen 0.25 mm cube-center spacing it would require about 1,891 centers; putting
every independently varying cube face on each rectilinear Yee axis has a
multi-billion-cell worst case and cannot support the required 1x/2x candidate
instrument. No r3 solver run is executed and no r3 run ID is reused.

Renderer iteration 4 instead uses the installed CSXCAD finite-volume
`Cylinder` primitive, whose axis may have any orientation. Each existing
Euclidean centerline edge becomes one PEC cylinder with exact endpoints and a
fixed 0.25 mm FDTD surrogate radius. The 0.6 mm feed gap remains empty. The
radius is independent of refinement and is disclosed as distinct from NEC2's
0.05 mm thin-wire radius; the unchanged 5% cross-solver frequency gate judges
that modeling difference.

Inside the structure bounding box expanded by the cylinder radius, openEMS uses
a deterministic uniform Cartesian mesh of 0.5 mm at refinement 1x and 0.25 mm
at 2x, plus exact source centerline endpoints and the existing graded exterior.
This bounds a 40 mm candidate at roughly 0.5 million local cells at 1x and 4.2
million at 2x, while a finite cylinder cannot vanish between grid lines. The
meander, anchor, patch, generic-wire, NEC2, and their fixture outputs remain
untouched.

The next known-answer run ID is
`day65-freeform-rotation-invariance-r4`; the three source geometries, sweep,
solvers, refinement, and <=2% / <=1.5 dB / Pearson>=0.95 thresholds are still
unchanged. R1/r2 remain immutable, r3 remains explicitly unexecuted, and all
later work remains blocked unless every r4 openEMS pair passes.

## Instrument refinement r5 after the r4 1x direction error

Run `day65-freeform-rotation-invariance-r4` established that the finite solid
renderer no longer disappears: both oblique orientations produced deep
resonances at 2.110 GHz and agreed with each other at Pearson 0.999995. The 1x
Cartesian instrument was not rotationally converged, however; the axis case
resonated at 1.870 GHz, giving a 12.060302% axis-to-oblique difference. The r4
gate therefore failed and released nothing.

Before r5, the only change is openEMS refinement 2x, which changes the already
frozen local grid from 0.5 mm to 0.25 mm. The source centerlines, cylinder
endpoints, fixed 0.25 mm surrogate radius, feed, sweep, 201 samples, NEC2
lambda/160 control, and all <=2% / <=1.5 dB / Pearson>=0.95 release thresholds
remain identical. Run ID is `day65-freeform-rotation-invariance-r5`. If r5
fails, candidate re-verdict and the hunt remain blocked; the thresholds are not
relaxed.

## Rotation-fixture correction r6 after identifying the feed confound

R5 failed at 2x: the x-axis case was 2.260 GHz and both x-to-oblique cases
were 2.060 GHz, a 9.259259% difference. Before any further solver run, the
fixture audit identified that these were not rigid rotations of the complete
openEMS-fed structure. The lumped port is necessarily x-directed. Keeping its
0.6 mm x gap fixed while rotating arms from x into xy/xz changes the feed-arm
angle from 0 to 45 degrees, so the strong FDTD feed discontinuity was confounded
with renderer orientation.

R6 corrects only that known-answer geometry confound. The x-directed feed and
its endpoints remain byte-identical, and the arms are rigidly rotated about the
x feed axis. The three directions are y-axis `(0,1,0)`, yz-45 degrees
`(0,1/sqrt(2),1/sqrt(2))`, and z-axis `(0,0,1)`. All have the same 90-degree
feed-arm relation; the first and third test Cartesian-axis equivalence and the
middle tests a genuinely oblique out-of-plane cylinder. Length, radius,
cylinders, 2x grid, sweep, NEC2 control, and every <=2% / <=1.5 dB /
Pearson>=0.95 threshold remain unchanged.

Run ID is `day65-freeform-rotation-invariance-r6`. The original x/xy/xz r4/r5
results remain archived as diagnostics and are not reinterpreted as passes.
R6 is the sole corrected release gate and is frozen before execution; failure
still blocks candidate re-verdict and the v2 hunt.

## Instrument refinement r7 after the corrected r6 gate

R6 removed the feed-angle confound and verified exact y/z Cartesian symmetry:
both axis cases resonated at 2.190 GHz and their Pearson was 0.999983. The
yz-45 case was 2.130 GHz. Its 2.777778% frequency difference and about 0.899
Pearson failed the unchanged 2% and 0.95 thresholds (one depth pair also missed
1.5 dB by 0.063 dB). The corrected fixture therefore remains unreleased at 2x.

R7 changes only openEMS refinement from 2x to 4x, making the already frozen
local Cartesian step 0.125 mm. The finite cylinders and fixed 0.25 mm radius,
the y/yz-45/z rigid-rotation family, feed, sweep, 201 samples, NEC2 lambda/160,
and every release threshold remain unchanged. Run ID is
`day65-freeform-rotation-invariance-r7`. Failure still stops all later work;
runtime is recorded without reducing any frequency evidence.

## R7 timeout-only execution retry

The first r7 invocation produced no completed run: after 1,313 seconds a real
openEMS subprocess exceeded the adapter's generic 900-second per-solve timeout,
and `YAF_NO_FALLBACK=1` stopped execution before any six-curve summary was
written. No r7 numeric comparison was observed. Before retry, the adapter is
allowed a validated `openems_timeout_seconds` setting and preserves the strict
subprocess error rather than collapsing it into an analytical-fallback message.

Retry run ID is `day65-freeform-rotation-invariance-r7r2` and the timeout is
1,800 seconds per openEMS orientation. This changes execution capacity only:
the same r7 cylinders, 4x grid, corrected y/yz-45/z geometries, sweep, sample
count, NEC2 control, and all release thresholds remain byte-for-byte unchanged.
Later stages remain blocked unless r7r2 completes and passes.

## Constant-physical-duration instrument r8 after r7r2

R7r2 completed and failed: the y/z axes agreed exactly at 2.240 GHz /
-15.913568 dB, while yz-45 had no valid resonance and selected the 1.500 GHz
sweep edge at -2.546214 dB. The XML audit then found that every free-form mesh
used the same 40,000 maximum FDTD time steps. Under the Courant condition,
halving the 3D grid step approximately halves each time step; 4x therefore
simulated only about one quarter of the 1x physical duration. Spatial
refinement had been confounded with a shorter decay window.

R8 freezes a constant-duration correction before execution. It returns to the
r6 2x spatial grid (0.25 mm), where all orientations produced valid resonances,
and doubles the maximum time steps from 40,000 to 80,000. This keeps the nominal
physical integration duration aligned with the original 1x instrument. The
end criterion remains `1e-4`; early termination is still allowed only when the
same field-decay condition is met. Cylinders, fixed 0.25 mm radius, y/yz-45/z
geometry, feed, 201-point sweep, NEC2 lambda/160, and every <=2% / <=1.5 dB /
Pearson>=0.95 gate remain unchanged. Run ID is
`day65-freeform-rotation-invariance-r8`; all later work remains blocked unless
it passes.

## Spatial-and-temporal refinement r9 after r8

R8 completed with the longer physical decay window and reproduced r6: y/z
were 2.190 GHz, yz-45 was 2.130 GHz, the frequency difference remained
2.777778%, and Pearson remained about 0.90. Time-window truncation is therefore
not the cause of the corrected fixture's residual direction error.

R9 is the next clean convergence point: 4x spatial refinement (0.125 mm local
grid) with 160,000 maximum time steps, preserving the same nominal physical
duration as 1x/40,000 and 2x/80,000. The per-orientation process timeout is
3,600 seconds. The fixed-radius cylinders, y/yz-45/z source geometries, feed,
sweep, samples, NEC2 control, decay criterion, and every <=2% / <=1.5 dB /
Pearson>=0.95 threshold remain unchanged. Run ID is
`day65-freeform-rotation-invariance-r9`. No later work is authorized unless r9
completes and passes.

## R9 execution-resume amendment after external termination

The first r9 process produced no run directory, no archived evidence, and no
numeric curve or comparison output. Windows returned external-termination
status `0x40010004`; there was no openEMS/application crash event, resource
exhaustion event, surviving solver process, or memory pressure (about 37.7 GiB
remained free at inspection). This is therefore an unobserved execution
interruption, not an antenna result and not a failed release gate.

Before retry, r9 gains only crash-safe execution state. Each completed
orientation's NEC2 and openEMS curves is written atomically under the ignored
`runs/` draft area together with the exact r9 configuration hash. A restart
may reuse a completed orientation only when that hash and orientation match;
otherwise it stops instead of mixing instruments. The immutable six-curve run
and archive are still created only after all three orientations exist, and the
staging records are not manifest evidence by themselves. Geometry, 4x mesh,
160,000 steps, 3,600-second per-solve timeout, sweep, solver modes, and every
release threshold remain unchanged. The run ID remains
`day65-freeform-rotation-invariance-r9` because no run with that ID was ever
created.

## Resolved-radius Wire endpoint test r10 after r9

R9 completed and failed the unchanged gate. Its y/z axis curves were identical
at 2.240 GHz / -17.014241 dB. The yz-45 curve was 2.200 GHz / -11.759381 dB:
the 1.801802% frequency difference now passes, but the 5.254860 dB depth
difference and Pearson 0.883634 still fail. NEC2 remained invariant. Thus the
4x spatial frequency location is sufficiently converged for the 2% gate while
the openEMS feed-to-arm junction still changes the resonance shape by
orientation.

The official CSXCAD documentation defines `Wire` as a Curve with a radius, and
upstream `CSPrimWire::IsInside` tests both distance to each true line segment
and distance to every vertex. The vertex term makes a sphere-ended swept wire,
unlike r9's flat-ended finite Cylinder. This distinction matters at the two
points where the x-directed lumped feed meets y/yz/z arms. R2 does not test
this resolved form: it used the physical 0.05 mm radius on approximately
1.5 mm cells (radius/cell about 0.033), so both oblique wires vanished.

R10 replaces each arm's single r9 Cylinder with a single official CSXCAD Wire
following the same exact Euclidean endpoints. The FDTD surrogate radius stays
0.25 mm and the local grid stays 0.125 mm, so radius/cell is 2 and diameter is
four cells; the only intended variable is the sphere-ended connection. R10
retains r9's 4x grid, 160,000 maximum steps, 3,600-second timeout, crash-safe
orientation staging, y/yz-45/z source geometries, feed, 1.5--3.5 GHz / 201
point sweep, NEC2 lambda/160 control, and every <=2% / <=1.5 dB /
Pearson>=0.95 threshold. Run ID is
`day65-freeform-rotation-invariance-r10`. Candidate re-verdict and the v2 hunt
remain blocked unless all r10 openEMS pairs pass.

## Equal-interval local mesh r11 after the r10 audit

R10 completed and failed the unchanged gate. The openEMS y/z curves agreed at
2.210 GHz with Pearson 0.999695. The yz-45 curve was 2.190 GHz, so every
frequency pair passed at 0.909091%, but its depth differed by 5.496544 and
5.720992 dB and its Pearson values were 0.894197 and 0.893459. The
sphere-ended junction therefore did not by itself remove the shape error.

A pure XML audit, performed before r11, found a separate instrument confound.
The builder first made a global 0.125 mm lattice and then inserted every exact
wire vertex. Irrational rotated coordinates landed arbitrarily close to that
lattice. The resulting y/z grids had `[55,539,47]`/`[55,47,539]` lines,
1,336,392 cells, and a 0.033933 mm minimum cell; yz-45 had `[55,397,397]`
lines, 8,468,064 cells, and a 0.006151 mm minimum cell. Thus the Courant time
step and nominal physical duration differed by orientation despite the shared
refinement label.

R11 fixes only this mesh-construction defect. Within each radius-expanded
structure bounding box, the mandatory breakpoints are the two box faces and
the feed coordinates: feed start/stop on the port axis, and the feed center
plus/minus one target step on transverse axes. Each interval is divided into
`ceil(length / 0.125 mm)` equal cells. Consequently no cell exceeds the frozen
4x target step, and no interval may be shorter than half that step; this is a
pre-solver invariant. Non-feed Wire vertices are no longer forced onto mesh
planes because a resolved CSXCAD Wire is a finite-radius volumetric primitive.
The exterior remains the same geometrically graded mesh.

Run ID is `day65-freeform-rotation-invariance-r11`. The sphere-ended 0.25 mm
Wire, exact centerlines and feed, corrected y/yz-45/z family, 4x refinement,
160,000 maximum steps, 3,600-second timeout, 1.5--3.5 GHz / 201-point sweep,
NEC2 lambda/160 control, crash-safe staging, and every <=2% / <=1.5 dB /
Pearson>=0.95 release threshold remain unchanged. No candidate re-verdict or
v2 hunt is authorized unless all r11 pairs pass.

## Spatial refinement r12 after the corrected r11 instrument

R11 completed and failed the unchanged gate. Its y/z openEMS curves agreed at
2.140 GHz with Pearson 0.999976. The yz-45 curve was 2.190 GHz. Its two depth
differences, 1.175046 and 1.228765 dB, passed; its 2.309469% frequency
differences and Pearson 0.931858/0.931671 did not. All NEC2 pairs again passed.
The equal-interval audit measured local minima of 0.120--0.125 mm in every
orientation, so the former direction-dependent Courant runt is removed.

R12 is the next spatial convergence point. It changes only openEMS refinement
from 4x to 6x, giving a target local step of 0.083333 mm, and maximum time
steps from 160,000 to 240,000 so nominal physical duration remains constant.
The per-orientation timeout rises from 3,600 to 7,200 seconds solely as an
execution-capacity allowance. Run ID is
`day65-freeform-rotation-invariance-r12`.

The sphere-ended 0.25 mm Wire, exact centerlines and feed, equal-box/feed
interval meshing, corrected y/yz-45/z geometry family, 1.5--3.5 GHz / 201-point
sweep, NEC2 lambda/160 control, decay criterion, crash-safe staging, and every
<=2% / <=1.5 dB / Pearson>=0.95 release threshold remain unchanged. Later
work remains blocked unless all r12 openEMS pairs pass.

## Released-instrument execution for frozen candidates

R12 passed all rotation pairs. Its three openEMS resonances were all 2.210 GHz,
depth differences were at most 0.137231 dB, and Pearson was at least 0.999728.
The released free-form instrument is therefore the r12 sphere-ended Wire at
6x equal-interval mesh, 240,000 maximum steps, and unchanged `1e-4` decay.
No coarser setting is authorized for a cross-solver confirmation claim.

Before re-verdict, candidate A receives the already preregistered high-band
self-convergence series at 1x and 2x. If their valid 5.8 GHz resonance shift is
at most 3%, the self-check passes; if not, the series deterministically adds 4x
and then 6x until an adjacent pair passes or the sequence is exhausted. Missing
valid resonance at either adjacent level is a failed convergence comparison,
not zero shift. Run IDs are
`day65-repair-openems-convergence-top1-{1,2,4,6}x`; only required levels run.
Every curve keeps the full 1.5--6.5 GHz / 251-point sweep.

The frozen candidates remain exactly the committed Day 6 selection: A is
`day6-freeform-dual-gp-s202` step 193 and B is the same run step 172. Their
final repaired runs are `day65-repair-crosscheck-top1` and
`day65-repair-crosscheck-top2`. Each runs one new 6x/240k openEMS curve with a
21,600-second process timeout. The unchanged lambda/160 NEC2 curve is copied
byte-for-byte from `day6-freeform-final-crosscheck-top1/top2`; the new run
records that source ID and SHA-256 rather than pretending to rerun it.

The v2.1 gates are unchanged. Each band independently requires valid internal
minima no shallower than -6 dB in both solvers and frequency difference no
greater than 5%. The preregistered whole 1.5--6.5 GHz Pearson threshold remains
0.8 and is evaluated descriptively even when one band fails. A per-band
`CONFIRMED` label additionally requires that same whole-sweep Pearson gate;
the dual-band label still requires both bands. This is stricter than inferring
agreement from frequency alone and introduces no new threshold. Candidate A's
known NEC2 high-band depth of -5.147263 dB precludes a dual-band confirmation;
candidate B is nevertheless reported in full without replacement.
