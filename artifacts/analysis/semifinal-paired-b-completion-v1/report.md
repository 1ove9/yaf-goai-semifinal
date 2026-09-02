# B-parent conditional-completion analysis

- Study status: `complete`
- Scientific endpoint: `b_completion_pair_validity_without_effect_crossing`
- Verdict ceiling: `insufficient_evidence`

| Parent | Agent | Seed | Status | Accepted | H1 | H2 |
|---|---|---:|---|---:|---:|---:|
| p01 | random-b-completion | 101 | `completed` | 300 | 1 | 0 |
| p01 | random-b-completion | 202 | `completed` | 300 | 0 | 0 |
| p01 | random-b-completion | 303 | `completed` | 300 | 0 | 0 |
| p01 | random-b-completion | 404 | `completed` | 300 | 0 | 0 |
| p01 | random-b-completion | 505 | `completed` | 300 | 1 | 0 |
| p01 | es-b-completion | 101 | `completed` | 300 | 16 | 0 |
| p01 | es-b-completion | 202 | `completed` | 300 | 3 | 0 |
| p01 | es-b-completion | 303 | `completed` | 300 | 97 | 0 |
| p01 | es-b-completion | 404 | `completed` | 300 | 83 | 0 |
| p01 | es-b-completion | 505 | `completed` | 300 | 66 | 0 |
| p02 | random-b-completion | 101 | `completed` | 300 | 1 | 0 |
| p02 | random-b-completion | 202 | `completed` | 300 | 0 | 0 |
| p02 | random-b-completion | 303 | `completed` | 300 | 0 | 0 |
| p02 | random-b-completion | 404 | `completed` | 300 | 1 | 0 |
| p02 | random-b-completion | 505 | `completed` | 300 | 1 | 0 |
| p02 | es-b-completion | 101 | `completed` | 300 | 82 | 0 |
| p02 | es-b-completion | 202 | `completed` | 300 | 56 | 0 |
| p02 | es-b-completion | 303 | `completed` | 300 | 81 | 0 |
| p02 | es-b-completion | 404 | `completed` | 300 | 125 | 0 |
| p02 | es-b-completion | 505 | `completed` | 300 | 88 | 0 |

- H1 accepted records: 702
- H2 accepted records: 0

## Parent-by-agent seed support

| Parent | Agent | H1 seeds | H2 seeds | Interpretation |
|---|---|---:|---:|---|
| p01 | random-b-completion | 2/5 | 0/5 | descriptive support in 2/5 seeds |
| p01 | es-b-completion | 5/5 | 0/5 | descriptive support in 5/5 seeds |
| p02 | random-b-completion | 3/5 | 0/5 | descriptive support in 3/5 seeds |
| p02 | es-b-completion | 5/5 | 0/5 | descriptive support in 5/5 seeds |

## Descriptive selected hypothesis

- Source: `semifinal-paired-b-completion-p01-es-s303` step 265, proposal 265
- Parent/agent/seed: p01 / es-b-completion / 303
- H1/H2: True / False
- Worst reflected-power fraction: 0.23010531242953516
- Pair hash: `59a7e7df8fe7b8c3e6a07333e84ef12099886c5971a9815891ef63e1d041f259`
- Hardware hash: `52cc0dfe93a241643f2089bbd67f4d674edede0dfd38617983d9841a530a302b`
- Proposal: `{"hardware":{"box_size_um":40000,"feed_gap_ratio_ppm":49001,"max_total_wire_length_um":100000,"mechanism_version":"ideal-symmetric-telescopic-PEC-meander-v1","quantization_version":"integer-um-ppm-v1","schema_version":1,"terminal_ratio_ppm":0,"turn_count":3,"wire_radius_um":50},"proposer":"es-b-completion","state_a":{"span_ratio_ppm":999881,"state":"A","total_wire_length_um":70775},"state_b":{"span_ratio_ppm":785552,"state":"B","total_wire_length_um":26090}}`

Random is the comparison baseline. This is an NEC2-only descriptive outcome; independent-solver confirmation requires a separate preregistration.
