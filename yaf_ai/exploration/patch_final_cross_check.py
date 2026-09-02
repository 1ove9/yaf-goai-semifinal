"""One-shot protocol-v2.1 decision for the frozen final patch curves."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve
from yaf_ai.exploration.cross_check_v2 import _canonical_hash
from yaf_ai.exploration.cross_check_v21 import CurveDecisionV21, evaluate_curves_v21
from yaf_ai.exploration.patch_final_analysis import build_patch_convergence_series
from yaf_ai.exploration.patch_final_protocol import (
    FREQUENCY_POINTS,
    FREQUENCY_RANGE_HZ,
    SOURCE_DESIGN_INDEX,
    SOURCE_GEOMETRY_HASH,
    SOURCE_RUN_ID,
    SOURCE_STEP_INDEX,
)

FINAL_RUN_ID = "day5-patch-final-crosscheck"


class PatchFinalCrossCheckSummary(BaseModel):
    """Archive-compatible single final decision using archived real curves."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str = FINAL_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 2
    evaluation_budget: int = 2
    solver_mode_counts: dict[str, int]
    source_run_id: str = SOURCE_RUN_ID
    source_design_index: int = SOURCE_DESIGN_INDEX
    source_step_index: int = SOURCE_STEP_INDEX
    source_geometry_hash: str = SOURCE_GEOMETRY_HASH
    openems_source_run_id: str
    nec2_source_run_id: str
    curves_reused_from_archived_convergence: Literal[True] = True
    openems: SolverCurve
    nec2: SolverCurve
    decision: CurveDecisionV21


def _seed(repo_root: Path) -> int:
    path = (
        repo_root
        / "artifacts"
        / "runs"
        / SOURCE_RUN_ID
        / "summary.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CrossCheckError(f"cannot load frozen patch seed: {error}") from error
    return int(payload["seed"])


def _write_run(directory: Path, summary: PatchFinalCrossCheckSummary) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    records = [
        {
            "schema_version": 1,
            "event_type": "patch_final_cross_solver_curve",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "source_run_id": source_run_id,
            "curve": curve.model_dump(mode="json"),
        }
        for source_run_id, curve in (
            (summary.openems_source_run_id, summary.openems),
            (summary.nec2_source_run_id, summary.nec2),
        )
    ]
    records.append(
        {
            "schema_version": 1,
            "event_type": "patch_final_v2_1_decision",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "decision": summary.decision.model_dump(mode="json"),
        }
    )
    log = "".join(
        json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
        for item in records
    )
    (directory / "log.jsonl").write_bytes(log.encode("utf-8"))
    temporary = directory / "summary.json.tmp"
    temporary.write_bytes(
        (
            json.dumps(
                summary.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    os.replace(temporary, directory / "summary.json")


def run_patch_final_cross_check(repo_root: Path) -> PatchFinalCrossCheckSummary:
    """Evaluate the unique frozen pair exactly once without rerunning either solver."""

    run_directory = repo_root / "runs" / FINAL_RUN_ID
    if run_directory.exists():
        raise CrossCheckError(f"final patch cross-check already exists: {FINAL_RUN_ID}")
    series = build_patch_convergence_series(repo_root)
    if series.selected_openems_refinement is None:
        raise CrossCheckError("openEMS has no self-converged final curve")
    open_stage = next(
        item
        for item in series.openems_runs
        if item.refinement == series.selected_openems_refinement
    )
    nec_stage = next(
        item
        for item in series.nec2_runs
        if item.point.grid_intervals == series.selected_nec2_grid
    )
    if (
        open_stage.curve.solver_mode != "subprocess"
        or nec_stage.point.curve.solver_mode != "subprocess"
    ):
        raise CrossCheckError("final patch curves are not both real subprocess results")
    started_at = datetime.now(UTC)
    decision = evaluate_curves_v21(open_stage.curve, nec_stage.point.curve)
    config = {
        "execution_note": "docs/patch-crosscheck-final-execution-note.md",
        "protocol_version": decision.protocol_version,
        "candidate": {
            "source_run_id": SOURCE_RUN_ID,
            "source_design_index": SOURCE_DESIGN_INDEX,
            "source_step_index": SOURCE_STEP_INDEX,
            "source_geometry_hash": SOURCE_GEOMETRY_HASH,
        },
        "frequency_range_hz": FREQUENCY_RANGE_HZ,
        "frequency_points": FREQUENCY_POINTS,
        "openems_refinement": series.selected_openems_refinement,
        "nec2_grid_intervals": series.selected_nec2_grid,
        "openems_source_run_id": open_stage.run_id,
        "nec2_source_run_id": nec_stage.run_id,
        "curves_reused_from_archived_convergence": True,
        "resonance_depth_threshold_db": -6.0,
        "edge_guard_sample_count": 3,
        "resonance_relative_threshold": 0.05,
        "curve_pearson_threshold": 0.8,
    }
    summary = PatchFinalCrossCheckSummary(
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=_seed(repo_root),
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 2},
        openems_source_run_id=open_stage.run_id,
        nec2_source_run_id=nec_stage.run_id,
        openems=open_stage.curve,
        nec2=nec_stage.point.curve,
        decision=decision,
    )
    _write_run(run_directory, summary)
    return summary


def load_patch_final_cross_check(repo_root: Path) -> PatchFinalCrossCheckSummary:
    """Load the archived final result for report generation."""

    path = (
        repo_root
        / "artifacts"
        / "runs"
        / FINAL_RUN_ID
        / "summary.json"
    )
    try:
        return PatchFinalCrossCheckSummary.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load final patch result: {error}") from error
