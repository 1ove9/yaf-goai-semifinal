# Patch openEMS mesh-count execution note

Status: frozen before either diagnostic XML is built and before any new solver run.

## Scope

The only geometry is the frozen `day2-wifi24-gp-s505` best-design air variant used by
`day5-patch-final`. Its source run, design index, step index, geometry hash, air
transformation, 4.098041023--6.830068372 GHz sweep, and 51-point sampling remain
unchanged. The diagnostic compares `openems_mesh_refinement=1.0` and `2.0`.

This addendum audits only whether the archived 2x openEMS self-convergence claim had a
materially different mesh. It does not reopen the final `DIVERGENT` decision: NEC2 grid
44 still misses both the 5% resonance and 0.8 Pearson gates even if openEMS is treated
as the reference.

## Frozen measurements

Build each simulation XML without invoking the solver. Parse its `RectilinearGrid` and
record:

- the number of unique grid lines on x, y, and z;
- total Yee cells `(Nx - 1) * (Ny - 1) * (Nz - 1)`;
- the minimum and maximum adjacent cell size on each axis; and
- the SHA-256 of the XML, so equality or inequality is auditable.

The interpretation uses the ratio `cells_2x / cells_1x`:

- ratio greater than or equal to 3.0: `effective`; the archived zero-bin resonance
  movement establishes the openEMS self-convergence claim and no solver rerun is
  permitted;
- ratio greater than or equal to 1.2 but below 3.0: `partially_supported`; downgrade
  the claim and perform the conditional repair and one real 2x recheck below;
- ratio below 1.2: `ineffective`; retract the claim as
  `self_convergence_not_established` and perform the conditional repair and recheck.

Boundary values belong to the higher category: exactly 1.2 is partially supported and
exactly 3.0 is effective.

## Conditional repair and one-shot recheck

Only a `partially_supported` or `ineffective` result authorizes a minimal change that
propagates `openems_mesh_refinement` through the parametric patch XML path. The
refinement=1.0 XML must remain byte-for-byte unchanged. After the fix, rebuild the two
XMLs, archive their counts, and run the repaired 2x air variant exactly once with the
original sweep. Record wall time and resonance movement against the archived 1x curve.

Movement at or below 3% restores the self-convergence claim with mesh evidence.
Movement above 3% leaves it retracted and adds an uncertainty footnote to the new
addendum only; historical run, analysis, and manifest entries are never modified.

All generated counts, XML-derived hashes, conditional-run logs, and conclusions go to
new evidence paths. Existing Day 2/3/4/5 patch evidence remains byte-identical.
