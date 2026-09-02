"""Run Day 6.5 v2 convergence and final top-two cross-check stages."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.day6_cross_check import (
    Day6BandDecision,
    high_band_shift,
)
from yaf_ai.exploration.day65_cross_check import (
    Day65V2InstrumentRunSummary,
    build_day65_v2_convergence,
    frozen_day65_v2_candidates,
    run_day65_v2_final,
    run_day65_v2_instrument,
    write_day65_v2_convergence,
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
    selected = frozen_day65_v2_candidates(repo_root)[0]
    summaries: list[Day65V2InstrumentRunSummary] = []
    for refinement in (1.0, 2.0):
        summary = await run_day65_v2_instrument(repo_root, selected, refinement)
        _archive(
            repo_root,
            summary.run_id,
            f"batch=day65-freeform-v2 candidate=top1 openEMS={refinement:g}x convergence",
        )
        summaries.append(summary)
    shift = high_band_shift(summaries[-2].curve, summaries[-1].curve)
    if shift is None or shift > 0.03:
        for refinement in (4.0, 6.0):
            summary = await run_day65_v2_instrument(repo_root, selected, refinement)
            _archive(
                repo_root,
                summary.run_id,
                f"batch=day65-freeform-v2 candidate=top1 openEMS={refinement:g}x convergence",
            )
            summaries.append(summary)
            shift = high_band_shift(summaries[-2].curve, summaries[-1].curve)
            if shift is not None and shift <= 0.03:
                break
    document = build_day65_v2_convergence(summaries)
    write_day65_v2_convergence(repo_root, document)
    for level in document.levels:
        print(
            f"openEMS={level.refinement:g}x run={level.run_id} "
            f"seconds={level.simulation_time_seconds:.6f} "
            f"shift={level.high_band_shift_from_previous} "
            f"pass={level.comparison_passed}"
        )
    print(
        f"self_convergence={document.self_convergence_established} "
        f"first_passing={document.first_passing_refinement} claim=6x"
    )
    return 0


def _band_line(name: str, value: Day6BandDecision) -> str:
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


async def _final(repo_root: Path) -> int:
    for selected in frozen_day65_v2_candidates(repo_root):
        result = await run_day65_v2_final(repo_root, selected)
        _archive(
            repo_root,
            result.run_id,
            f"batch=day65-freeform-v2 candidate=top{selected.rank} final dual-band v2.1",
        )
        print(
            f"top{selected.rank} source={selected.source_run_id}:"
            f"{selected.source_step_index} base={selected.source_base_score:.9f}"
        )
        print(_band_line("low", result.decision.low_band))
        print(_band_line("high", result.decision.high_band))
        print(
            f"pearson={result.decision.whole_sweep_pearson} "
            f"verdict={result.decision.verdict} "
            f"self_converged={result.high_band_self_convergence_established} "
            f"discovery={result.discovery_verdict}"
        )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("convergence", "final"), required=True)
    return parser.parse_args()


def main() -> int:
    """Execute one source-order-sensitive v2 cross-check stage."""

    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        if args.stage == "convergence":
            return asyncio.run(_convergence(repo_root))
        return asyncio.run(_final(repo_root))
    except (CrossCheckError, OSError, subprocess.CalledProcessError) as error:
        print(f"day65_cross_check: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
