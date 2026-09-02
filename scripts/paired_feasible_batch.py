"""Run the preregistered exact-support Stage-B matrix."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from yaf_ai.exploration.paired_feasible_batch import (
    StageBMatrixError,
    run_stage_b_matrix,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage-a-evidence-commit",
        required=True,
        help="Full Git commit containing the validated Stage-A summary and report.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        results = asyncio.run(
            run_stage_b_matrix(
                Path(__file__).resolve().parents[1],
                stage_a_evidence_commit=args.stage_a_evidence_commit,
            )
        )
    except StageBMatrixError as error:
        cell = "pre-matrix" if error.failed_cell is None else str(error.failed_cell)
        print(
            f"Stage B failed at {cell}; started={error.failed_cell_started}; "
            f"confirmed={len(error.confirmed_results)}; "
            f"{error.cause_type}: {error.cause_message}"
        )
        return 1
    for result in results:
        print(
            f"{result.summary.run_id}: completed; "
            f"steps={result.summary.steps_completed}; "
            f"turns={[item.accepted_count for item in result.diagnostics.islands]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
