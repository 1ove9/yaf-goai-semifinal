# Paired-state computational hypothesis card

> Status: `NEC2-only / insufficient_evidence`. This is not YAF-M1, a confirmed
> invention, a manufacturable antenna, or a continuous-motion proof.

- Source: `semifinal-paired-es-warm-s101`, step `213`, proposal `658`
- Hardware hash: `b6f72349504b6994a10ff9d32ffb7059424073fb25bc2900860f7e1348b9340c`
- Pair hash: `8a4ad18c710ec185728fd5bff0e6f16461aea29362024893e1bb6ddd3dcc73ca`
- Mechanism: `ideal-symmetric-telescopic-PEC-meander-v1`
- Box / wire radius: `40.0 mm` / `0.050 mm`
- Turns / feed-gap ppm / terminal ppm: `3` / `58388` / `87831`
- Physical feed gap: `2.335520 mm`
- Minimum pitch / height: `3.512815 mm` / `0.405504 mm`
- Maximum adjacent trajectory movement: `0.261734 mm`

| State | Wire length (mm) | Span ratio | Selected GHz | S11 (dB) | Index | Internal valid | State FoM | Geometry SHA-256 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 70.731 | 0.998536 | 2.4930 | -6.874 | 93 | True | 0.794583 | 4d8c585c7e4112d1d8aad9d8c33b55642549008cec6649075a75ffa4a4b15b55 |
| B | 26.057 | 0.760951 | 5.7355 | -16.090 | 7 | True | 0.975398 | 84566f8b6ab538d6ff1ae730b2ecd74f445fc127f877f8edb1a53530e509c33e |

The frozen valid-index interval is 3..97 inclusive. State A index 93 and state B
index 7 are each four bins inside the nearest validity boundary and are therefore
valid but edge-adjacent observations.

The 21-point discrete trajectory passed. Minimum clearance was 0.202752 mm, only 2.752 um above the frozen 0.200 mm boundary.

The candidate reduced the worse-state reflected-power fraction by 4.674341% versus the frozen manual comparator, below the preregistered 10.0% requirement.

Manual-comparator limitation: 5,184 pairs were assembled, 756 were scored, and 0 were valid. Its selected state-A minimum was index 100 (the sweep endpoint), so this comparator was nonvalid and is not claimed to be the strongest possible baseline.

Independent openEMS candidate confirmation was not authorized because the 5.8 GHz rod
instrument was `NOT RELEASED` (`repair_not_confirmed`); the repaired probes existed but carried zero
parseable samples in the frozen diagnostic run.

Model exclusions: sleeve overlap, contact resistance, actuator volume, mechanical stress,
conductor loss, tolerance robustness, and continuous-path mechanics.
