"""Run the frozen 864-sweep manual reconfigurable NEC2 baseline."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from yaf_ai.exploration.paired_baseline import run_manual_baseline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    os.environ["YAF_NO_FALLBACK"] = "1"
    summary = asyncio.run(run_manual_baseline(args.repo_root.resolve()))
    print(f"run_id={summary.run_id}")
    print(f"result_status={summary.result_status}")
    print(f"single_state_total={summary.single_state_total}")
    print(f"single_state_rejected={summary.single_state_rejected}")
    print(f"nec2_successes={summary.nec2_successes}")
    print(f"solver_mode_counts={summary.solver_mode_counts}")
    print(f"pair_total={summary.pair_total}")
    print(f"curve_incomplete_pairs={summary.curve_incomplete_pairs}")
    print(f"trajectory_invalid_pairs={summary.trajectory_invalid_pairs}")
    print(f"scored_pairs={summary.scored_pairs}")
    print(f"valid_pair_count={summary.valid_pair_count}")
    print(f"warm_parent_pair_hash={summary.warm_parent_pair_hash}")
    print(f"verdict_ceiling={summary.verdict_ceiling}")
    if summary.result_status != "completed":
        print(f"failure={summary.failure_message}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
