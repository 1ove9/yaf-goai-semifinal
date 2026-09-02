"""Run or exactly resume the frozen nine-cell paired-state NEC2 batch."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from yaf_ai.exploration.paired_batch import run_frozen_agent_matrix


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    os.environ["YAF_NO_FALLBACK"] = "1"
    summaries = asyncio.run(run_frozen_agent_matrix(args.repo_root.resolve()))
    complete = True
    for summary in summaries:
        print(
            f"run_id={summary.run_id} status={summary.status} "
            f"steps={summary.steps_completed}/{summary.evaluation_budget} "
            f"rejected={summary.rejected_proposals} "
            f"attempts={summary.proposal_attempts} "
            f"solver_modes={summary.solver_mode_counts}"
        )
        complete = complete and summary.status == "completed"
    print(f"matrix_terminal={len(summaries) == 9}")
    print(f"matrix_budget_complete={complete}")
    print("openems_started=false")
    print("verdict_ceiling=insufficient_evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
