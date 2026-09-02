# Solver-free representation ablation

- Study: `semifinal-paired-feasibility-stratified-exact-v2`
- Status: `completed`
- Endpoint: `coverage_improved_all_turns`
- Solver calls: `0`

| Turn | Seed | Legacy valid | Conditional valid | Coverage pass |
|---:|---:|---:|---:|:---:|
| 3 | 101 | 4844/10000 | 10000/10000 | yes |
| 3 | 202 | 4818/10000 | 10000/10000 | yes |
| 3 | 303 | 4798/10000 | 10000/10000 | yes |
| 3 | 404 | 4870/10000 | 10000/10000 | yes |
| 3 | 505 | 4895/10000 | 10000/10000 | yes |
| 4 | 101 | 4140/10000 | 10000/10000 | yes |
| 4 | 202 | 4129/10000 | 10000/10000 | yes |
| 4 | 303 | 4071/10000 | 10000/10000 | yes |
| 4 | 404 | 4163/10000 | 10000/10000 | yes |
| 4 | 505 | 4115/10000 | 10000/10000 | yes |
| 5 | 101 | 3611/10000 | 10000/10000 | yes |
| 5 | 202 | 3535/10000 | 10000/10000 | yes |
| 5 | 303 | 3514/10000 | 10000/10000 | yes |
| 5 | 404 | 3590/10000 | 10000/10000 | yes |
| 5 | 505 | 3594/10000 | 10000/10000 | yes |
| 6 | 101 | 3017/10000 | 10000/10000 | yes |
| 6 | 202 | 3061/10000 | 10000/10000 | yes |
| 6 | 303 | 3082/10000 | 10000/10000 | yes |
| 6 | 404 | 2956/10000 | 10000/10000 | yes |
| 6 | 505 | 2844/10000 | 10000/10000 | yes |

## Turn-level endpoint

- Turn 3: 5/5 passing seeds (101, 202, 303, 404, 505); reproducibly improved = `true`.
- Turn 4: 5/5 passing seeds (101, 202, 303, 404, 505); reproducibly improved = `true`.
- Turn 5: 5/5 passing seeds (101, 202, 303, 404, 505); reproducibly improved = `true`.
- Turn 6: 5/5 passing seeds (101, 202, 303, 404, 505); reproducibly improved = `true`.

This is a solver-free representation endpoint. It contains no antenna score and does not select or remove a turn from Stage B.
