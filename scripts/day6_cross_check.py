"""Run Day 6 openEMS convergence and both frozen final cross-checks."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.day6_cross_check import (
    DAY6_OPENEMS_MAX_REFINEMENT_SECONDS,
    Day6InstrumentRunSummary,
    SelectedDay6Design,
    high_band_shift,
    load_day6_selection,
    openems_converged,
    run_day6_final_cross_check,
    run_day6_instrument,
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


async def _load_or_run_instrument(
    repo_root: Path,
    *,
    selected: SelectedDay6Design,
    run_id: str,
    refinement: float,
) -> Day6InstrumentRunSummary:
    summary_path = repo_root / "runs" / run_id / "summary.json"
    if summary_path.is_file():
        summary = Day6InstrumentRunSummary.model_validate_json(
            summary_path.read_text(encoding="utf-8")
        )
        if (
            summary.config.get("openems_mesh_refinement") != refinement
            or summary.config.get("solver") != "openems"
        ):
            raise CrossCheckError(f"existing convergence run changed settings: {run_id}")
        return summary
    return await run_day6_instrument(
        repo_root,
        selected,
        solver="openems",
        run_id=run_id,
        openems_refinement=refinement,
    )


async def _run() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    selection = load_day6_selection(repo_root)
    top = selection.candidates[0]
    convergence: list[tuple[float, Day6InstrumentRunSummary]] = []
    for refinement in (1.0, 2.0):
        run_id = f"day6-freeform-openems-convergence-{int(refinement)}x"
        summary = await _load_or_run_instrument(
            repo_root,
            selected=top,
            run_id=run_id,
            refinement=refinement,
        )
        _archive(
            repo_root,
            run_id,
            f"batch=day6-freeform candidate=top1 openEMS={refinement:g}x convergence",
        )
        convergence.append((refinement, summary))
    selected_refinement: float | None = None
    if openems_converged(convergence[-2][1].curve, convergence[-1][1].curve):
        selected_refinement = 2.0
    elif convergence[-1][1].curve.simulation_time_seconds <= DAY6_OPENEMS_MAX_REFINEMENT_SECONDS:
        summary = await _load_or_run_instrument(
            repo_root,
            selected=top,
            run_id="day6-freeform-openems-convergence-4x",
            refinement=4.0,
        )
        _archive(
            repo_root,
            summary.run_id,
            "batch=day6-freeform candidate=top1 openEMS=4x convergence",
        )
        convergence.append((4.0, summary))
        if openems_converged(convergence[-2][1].curve, convergence[-1][1].curve):
            selected_refinement = 4.0
    convergence_payload = {
        "protocol": "day6-dual-band-v2.1",
        "threshold": 0.03,
        "levels": [
            {
                "refinement": refinement,
                "run_id": summary.run_id,
                "high_band_shift_from_previous": (
                    None
                    if index == 0
                    else high_band_shift(convergence[index - 1][1].curve, summary.curve)
                ),
                "curve": summary.curve.model_dump(mode="json"),
            }
            for index, (refinement, summary) in enumerate(convergence)
        ],
        "selected_refinement": selected_refinement,
        "status": "converged" if selected_refinement is not None else "infeasible_at_current_compute",
    }
    output = repo_root / "artifacts" / "analysis" / "day6-freeform"
    output.mkdir(parents=True, exist_ok=True)
    (output / "convergence.json").write_bytes(
        (json.dumps(convergence_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    if selected_refinement is None:
        print("openEMS high-band instrument did not self-converge", file=sys.stderr)
        return 1
    for candidate in selection.candidates:
        result = await run_day6_final_cross_check(
            repo_root, candidate, openems_refinement=selected_refinement
        )
        _archive(
            repo_root,
            result.run_id,
            f"batch=day6-freeform candidate=top{candidate.rank} final dual-band v2.1",
        )
        print(
            f"top{candidate.rank} verdict={result.decision.verdict} "
            f"discovery={result.discovery_verdict} "
            f"pearson={result.decision.whole_sweep_pearson}"
        )
    return 0


def main() -> int:
    """Run the fixed convergence decision tree and final top-two checks."""

    try:
        return asyncio.run(_run())
    except (CrossCheckError, OSError, subprocess.CalledProcessError) as error:
        print(f"day6_cross_check: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
