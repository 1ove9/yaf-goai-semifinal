"""Execute the preregistered Day 6.5 factor audit in explicit stages."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Literal, cast

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.day65_factor_audit import (
    CANDIDATE_B_OPENEMS_RUN_ID,
    CANDIDATE_B_REBOOT_FAILURE_RUN_ID,
    CANDIDATE_B_REVERDICT_RUN_ID,
    F1_OPENEMS_RUN_ID,
    F2_OPENEMS_RUN_ID,
    F3_L80_RUN_ID,
    F3_L320_RUN_ID,
    F4_NEC2_RUN_ID,
    F4_OPENEMS_RUN_ID,
    OPENEMS_BASE_REFINEMENT,
    OPENEMS_FINE_REFINEMENT,
    SENSITIVE_FEED_GAP_M,
    SHORTEN_EACH_END_M,
    classify_segmentation_stability,
    record_candidate_b_host_reboot,
    run_candidate_b_terminal_retry,
    run_nec2_factor,
    run_openems_factor,
    write_factor_audit_analysis,
)
from yaf_solvers.base import SolverError

Stage = Literal[
    "f3",
    "f4-nec2",
    "f2",
    "f4-openems",
    "f1",
    "rearm-candidate-b-after-reboot",
    "candidate-b",
]


def _archived(repo_root: Path, run_id: str) -> bool:
    manifest = repo_root / "artifacts" / "runs" / "manifest.json"
    return f'"run_id": "{run_id}"' in manifest.read_text(encoding="utf-8")


def _archive(repo_root: Path, run_id: str, note: str) -> None:
    if _archived(repo_root, run_id):
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


async def _run_f3(repo_root: Path) -> int:
    lambda80 = await run_nec2_factor(
        repo_root,
        run_id=F3_L80_RUN_ID,
        factor="F3",
        density=80,
        feed_gap_m=0.0006,
        changed_variable="nec2_segments_per_wavelength=80",
    )
    _archive(repo_root, lambda80.run_id, "day65 factor-audit F3 NEC2 lambda/80")
    print(
        f"F3 lambda/80 f_res={lambda80.resonance.frequency_hz / 1e9:.9f}GHz",
        flush=True,
    )
    lambda320 = await run_nec2_factor(
        repo_root,
        run_id=F3_L320_RUN_ID,
        factor="F3",
        density=320,
        feed_gap_m=0.0006,
        changed_variable="nec2_segments_per_wavelength=320",
    )
    _archive(repo_root, lambda320.run_id, "day65 factor-audit F3 NEC2 lambda/320")
    decision = classify_segmentation_stability(
        lambda80.resonance.frequency_hz,
        lambda320.resonance.frequency_hz,
    )
    print(
        f"F3 lambda/320 f_res={lambda320.resonance.frequency_hz / 1e9:.9f}GHz "
        f"max_shift={decision.maximum_shift_hz / 1e6:.6f}MHz "
        f"classification={decision.classification}",
        flush=True,
    )
    return 0 if decision.classification == "segmentation_stable" else 1


async def _run_f4_nec2(repo_root: Path) -> int:
    result = await run_nec2_factor(
        repo_root,
        run_id=F4_NEC2_RUN_ID,
        factor="F4",
        density=160,
        feed_gap_m=SENSITIVE_FEED_GAP_M,
        changed_variable="feed_gap_m=0.0003",
    )
    _archive(repo_root, result.run_id, "day65 factor-audit F4 NEC2 feed-gap")
    print(
        f"F4 NEC2 f_res={result.resonance.frequency_hz / 1e9:.9f}GHz "
        f"delta={result.delta_frequency_hz / 1e6:.6f}MHz",
        flush=True,
    )
    return 0


async def _run_f2(repo_root: Path) -> int:
    result = await run_openems_factor(
        repo_root,
        run_id=F2_OPENEMS_RUN_ID,
        factor="F2",
        refinement=OPENEMS_BASE_REFINEMENT,
        feed_gap_m=0.0006,
        shorten_each_end_m=SHORTEN_EACH_END_M,
        changed_variable="free_end_centerline_shortening_m=0.00025_each",
    )
    _archive(repo_root, result.run_id, "day65 factor-audit F2 endcap")
    print(
        f"F2 f_res={result.resonance.frequency_hz / 1e9:.9f}GHz "
        f"delta={result.delta_frequency_hz / 1e6:.6f}MHz "
        f"materiality={result.materiality}",
        flush=True,
    )
    return 0


async def _run_f4_openems(repo_root: Path) -> int:
    result = await run_openems_factor(
        repo_root,
        run_id=F4_OPENEMS_RUN_ID,
        factor="F4",
        refinement=OPENEMS_BASE_REFINEMENT,
        feed_gap_m=SENSITIVE_FEED_GAP_M,
        shorten_each_end_m=0.0,
        changed_variable="feed_gap_m=0.0003",
    )
    _archive(repo_root, result.run_id, "day65 factor-audit F4 openEMS feed-gap")
    print(
        f"F4 openEMS f_res={result.resonance.frequency_hz / 1e9:.9f}GHz "
        f"delta={result.delta_frequency_hz / 1e6:.6f}MHz "
        f"differential={float(result.decision_shift_hz or 0.0) / 1e6:.6f}MHz "
        f"materiality={result.materiality}",
        flush=True,
    )
    return 0


async def _run_f1(repo_root: Path) -> int:
    result = await run_openems_factor(
        repo_root,
        run_id=F1_OPENEMS_RUN_ID,
        factor="F1",
        refinement=OPENEMS_FINE_REFINEMENT,
        feed_gap_m=0.0006,
        shorten_each_end_m=0.0,
        changed_variable="openems_refinement=8;timesteps=320000",
    )
    _archive(repo_root, result.run_id, "day65 factor-audit F1 openEMS 8x/320k")
    print(
        f"F1 f_res={result.resonance.frequency_hz / 1e9:.9f}GHz "
        f"delta={result.delta_frequency_hz / 1e6:.6f}MHz "
        f"materiality={result.materiality}",
        flush=True,
    )
    return 0
async def _rearm_candidate_b_after_reboot(repo_root: Path) -> int:
    summary = record_candidate_b_host_reboot(repo_root)
    _archive(
        repo_root,
        CANDIDATE_B_REBOOT_FAILURE_RUN_ID,
        "day65 candidate=B terminal attempt externally interrupted by host reboot",
    )
    print(
        f"candidate_B_interruption={summary.failure_type} "
        f"result={summary.result_status} rearmed_replacement=True",
        flush=True,
    )
    return 0




async def _run_candidate_b(repo_root: Path) -> int:
    state = await run_candidate_b_terminal_retry(repo_root)
    if state.status == "success":
        _archive(
            repo_root,
            CANDIDATE_B_OPENEMS_RUN_ID,
            "batch=day65-freeform-repair candidate=B openEMS=6x terminal retry",
        )
        _archive(
            repo_root,
            CANDIDATE_B_REVERDICT_RUN_ID,
            "batch=day65-freeform-repair candidate=B repaired terminal re-verdict",
        )
    summary = write_factor_audit_analysis(repo_root)
    print(
        f"candidate_B={summary.candidate_b.status} "
        f"dual={summary.candidate_b.dual_band_verdict} "
        f"discovery={summary.candidate_b.discovery_verdict}",
        flush=True,
    )
    return 0


async def _run(stage: Stage) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    runners = {
        "f3": _run_f3,
        "f4-nec2": _run_f4_nec2,
        "f2": _run_f2,
        "f4-openems": _run_f4_openems,
        "f1": _run_f1,
        "candidate-b": _run_candidate_b,
        "rearm-candidate-b-after-reboot": _rearm_candidate_b_after_reboot,
    }
    return await runners[stage](repo_root)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=(
            "f3",
            "f4-nec2",
            "f2",
            "f4-openems",
            "f1",
            "rearm-candidate-b-after-reboot",
            "candidate-b",
        ),
        required=True,
    )
    return parser


def main() -> int:
    """Execute exactly one explicitly selected preregistered stage."""

    stage = cast(Stage, _parser().parse_args().stage)
    try:
        return asyncio.run(_run(stage))
    except (CrossCheckError, SolverError, OSError, subprocess.SubprocessError) as error:
        print(f"day65_factor_audit: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
