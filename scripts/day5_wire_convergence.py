"""Run and archive the preregistered Day 5 top-1 convergence study."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.day5_wire_convergence import run_day5_convergence


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", default="day5-wire-v6r2")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    summary = await run_day5_convergence(repo_root, batch_id=args.batch_id)
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "archive_run.py"),
            summary.run_id,
            "--role",
            "other",
            "--note",
            f"batch={args.batch_id} top1 segmentation-and-mesh-convergence",
        ],
        cwd=repo_root,
        check=True,
    )
    print(
        f"openems_1x={summary.openems_default.resonance_frequency_hz:.0f} "
        f"openems_2x={summary.openems_refined.resonance_frequency_hz:.0f} "
        f"shift={summary.openems_resonance_relative_shift:.6%} "
        f"self_converged={summary.openems_self_converged}"
    )
    for density, curve, gap in zip(
        (20, 40, 80),
        summary.nec2_curves,
        summary.nec2_to_refined_openems_gaps,
        strict=True,
    ):
        print(
            f"lambda/{density} f_res={curve.resonance_frequency_hz:.0f} "
            f"s11={curve.resonance_s11_db:.6f} gap={gap:.6%} "
            f"seconds={curve.simulation_time_seconds:.6f}"
        )
    print(
        f"attribution={summary.attribution.verdict} "
        f"ratio={summary.attribution.finest_to_coarsest_ratio:.6f} "
        "estimated_density="
        f"{summary.attribution.estimated_segments_per_wavelength_for_five_percent}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
