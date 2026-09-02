"""Run and archive one preregistered Day 3 openEMS/NEC2 cross-check."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import (
    CrossCheckError,
    record_cross_check_failure,
    run_cross_check,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_run_id")
    parser.add_argument("--design-index", type=int, default=0)
    parser.add_argument("--batch-id", default="day3-crosscheck")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    try:
        summary = await run_cross_check(
            args.source_run_id,
            design_index=args.design_index,
            batch_id=args.batch_id,
            repo_root=repo_root,
        )
        note = (
            f"cross-check target={summary.source_run_id} "
            f"verdict={summary.decision.verdict}"
        )
        subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts" / "archive_run.py"),
                summary.run_id,
                "--role",
                "other",
                "--note",
                note,
            ],
            cwd=repo_root,
            check=True,
        )
    except (CrossCheckError, subprocess.CalledProcessError) as error:
        record_cross_check_failure(
            args.source_run_id,
            args.design_index,
            str(error),
            batch_id=args.batch_id,
            repo_root=repo_root,
        )
        print(f"cross_check_run: {error}", file=sys.stderr)
        return 1
    print(f"run_id={summary.run_id}")
    print(f"source_run_id={summary.source_run_id}")
    print(
        f"openems_f_res_hz={summary.openems.resonance_frequency_hz:.6f} "
        f"openems_s11_db={summary.openems.resonance_s11_db:.6f}"
    )
    print(
        f"nec2_f_res_hz={summary.nec2.resonance_frequency_hz:.6f} "
        f"nec2_s11_db={summary.nec2.resonance_s11_db:.6f}"
    )
    print(
        f"delta_f={summary.decision.resonance_relative_difference:.6%} "
        f"delta_s11_db={summary.decision.s11_depth_difference_db:.6f}"
    )
    print(f"verdict={summary.decision.verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(parse_args())))
