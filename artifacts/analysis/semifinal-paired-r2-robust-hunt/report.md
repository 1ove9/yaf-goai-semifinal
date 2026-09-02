# Robust Hunt R2: bounded parent-return ES gate reproduction

**Study status:** `complete`
**Verdict ceiling:** `insufficient_evidence`
**Scientific endpoint:** `no_gate_crossing_observed_under_frozen_r2`
**Passing seeds:** 0/5
**Seeds with any valid pair:** 4/5

No gate crossing was observed under the frozen parent, global bounds, algorithm, budget, and five seeds. This bounded result is not a topology or physics ceiling.

## Five-seed matrix

| Seed | Status | Source status | Attempts | Accepted | Valid | Rejected | Best valid L | Pass | Restarts |
|---:|---|---|---:|---:|---:|---:|---:|---|---:|
| 101 | `completed` | `completed` | 1755 | 400 | 1 | 1355 | 0.223616185488 | false | 5 |
| 202 | `completed` | `completed` | 1631 | 400 | 0 | 1231 | -- | false | 5 |
| 303 | `completed` | `completed` | 1691 | 400 | 1 | 1291 | 0.219344385016 | false | 5 |
| 404 | `completed` | `completed` | 1617 | 400 | 1 | 1217 | 0.223889714017 | false | 5 |
| 505 | `completed` | `completed` | 1619 | 400 | 1 | 1219 | 0.241579302545 | false | 5 |

## Per-seed audit diagnostics

### Seed 101

- Execution/source status: `completed` / `completed`.
- Exception: `None` — None.
- Source SHA-256: log=`7b18a9236293d000235df273c7040a9484e6318ab655435c07fbb13f4b3e05cc`, summary=`5f3189474c231cb5bf2faee74b0ea55e04febbfc3cb55a6ca792528b2126d656`.
- Best valid record: run=semifinal-paired-r2-es-warm-s101, step=354, proposal=1616, pair=e017e7dfb7c2880f5b51b30c508b8afa74353841ec467db43c24d80888ca8fcb, hardware=1219b67e0c2b47768557fadd01da63992b17319da618b0d5341c25d8dfba0a5d, state_a=ffa0c3d755b6eeb0710876a3afe1295642a161063bc5f4a3ef79f894318786a1, state_b=15544deaf7fc250e7e0538dfe99467f0464390aee08e4528018033518f386274, L=0.22361618548820708.
- Gate-crossing witness: --.
- No-valid diagnostic top: --.
- Accepted turn counts: 3:385, 4:15, 5:0, 6:0 (total=400).
- Effective-pool turn counts: 3:1, 4:0, 5:0, 6:0 (total=1).
- Rejection reasons: paired geometry contains a short segment: 1355.
- Short-segment rejection count: 1355.
- Boundary pool: `valid`; denominator=1.

| Coordinate | Lower 1% | Upper 1% | Either | Fraction |
|---|---:|---:|---:|---:|
| `feed_gap_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `terminal_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `state_a_total_wire_length_um` | 0 | 0 | 0 | 0.000000 |
| `state_a_span_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `state_b_total_wire_length_um` | 0 | 0 | 0 | 0.000000 |
| `state_b_span_ratio_ppm` | 0 | 0 | 0 | 0.000000 |

### Seed 202

- Execution/source status: `completed` / `completed`.
- Exception: `None` — None.
- Source SHA-256: log=`c819748e495a3f28c9dd499b4bbf4757e357b737e0d0be572c3b9349c715e909`, summary=`7f07539b49f897c39616f6ab5bc187b75d4dc5a2d68b8fe65736a2d8ac8afc56`.
- Best valid record: --.
- Gate-crossing witness: --.
- No-valid diagnostic top: run=semifinal-paired-r2-es-warm-s202, step=352, proposal=1452, pair=0a13777b3ae9429f6eaa87f6c0ccf814f6cecc82c9327c3c0d02016f411b2182, hardware=9d07c912c389ad0b95192e97a4b908d665b5099380e468e50b7d98555e65ada3, state_a=9c574952287b52734176253696930490de88d32c1ad08835137efd11c950403a, state_b=4287c8d0298d709f1769b5388356b36eda0b59309983d170861323425e785408, L=0.19394650238581257.
- Accepted turn counts: 3:385, 4:15, 5:0, 6:0 (total=400).
- Effective-pool turn counts: 3:385, 4:15, 5:0, 6:0 (total=400).
- Rejection reasons: paired geometry contains a short segment: 1231.
- Short-segment rejection count: 1231.
- Boundary pool: `accepted`; denominator=400.

| Coordinate | Lower 1% | Upper 1% | Either | Fraction |
|---|---:|---:|---:|---:|
| `feed_gap_ratio_ppm` | 0 | 29 | 29 | 0.072500 |
| `terminal_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `state_a_total_wire_length_um` | 0 | 0 | 0 | 0.000000 |
| `state_a_span_ratio_ppm` | 0 | 45 | 45 | 0.112500 |
| `state_b_total_wire_length_um` | 0 | 0 | 0 | 0.000000 |
| `state_b_span_ratio_ppm` | 46 | 0 | 46 | 0.115000 |

### Seed 303

- Execution/source status: `completed` / `completed`.
- Exception: `None` — None.
- Source SHA-256: log=`814e3ee02e5db89512d6c6c3d7b74626f91c0f91e108b568c54937002b649c36`, summary=`62cdd1dea0785fc4f9bd72922680ea7e3658e99862cea42b52aa44fcb24249b8`.
- Best valid record: run=semifinal-paired-r2-es-warm-s303, step=42, proposal=143, pair=adec5a154a383687a121c2a5e671f48425451fdb32e5e511bc9adac7136473b4, hardware=459567c4c934f70b24721421a5804326b47a8734c4b3383732f420bf8f43d35c, state_a=35543f0deba723fe2e801835246a70c02071290b5e91f215eb69fc90d3164383, state_b=53617208affe3f6f98bc231ee211ea54f8ac110f6b85b8b47577581782a8a4d8, L=0.21934438501629624.
- Gate-crossing witness: --.
- No-valid diagnostic top: --.
- Accepted turn counts: 3:384, 4:15, 5:1, 6:0 (total=400).
- Effective-pool turn counts: 3:1, 4:0, 5:0, 6:0 (total=1).
- Rejection reasons: paired geometry contains a short segment: 1291.
- Short-segment rejection count: 1291.
- Boundary pool: `valid`; denominator=1.

| Coordinate | Lower 1% | Upper 1% | Either | Fraction |
|---|---:|---:|---:|---:|
| `feed_gap_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `terminal_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `state_a_total_wire_length_um` | 0 | 0 | 0 | 0.000000 |
| `state_a_span_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `state_b_total_wire_length_um` | 0 | 0 | 0 | 0.000000 |
| `state_b_span_ratio_ppm` | 1 | 0 | 1 | 1.000000 |

### Seed 404

- Execution/source status: `completed` / `completed`.
- Exception: `None` — None.
- Source SHA-256: log=`1779b154e477d282674f2e44f94203bdc4d7f27e34d2c64cdf59b349037a80db`, summary=`53d4fd0022be417bfc119bb5ab67d47ad0f260f009b2c5cee55b4447ba30e32f`.
- Best valid record: run=semifinal-paired-r2-es-warm-s404, step=371, proposal=1510, pair=8a7c9c6605fe9750f48e518292bbb4c2071602575e846259283292353d0c2e33, hardware=adccddea8d7732ebb0cd5d8cea3291fdfc99237c733d61bdaac0ca10229dae75, state_a=e804f9c1a9fc9f28c72c2fd0db7dc43f3c78e6f09cb2b68d608e30db995021d4, state_b=9b0825288a6edede515f36b62fd6baf9b8e7ca82a4b5a9c1e3e3e9e6b57c6c26, L=0.22388971401747385.
- Gate-crossing witness: --.
- No-valid diagnostic top: --.
- Accepted turn counts: 3:389, 4:11, 5:0, 6:0 (total=400).
- Effective-pool turn counts: 3:1, 4:0, 5:0, 6:0 (total=1).
- Rejection reasons: paired geometry contains a short segment: 1217.
- Short-segment rejection count: 1217.
- Boundary pool: `valid`; denominator=1.

| Coordinate | Lower 1% | Upper 1% | Either | Fraction |
|---|---:|---:|---:|---:|
| `feed_gap_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `terminal_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `state_a_total_wire_length_um` | 0 | 0 | 0 | 0.000000 |
| `state_a_span_ratio_ppm` | 0 | 1 | 1 | 1.000000 |
| `state_b_total_wire_length_um` | 0 | 0 | 0 | 0.000000 |
| `state_b_span_ratio_ppm` | 0 | 0 | 0 | 0.000000 |

### Seed 505

- Execution/source status: `completed` / `completed`.
- Exception: `None` — None.
- Source SHA-256: log=`ca126577c41a5650fcb01c5ecaf38203f1b125aeb20da6324b7804bfc1c171fb`, summary=`68b6b2d903dcb5194befd6dd21d0318f036e17abea345cf42b525ef5b20f606f`.
- Best valid record: run=semifinal-paired-r2-es-warm-s505, step=372, proposal=1508, pair=063f0b44e10751c2e6924b86076fc2b52f1fed45db5a337b8519259d5a63ce0e, hardware=b4b1a9f5347d744abbf18722e74a8a2a61f1806da24ac0226b09a4658d327a45, state_a=b52ec7d2e991ab0186b9f9218e19ab48e6d4e8afa945739802719157afc8cf62, state_b=bb8e0f5c56a5a56ea1775d7ad973390c375bb762f5ce4d21f659d42f914b9e0c, L=0.24157930254508839.
- Gate-crossing witness: --.
- No-valid diagnostic top: --.
- Accepted turn counts: 3:385, 4:15, 5:0, 6:0 (total=400).
- Effective-pool turn counts: 3:1, 4:0, 5:0, 6:0 (total=1).
- Rejection reasons: paired geometry contains a short segment: 1219.
- Short-segment rejection count: 1219.
- Boundary pool: `valid`; denominator=1.

| Coordinate | Lower 1% | Upper 1% | Either | Fraction |
|---|---:|---:|---:|---:|
| `feed_gap_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `terminal_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `state_a_total_wire_length_um` | 0 | 0 | 0 | 0.000000 |
| `state_a_span_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `state_b_total_wire_length_um` | 0 | 0 | 0 | 0.000000 |
| `state_b_span_ratio_ppm` | 0 | 0 | 0 | 0.000000 |


## Pre-R2 archived diagnostic

The frozen warm-s101 source contains 300 accepted pairs, 48 valid pairs, and best valid L=0.20541677746768625. It is diagnostic only and is excluded from R2 pass counts.
Accepted turn counts: 3:297, 4:3, 5:0, 6:0 (total=300).
Effective turn counts: 3:48, 4:0, 5:0, 6:0 (total=48).
Rejection reasons: paired geometry contains a short segment: 536.
Best valid source: run=semifinal-paired-es-warm-s101, step=213, proposal=658, pair=8a4ad18c710ec185728fd5bff0e6f16461aea29362024893e1bb6ddd3dcc73ca, hardware=b6f72349504b6994a10ff9d32ffb7059424073fb25bc2900860f7e1348b9340c, state_a=4d8c585c7e4112d1d8aad9d8c33b55642549008cec6649075a75ffa4a4b15b55, state_b=84566f8b6ab538d6ff1ae730b2ecd74f445fc127f877f8edb1a53530e509c33e, L=0.20541677746768625.

| Coordinate | Lower 1% | Upper 1% | Either | Fraction |
|---|---:|---:|---:|---:|
| `feed_gap_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `terminal_ratio_ppm` | 0 | 0 | 0 | 0.000000 |
| `state_a_total_wire_length_um` | 0 | 0 | 0 | 0.000000 |
| `state_a_span_ratio_ppm` | 0 | 25 | 25 | 0.520833 |
| `state_b_total_wire_length_um` | 0 | 0 | 0 | 0.000000 |
| `state_b_span_ratio_ppm` | 42 | 0 | 42 | 0.875000 |

## Scope boundary

R2 uses the unchanged NEC2 scoring instrument and does not authorize openEMS. It cannot produce `CONFIRMED`, `YAF-M1`, a manufacturable-antenna claim, or a robust physical claim. Full source rows, hashes, turn distributions, rejection counts, and six boundary diagnostics are in `appendix.json`.
