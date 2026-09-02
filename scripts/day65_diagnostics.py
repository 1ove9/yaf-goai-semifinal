"""Run the preregistered Day 6.5 diagnostics in frozen order."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Literal, cast

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.day65_diagnostics import (
    RADIUS_DIAGNOSTIC_RUN_ID,
    run_compute_audit,
    run_radius_diagnostic,
)

Stage = Literal["radius", "mesh"]


def _archive_radius(repo_root: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "archive_run.py"),
            RADIUS_DIAGNOSTIC_RUN_ID,
            "--role",
            "other",
            "--note",
            "day65 diagnostic=nec2-surrogate-radius systematic-frequency-bias",
        ],
        cwd=repo_root,
        check=True,
    )


async def _run(stage: Stage) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    if stage == "radius":
        summary = await run_radius_diagnostic(repo_root)
        _archive_radius(repo_root)
        print(
            f"run_id={summary.run_id} "
            f"f_res={summary.resonance.frequency_hz / 1e9:.9f}GHz "
            f"s11={summary.resonance.s11_db:.9f}dB "
            f"explained_fraction={summary.decision.explained_fraction:.9f} "
            f"classification={summary.decision.classification}"
        )
        return 0
    analysis = await run_compute_audit(repo_root)
    for candidate in (analysis.candidate_a, analysis.candidate_b):
        mesh = candidate.mesh
        print(
            f"candidate={candidate.candidate} "
            f"lines=({mesh.x.line_count},{mesh.y.line_count},{mesh.z.line_count}) "
            f"cells={mesh.total_cells} "
            f"memory_gib={candidate.estimated_field_memory_gib:.9f}"
        )
    print(
        f"cells_B_over_A={analysis.compute_decision.cells_b_over_a:.9f} "
        f"classification={analysis.compute_decision.classification} "
        f"future_timeout_seconds={analysis.compute_decision.future_timeout_seconds}"
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("radius", "mesh"), required=True)
    return parser


def main() -> int:
    """Execute exactly one explicitly selected diagnostic stage."""

    stage = cast(Stage, _parser().parse_args().stage)
    try:
        return asyncio.run(_run(stage))
    except (CrossCheckError, OSError, subprocess.CalledProcessError) as error:
        print(f"day65_diagnostics: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
