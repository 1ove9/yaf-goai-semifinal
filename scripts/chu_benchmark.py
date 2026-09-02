"""Generate the preregistered Chu benchmark from archived bytes only."""

from __future__ import annotations

import sys
from pathlib import Path

from yaf_ai.analysis.chu_benchmark import write_chu_benchmark
from yaf_ai.exploration.cross_check import CrossCheckError


def main() -> int:
    try:
        summary = write_chu_benchmark(Path(__file__).resolve().parents[1])
    except (CrossCheckError, ValueError) as error:
        print(f"chu_benchmark: {error}", file=sys.stderr)
        return 1
    print(
        f"rows={len(summary.rows)} main={summary.main_row_count} "
        f"appendix={summary.appendix_row_count} "
        f"anchor_reference={summary.anchor_reference_ratio} "
        f"solver_calls={summary.solver_calls} new_runs={summary.new_run_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
