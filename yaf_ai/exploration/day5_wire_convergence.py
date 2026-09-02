"""Real-solver convergence evidence for the fixed Day 5 top-1 meander."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve, _curve
from yaf_ai.exploration.cross_check_v2 import _canonical_hash, _load_anchor_gate
from yaf_ai.exploration.cross_check_v21 import (
    WIDEBAND_FREQUENCY_POINTS,
    WIDEBAND_FREQUENCY_RANGE_HZ,
)
from yaf_ai.exploration.wire_convergence import (
    SegmentationAttribution,
    classify_segmentation_convergence,
)
from yaf_ai.exploration.wire_cross_check import (
    SelectedWireDesign,
    reconstruct_selected_design,
    select_top_gp_designs,
)
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

SEGMENTATION_DENSITIES = (20, 40, 80)
OPENEMS_REFINEMENTS = (1.0, 2.0)
OPENEMS_SELF_CONVERGENCE_THRESHOLD = 0.03


class Day5ConvergenceSummary(BaseModel):
    """Archive-compatible five-run convergence result."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 5
    evaluation_budget: int = 5
    solver_mode_counts: dict[str, int]
    selected_design: SelectedWireDesign
    openems_default: SolverCurve
    openems_refined: SolverCurve
    openems_resonance_relative_shift: float
    openems_self_converged: bool
    nec2_curves: tuple[SolverCurve, SolverCurve, SolverCurve]
    nec2_to_refined_openems_gaps: tuple[float, float, float]
    attribution: SegmentationAttribution


def _write_summary(run_directory: Path, summary: Day5ConvergenceSummary) -> None:
    run_directory.mkdir(parents=True, exist_ok=False)
    records: list[dict[str, Any]] = []
    for refinement, curve in zip(
        OPENEMS_REFINEMENTS,
        (summary.openems_default, summary.openems_refined),
        strict=True,
    ):
        records.append(
            {
                "schema_version": 1,
                "event_type": "openems_mesh_convergence",
                "run_id": summary.run_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "openems_mesh_refinement": refinement,
                "curve": curve.model_dump(mode="json"),
            }
        )
    for density, gap, curve in zip(
        SEGMENTATION_DENSITIES,
        summary.nec2_to_refined_openems_gaps,
        summary.nec2_curves,
        strict=True,
    ):
        records.append(
            {
                "schema_version": 1,
                "event_type": "nec2_segmentation_convergence",
                "run_id": summary.run_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "nec2_segments_per_wavelength": density,
                "relative_gap_to_refined_openems": gap,
                "curve": curve.model_dump(mode="json"),
            }
        )
    log = "".join(
        json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
        for item in records
    )
    (run_directory / "log.jsonl").write_bytes(log.encode("utf-8"))
    temporary = run_directory / "summary.json.tmp"
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
    os.replace(temporary, run_directory / "summary.json")


async def run_day5_convergence(
    repo_root: Path,
    *,
    batch_id: str = "day5-wire-v6r2",
    anchor_run_id: str = "day4-dipole-anchor",
) -> Day5ConvergenceSummary:
    """Run the frozen lambda/20-/40-/80 and openEMS 1x/2x study."""

    _load_anchor_gate(repo_root, anchor_run_id)
    selected = select_top_gp_designs(repo_root, batch_id=batch_id, count=1)[0]
    _config, geometry, seed = reconstruct_selected_design(repo_root, selected)
    run_id = f"{batch_id}-convergence-top1"
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        raise CrossCheckError(f"convergence run already exists: {run_id}")
    frozen_config = {
        "anchor_run_id": anchor_run_id,
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "source_geometry_hash": selected.source_geometry_hash,
        "frequency_range_hz": WIDEBAND_FREQUENCY_RANGE_HZ,
        "frequency_points": WIDEBAND_FREQUENCY_POINTS,
        "nec2_segments_per_wavelength": SEGMENTATION_DENSITIES,
        "openems_mesh_refinements": OPENEMS_REFINEMENTS,
        "openems_self_convergence_threshold": OPENEMS_SELF_CONVERGENCE_THRESHOLD,
        "attribution_instrument_ratio_exclusive": 0.5,
        "attribution_plateau_ratio_inclusive": 0.8,
    }
    started_at = datetime.now(UTC)
    openems_curves: list[SolverCurve] = []
    for refinement in OPENEMS_REFINEMENTS:
        spec = SimulationSpec(
            name=f"{run_id}-openems-{refinement:g}x",
            frequency_range=WIDEBAND_FREQUENCY_RANGE_HZ,
            frequency_points=WIDEBAND_FREQUENCY_POINTS,
            far_field_request=None,
            solver_settings={"openems_mesh_refinement": refinement},
        )
        openems_adapter = OpenEMSAdapter()
        curve = _curve(
            await openems_adapter.solve(
                await openems_adapter.mesh(geometry, spec), spec
            )
        )
        if curve.solver_mode != "subprocess":
            raise CrossCheckError("openEMS convergence result is not subprocess")
        openems_curves.append(curve)
    reference = openems_curves[-1]
    nec2_curves: list[SolverCurve] = []
    gaps: list[float] = []
    for density in SEGMENTATION_DENSITIES:
        spec = SimulationSpec(
            name=f"{run_id}-nec2-lambda-{density}",
            frequency_range=WIDEBAND_FREQUENCY_RANGE_HZ,
            frequency_points=WIDEBAND_FREQUENCY_POINTS,
            far_field_request=None,
            solver_settings={"nec2_segments_per_wavelength": density},
        )
        nec2_adapter = NEC2Adapter()
        curve = _curve(
            await nec2_adapter.solve(await nec2_adapter.mesh(geometry, spec), spec)
        )
        if curve.solver_mode != "subprocess":
            raise CrossCheckError("NEC2 convergence result is not subprocess")
        nec2_curves.append(curve)
        gaps.append(
            abs(curve.resonance_frequency_hz - reference.resonance_frequency_hz)
            / reference.resonance_frequency_hz
        )
    openems_shift = abs(
        openems_curves[0].resonance_frequency_hz
        - openems_curves[1].resonance_frequency_hz
    ) / openems_curves[1].resonance_frequency_hz
    summary = Day5ConvergenceSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=seed,
        config_hash=_canonical_hash(frozen_config),
        config=frozen_config,
        solver_mode_counts={"subprocess": 5},
        selected_design=selected,
        openems_default=openems_curves[0],
        openems_refined=openems_curves[1],
        openems_resonance_relative_shift=openems_shift,
        openems_self_converged=(
            openems_shift <= OPENEMS_SELF_CONVERGENCE_THRESHOLD
        ),
        nec2_curves=(nec2_curves[0], nec2_curves[1], nec2_curves[2]),
        nec2_to_refined_openems_gaps=(gaps[0], gaps[1], gaps[2]),
        attribution=classify_segmentation_convergence(gaps),
    )
    _write_summary(run_directory, summary)
    return summary
