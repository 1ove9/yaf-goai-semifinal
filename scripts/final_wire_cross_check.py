"""Run both frozen Day 5-1b candidates under the converged instruments."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.cross_check_v21 import CurveDecisionV21
from yaf_ai.exploration.final_wire_convergence import FinalConvergenceSeries
from yaf_ai.exploration.final_wire_protocol import load_frozen_final_candidates
from yaf_ai.exploration.wire_cross_check import run_wire_cross_check

FINAL_BATCH_ID = "day5-wire-v6-final"


def _archived(repo_root: Path) -> set[str]:
    path = repo_root / "artifacts" / "runs" / "manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CrossCheckError(f"cannot read evidence manifest: {error}") from error
    return {str(item["run_id"]) for item in payload}


def _instrument_settings(repo_root: Path) -> tuple[int, float]:
    path = repo_root / "artifacts" / "analysis" / FINAL_BATCH_ID / "convergence-series.json"
    try:
        series = FinalConvergenceSeries.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load final convergence series: {error}") from error
    if series.selected_openems_refinement is None:
        raise CrossCheckError("openEMS has no preregistered final feasible setting")
    return series.selected_nec2_density, series.selected_openems_refinement


def _archive(repo_root: Path, run_id: str, label: str, source_run_id: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "archive_run.py"),
            run_id,
            "--role",
            "other",
            "--note",
            (
                f"batch={FINAL_BATCH_ID} candidate={label} final-v2.1-crosscheck "
                f"source={source_run_id}"
            ),
        ],
        cwd=repo_root,
        check=True,
    )


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        density, refinement = _instrument_settings(repo_root)
        candidates = load_frozen_final_candidates(repo_root)
        archived = _archived(repo_root)
        for candidate in candidates:
            run_id = f"{FINAL_BATCH_ID}-crosscheck-top{candidate.design.rank}"
            if run_id in archived:
                print(f"SKIP {run_id} already archived")
                continue
            summary = await run_wire_cross_check(
                repo_root,
                candidate.design,
                batch_id=FINAL_BATCH_ID,
                nec2_segments_per_wavelength=density,
                openems_mesh_refinement=refinement,
            )
            _archive(
                repo_root,
                summary.run_id,
                candidate.label,
                candidate.design.source_run_id,
            )
            if not isinstance(summary.decision, CurveDecisionV21):
                raise CrossCheckError("final cross-check did not use protocol v2.1")
            print(
                f"candidate={candidate.label} run_id={summary.run_id} "
                f"source={candidate.design.source_run_id} "
                f"step={candidate.design.source_step_index} "
                f"nec2=lambda/{density} openems={refinement:g}x"
            )
            print(
                f"openems_f_res_hz={summary.openems.resonance_frequency_hz:.6f} "
                f"openems_s11_db={summary.openems.resonance_s11_db:.9f} "
                f"nec2_f_res_hz={summary.nec2.resonance_frequency_hz:.6f} "
                f"nec2_s11_db={summary.nec2.resonance_s11_db:.9f}"
            )
            print(
                f"openems_valid={summary.decision.openems_validity.valid} "
                f"nec2_valid={summary.decision.nec2_validity.valid} "
                f"delta_f={summary.decision.resonance_relative_difference} "
                f"pearson={summary.decision.curve_pearson_correlation} "
                f"verdict={summary.decision.verdict}"
            )
        return 0
    except (CrossCheckError, subprocess.CalledProcessError) as error:
        print(f"final_wire_cross_check: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
