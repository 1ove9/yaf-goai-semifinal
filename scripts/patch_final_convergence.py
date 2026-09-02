"""Run and immediately archive the resource-gated final patch ladder."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.patch_final_convergence import (
    ANALYSIS_ID,
    OPENEMS_SELF_CONVERGENCE_THRESHOLD,
    PatchConvergenceSeries,
    PatchResourceStop,
    archived_run_ids,
    grid_prediction,
    load_nec2_run,
    load_openems_run,
    run_nec2_grid,
    run_openems_refinement,
    validate_gate,
    write_series,
)
from yaf_ai.exploration.patch_final_protocol import (
    PATCH_GRID_LADDER,
    GridResourcePrediction,
)


def _archive(repo_root: Path, run_id: str, note: str) -> None:
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


def _print_prediction(prediction: GridResourcePrediction) -> None:
    payload = json.loads(prediction.model_dump_json())
    print(
        "PREDICT "
        f"grid={payload['target_grid_intervals']} "
        f"segments={payload['target_segment_count']} "
        f"seconds={payload['predicted_seconds']:.3f} "
        f"matrix_mib={payload['predicted_matrix_bytes'] / 2**20:.3f} "
        f"available_mib={payload['available_memory_bytes'] / 2**20:.3f} "
        f"memory_limit_mib={payload['memory_limit_bytes'] / 2**20:.3f} "
        f"feasible={payload['feasible']}",
        flush=True,
    )


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        source, prior = validate_gate(repo_root)
        archived = archived_run_ids(repo_root)
        openems_runs = []
        open2_id = f"{ANALYSIS_ID}-openems-2x"
        if open2_id in archived:
            open2 = load_openems_run(repo_root, 2.0)
            print(f"SKIP {open2_id} already archived", flush=True)
        else:
            open2 = await run_openems_refinement(
                repo_root,
                source=source,
                baseline=source.openems,
                baseline_refinement=1.0,
                refinement=2.0,
                baseline_actual_seconds=source.openems.simulation_time_seconds,
            )
            _archive(
                repo_root,
                open2.run_id,
                "patch-final openems-self-convergence refinement=2x",
            )
            archived.add(open2.run_id)
        openems_runs.append(open2)
        print(
            f"OPENEMS refinement=2x predicted={open2.predicted_seconds:.3f}s "
            f"actual={open2.actual_wall_seconds:.3f}s "
            f"f_res={open2.curve.resonance_frequency_hz:.0f} "
            f"s11={open2.curve.resonance_s11_db:.6f} "
            f"shift={open2.adjacent_resonance_shift:.6%} action={open2.action}",
            flush=True,
        )
        selected_refinement = 2.0 if open2.action == "selected" else None
        if open2.action == "run_4x":
            open4_id = f"{ANALYSIS_ID}-openems-4x"
            if open4_id in archived:
                open4 = load_openems_run(repo_root, 4.0)
                print(f"SKIP {open4_id} already archived", flush=True)
            else:
                open4 = await run_openems_refinement(
                    repo_root,
                    source=source,
                    baseline=open2.curve,
                    baseline_refinement=2.0,
                    refinement=4.0,
                    baseline_actual_seconds=open2.actual_wall_seconds,
                )
                _archive(
                    repo_root,
                    open4.run_id,
                    "patch-final openems-self-convergence refinement=4x",
                )
                archived.add(open4.run_id)
            openems_runs.append(open4)
            print(
                f"OPENEMS refinement=4x predicted={open4.predicted_seconds:.3f}s "
                f"actual={open4.actual_wall_seconds:.3f}s "
                f"f_res={open4.curve.resonance_frequency_hz:.0f} "
                f"s11={open4.curve.resonance_s11_db:.6f} "
                f"shift={open4.adjacent_resonance_shift:.6%} action={open4.action}",
                flush=True,
            )
            if open4.adjacent_resonance_shift <= OPENEMS_SELF_CONVERGENCE_THRESHOLD:
                selected_refinement = 4.0

        completed = []
        resource_stop = None
        baseline_grid = prior.points[-1].grid_intervals
        baseline_seconds = prior.points[-1].solve_time_seconds
        for grid in PATCH_GRID_LADDER:
            run_id = f"{ANALYSIS_ID}-nec2-grid{grid}"
            if run_id in archived:
                stage = load_nec2_run(repo_root, grid)
                completed.append(stage)
                baseline_grid = grid
                baseline_seconds = stage.actual_wall_seconds
                print(f"SKIP {run_id} already archived", flush=True)
                continue
            prediction = grid_prediction(
                baseline_grid=baseline_grid,
                baseline_seconds=baseline_seconds,
                target_grid=grid,
            )
            _print_prediction(prediction)
            if not prediction.feasible:
                resource_stop = PatchResourceStop(
                    target_grid_intervals=grid,
                    prediction=prediction,
                )
                print(
                    f"STOP grid={grid} verdict=infeasible_at_current_compute",
                    flush=True,
                )
                break
            stage = await asyncio.to_thread(
                run_nec2_grid,
                repo_root,
                source=source,
                prior=prior,
                completed=tuple(completed),
                grid_intervals=grid,
                prediction=prediction,
            )
            _archive(
                repo_root,
                stage.run_id,
                f"patch-final nec2-grid-convergence grid={grid}",
            )
            archived.add(stage.run_id)
            completed.append(stage)
            baseline_grid = grid
            baseline_seconds = stage.actual_wall_seconds
            print(
                f"NEC2 grid={grid} predicted={prediction.predicted_seconds:.3f}s "
                f"actual={stage.actual_wall_seconds:.3f}s "
                f"solver={stage.point.solve_time_seconds:.3f}s "
                f"f_res={stage.point.nec2_resonance_frequency_hz:.0f} "
                f"s11={stage.point.curve.resonance_s11_db:.6f} "
                f"gap_to_day3_openems={stage.point.resonance_relative_gap:.6%} "
                f"grid_for_5pct={stage.extrapolation.estimated_grid_for_five_percent} "
                f"grid_for_pearson={stage.extrapolation.estimated_grid_for_pearson}",
                flush=True,
            )
        if not completed:
            raise CrossCheckError("resource gate prevented every new NEC2 grid")
        series = PatchConvergenceSeries(
            openems_runs=tuple(openems_runs),
            nec2_runs=tuple(completed),
            selected_openems_refinement=selected_refinement,
            selected_nec2_grid=completed[-1].point.grid_intervals,
            resource_stop=resource_stop,
        )
        write_series(repo_root, series)
        print(
            f"SERIES openems={series.selected_openems_refinement} "
            f"nec2_grid={series.selected_nec2_grid} "
            f"resource_stop={series.resource_stop is not None}",
            flush=True,
        )
        return 0
    except (CrossCheckError, subprocess.CalledProcessError) as error:
        print(f"patch_final_convergence: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
