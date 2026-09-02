"""Run repaired-renderer convergence and frozen-candidate re-verdicts."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.day65_repair import (
    frozen_candidates,
    repaired_convergence_passed,
    repaired_convergence_shift,
    run_repaired_candidate,
    run_repaired_openems_instrument,
)


def _archived(repo_root: Path) -> set[str]:
    payload = json.loads(
        (repo_root / "artifacts" / "runs" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    return {str(item["run_id"]) for item in payload}


def _archive(repo_root: Path, run_id: str, note: str) -> None:
    if run_id in _archived(repo_root):
        return
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "archive_run.py"),
            run_id,
            "--role",
            "other",
            "--note",
            note,
        ],
        cwd=repo_root,
        check=True,
    )


async def _convergence(repo_root: Path) -> int:
    candidate = frozen_candidates(repo_root)[0]
    previous = None
    for refinement in (1.0, 2.0, 4.0, 6.0):
        result = await run_repaired_openems_instrument(
            repo_root, candidate, refinement=refinement
        )
        _archive(
            repo_root,
            result.run_id,
            f"batch=day65-freeform-repair candidate=A openEMS={refinement:g}x convergence",
        )
        shift = None if previous is None else repaired_convergence_shift(previous, result)
        print(
            f"openEMS {refinement:g}x: min={min(result.curve.s11_db):.6f}dB "
            f"time={result.curve.simulation_time_seconds:.6f}s "
            f"high_band_shift={shift}"
        )
        if previous is not None and repaired_convergence_passed(shift):
            print(f"self_convergence=PASS selected={refinement:g}x")
            return 0
        previous = result
    print("self_convergence=FAIL after 6x", file=sys.stderr)
    return 1


def _band_line(name: str, value: object) -> str:
    payload = value.model_dump(mode="json")
    openems = payload["openems"]
    nec2 = payload["nec2"]
    return (
        f"{name}: openEMS={openems['minimum_frequency_hz']/1e9:.3f}GHz/"
        f"{openems['minimum_s11_db']:.6f}dB valid={openems['valid']} "
        f"NEC2={nec2['minimum_frequency_hz']/1e9:.3f}GHz/"
        f"{nec2['minimum_s11_db']:.6f}dB valid={nec2['valid']} "
        f"gap={payload['resonance_relative_difference']}"
    )


async def _candidates(repo_root: Path) -> int:
    for candidate in frozen_candidates(repo_root):
        result = await run_repaired_candidate(repo_root, candidate)
        _archive(
            repo_root,
            result.run_id,
            f"batch=day65-freeform-repair candidate={'A' if candidate.rank == 1 else 'B'} repaired re-verdict",
        )
        print(f"candidate={'A' if candidate.rank == 1 else 'B'} run={result.run_id}")
        print(_band_line("low", result.decision.low_band))
        print(_band_line("high", result.decision.high_band))
        print(
            f"pearson={result.whole_sweep_pearson:.9f} "
            f"low={result.low_band_verdict} high={result.high_band_verdict} "
            f"dual={result.dual_band_verdict} discovery={result.discovery_verdict}"
        )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("convergence", "candidates"), required=True)
    return parser.parse_args()


def main() -> int:
    """Execute one preregistered stage."""

    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        if args.stage == "convergence":
            return asyncio.run(_convergence(repo_root))
        return asyncio.run(_candidates(repo_root))
    except (CrossCheckError, OSError, subprocess.CalledProcessError) as error:
        print(f"day65_reverdict: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
