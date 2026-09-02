"""Execute and archive the preregistered Day 6.5 rotation release gate."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.day65 import DAY65_ROTATION_RUN_ID, run_rotation_invariance


def _archive(repo_root: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "archive_run.py"),
            DAY65_ROTATION_RUN_ID,
            "--role",
            "other",
            "--note",
            "batch=day65-freeform-repair rotation-invariance known answer",
        ],
        cwd=repo_root,
        check=True,
    )


async def _run() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    summary = await run_rotation_invariance(repo_root)
    for result in summary.orientations:
        print(
            f"{result.orientation}: "
            f"NEC2={result.nec2_resonance.frequency_hz / 1e9:.3f}GHz/"
            f"{result.nec2_resonance.s11_db:.6f}dB "
            f"openEMS={result.openems_resonance.frequency_hz / 1e9:.3f}GHz/"
            f"{result.openems_resonance.s11_db:.6f}dB"
        )
    for decision in summary.comparisons:
        print(
            f"{decision.solver} {decision.first}-{decision.second}: "
            f"df={decision.frequency_relative_difference:.6%} "
            f"dS11={decision.s11_depth_difference_db:.6f}dB "
            f"r={decision.pearson:.9f} pass={decision.passed}"
        )
    _archive(repo_root)
    print(
        f"openems_release_gate={summary.openems_release_gate_passed} "
        f"nec2_control={summary.nec2_control_passed}"
    )
    return 0 if summary.openems_release_gate_passed else 1


def main() -> int:
    """Run the release gate and stop later work on any failure."""

    try:
        return asyncio.run(_run())
    except (CrossCheckError, OSError, subprocess.CalledProcessError) as error:
        print(f"day65_rotation: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
