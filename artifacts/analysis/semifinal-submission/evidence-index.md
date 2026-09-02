# Semifinal evidence index

| Claim | Run ID / source | Step | Commit | Digest / artifact |
| --- | --- | --- | --- | --- |
| Historical static Day 6 study ended insufficient_evidence | artifacts/analysis/day6-freeform/report.md + artifacts/analysis/day6-freeform/summary.json | committed blobs | acbf4736b8755b682d215e16fe479ffff534360d | report=07426556777d842bd71489a4e866f6a5487714a95e0f10b3ec52f137aac95d00; summary=28def8a7b5a204e7da394f458ab6bd6e027f124f0da025571065c904ef1a4df1 |
| Manual comparator: 5,184 assembled / 756 scored / 0 valid | semifinal-paired-manual-baseline | selected step 288; A index 100 | 906835eceeae2e48a652e2b7fa891fd3e8461440 | log=838fd4d77e6fe15ad7bd7625d95d6a8071a96cd6c1e2483dcae77824a80420e4; summary=a089fa75ac3891ea7895b86962574aefda778c9a2d8728d1f29c2db7027cb133 |
| 9-cell paired search historical source manifest | semifinal-paired-{random,es-cold,es-warm}-s{101,202,303} | all accepted steps | a19684b5449774db82b21907cc11c7874287f838 | 6de538d4ec44931eda14cd4ce1828b2962176c8af500106f48bb0fbba331ffcb |
| Selected ES source curve bytes | semifinal-paired-es-warm-s101 | 213 | a19684b5449774db82b21907cc11c7874287f838 | log=af5b158d487577d7a07f26186ff66222b34abe05e36bd58596849dc4e3ff6c65; summary=52cd3ad16c3db5b2f3d98ab2bf394e69d4f6af0381d595d88edd3de3f98e25b7 |
| Selected Random source curve bytes | semifinal-paired-random-s202 | 130 | a19684b5449774db82b21907cc11c7874287f838 | log=6d314da8045b620f8303b1335921d1d770d3cac6a5bff1e91fceacb6a6a0626e; summary=2e9aff581abb264d5a0a7babe0cc48ba0bf61e19c6888051c3d7bfb175ac8bd9 |
| Frozen candidate selection and 4.674% effect-gate result | artifacts/analysis/semifinal-paired-agent-batch/frozen_candidates.json | top-es / top-random / manual-baseline | 4a8222eb7528a24acaa5879e7afa2398f0413740 | 0e814e2cc85ae0fe361c91a4d7338ae2175369b494eb49cdef8bd165338695d5 |
| Thin-box 5.8 GHz anchor not released | semifinal-wifi58-meander-renderer-anchor-r3-combined | all seven steps | 6bee5eeac5642386f7015bf496e8a592424cb75c | log=0e9da50876fa679870160ba9349a8391c18d7917355d7cef50177899bb967a9f; summary=d5ac661dc0251d0e7dcecf7a88d967a2c510e568e3338a45c5e84399254f67a9 |
| Rod repair gate not confirmed; no science ladder | semifinal-wifi58-rod-renderer-anchor-r2-combined | A/B diagnostics only | ba53596f8191ec1a820ae7470349c89091a5bbe8 | log=b3dd5214aae9c0f48f1051514109207bbb86c9f5cc3b832afc6180da62347079; summary=6981fb426ea700a31aa4b716c845bb7b6b6a99a30a41e1013b090eed89dcf6f1 |
| Full archive integrity 219/219 | artifacts/runs/manifest.json | all entries | ba53596f8191ec1a820ae7470349c89091a5bbe8 | cd6d8bd106ae6b7da478c836913a84511f1a484e55641e07f21cbe17013dfb8c |

The paired candidate freeze at `4a8222e` binds the frozen-candidates document only.
The historical 218-entry source manifest is separately pinned at `a19684b` by its
canonical content digest. The current 219-entry manifest is an append-safe successor:
every pinned canonical JSON entry must remain identical after canonical JSON serialization,
every pinned source file must remain byte-identical, and only unique entries may be
appended.
Day 6 report/summary digests above are hashes of committed Git blobs, not CRLF working-tree views.
