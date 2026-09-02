# Day 5 wire-v6 preregistration

Status: frozen before the first `day5-wire-v6` numeric run.

## Scientific question

Can GP search find a genuinely resonant meander dipole in the 2.40--2.50 GHz
target band, inside the existing 30 x 30 mm box, and can that result satisfy the
unchanged `day4-wideband-resonance-v2.1` native-solver agreement rules?

The `wire-realized-gain-v2` score, the zero efficiency weight, and every v2.1
threshold remain unchanged. Only the proposal-space version changes.

## Electrical-length audit and proposal space

At 2.45 GHz, `c / (2 f)` is 61.182134 mm. A deterministic scan of all v1 bound
corners (integer turns 2--6 and both endpoints of the other four dimensions)
found 70 valid and 10 invalid cases. Valid total centerline lengths ranged from
28.700000 to 246.000000 mm. Thus the earlier informal description that v1 was
limited to about 2.6 turns was inaccurate: the actual problem is an indirect,
strongly coupled length coordinate plus invalid regions, not an absolute lack of
61 mm designs.

`meander-dipole-v2-5d` uses one source of truth for both GP and Random:

| Parameter | Lower | Upper | Meaning |
|---|---:|---:|---|
| `turns` | 2 | 6 | rounded integer meander turns |
| `span_ratio` | 0.76 | 1.00 | horizontal half-box utilization |
| `total_length_m` | 0.050 | 0.080 | requested full centerline length |
| `feed_gap_ratio` | 0.02 | 0.06 | feed gap relative to the 30 mm box |
| `terminal_ratio` | 0.00 | 1.00 | final horizontal fraction |

The generator solves the meander height from the requested total length. An
exhaustive boundary audit of 80 cases found 80 valid and zero invalid: realized
length 50.000000--80.000000 mm, minimum pitch 1.500000 mm, and full vertical
extent 1.818182--21.533333 mm. The 61.182134 mm half-wave estimate is therefore
strictly inside the direct length interval.

## Frozen batch and GP policy

The matrix is `agents={gp, random}` x `seeds={101,202,303,404,505}` with budget
400, plus the unchanged one-evaluation box-straight classic reference. The
oracle is real NEC2 with adaptive lambda/20 segmentation. A local benchmark of
one GP suggestion after 400 stored five-dimensional observations took 0.033720
seconds. This is below the preregistered 5 second threshold, so all 400
observations are retained and no sliding window is enabled.

## Frozen top-2 selection

Selection examines every accepted GP evaluation in the archived batch logs and
uses no cross-check result. A target-band-valid candidate has `min_s11_db <=
-6.0`, and its minimum index is at least 3 and less than `frequency_points - 3`.
Unique geometry hashes are sorted by this exact key:

1. target-band-valid candidates before invalid candidates;
2. higher frozen exploration score;
3. lexicographically smaller source run ID;
4. lower source step index.

The first two are cross-checked. No result-driven substitution is permitted.

## Frozen convergence and cross-check plan

For selected top-1, NEC2 is run on the unchanged 1.5--3.5 GHz, 201-point sweep
at lambda/20, lambda/40, and lambda/80. The reference is openEMS at refinement
2x. Let `gap(d)` be the relative resonance-frequency gap to that reference.
The inherited attribution thresholds are applied mechanically:

- monotonically narrowing and `gap(80) / gap(20) < 0.5`:
  `instrument_boundary`;
- `gap(80) / gap(20) >= 0.8`: `genuine_anomaly`;
- otherwise: `inconclusive_needs_finer_segmentation`, with a linear fit against
  inverse segmentation density used to estimate the density for a 5% gap.

openEMS is self-checked at its default and 2x mesh. A resonance-frequency shift
of at most 3% is recorded as internally converged; otherwise the openEMS side is
reported as mesh-sensitive. Both final top-2 checks nevertheless use the frozen
lambda/80 NEC2 and 2x openEMS settings and retain the unchanged v2.1 gates:
interior minimum, depth at most -6 dB, frequency gap at most 5%, and Pearson
correlation at least 0.8.

