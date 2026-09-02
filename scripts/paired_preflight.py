"""Run the sole authorized 20-pair semifinal NEC2 timing preflight."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from yaf_ai.exploration.paired_preflight import run_paired_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    os.environ["YAF_NO_FALLBACK"] = "1"
    summary = asyncio.run(run_paired_preflight(args.repo_root.resolve()))
    print(f"run_id={summary.run_id}")
    print(f"result_status={summary.result_status}")
    print(f"legal_pairs={summary.legal_pair_count}/{summary.input_pair_count}")
    for row in summary.timing_rows:
        print(
            f"pair_{row.step_index:02d} hash={row.pair_hash} "
            f"elapsed_s={row.elapsed_seconds:.9f}"
        )
    if summary.result_status != "completed":
        print(f"failure={summary.failure_message}")
        return 1
    print(f"p95_method={summary.p95_method}")
    print(f"t_pair_p95_s={summary.t_pair_p95_seconds:.9f}")
    print(f"raw_budget={summary.raw_budget}")
    print(f"budget={summary.budget}")
    print(f"classification={summary.budget_classification}")
    print(f"verdict_ceiling={summary.verdict_ceiling}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
