"""Execute the preregistered Day 5-1b instrument-convergence sequence."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve, _curve
from yaf_ai.exploration.cross_check_v2 import _canonical_hash, _load_anchor_gate
from yaf_ai.exploration.cross_check_v21 import (
    WIDEBAND_FREQUENCY_POINTS,
    WIDEBAND_FREQUENCY_RANGE_HZ,
)
from yaf_ai.exploration.day5_wire_convergence import Day5ConvergenceSummary
from yaf_ai.exploration.final_wire_protocol import (
    FinalInstrumentAttribution,
    FrozenFinalCandidate,
    OpenEMSInstrumentDecision,
    classify_final_instrument_attribution,
    decide_openems_instrument,
    load_frozen_final_candidates,
)
from yaf_ai.exploration.wire_cross_check import reconstruct_selected_design
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

FINAL_ANALYSIS_ID = "day5-wire-v6-final"
STAGE1_RUN_ID = f"{FINAL_ANALYSIS_ID}-convergence-stage1"
StageHook = Callable[["FinalConvergenceStageSummary"], None]


class TimedInstrumentCurve(BaseModel):
    """One real curve with both solver-reported and wall-clock duration."""

    model_config = ConfigDict(frozen=True)

    solver: Literal["openems", "nec2"]
    setting_name: str
    setting_value: float = Field(gt=0.0)
    wall_time_seconds: float = Field(ge=0.0)
    curve: SolverCurve


class FinalConvergenceStageSummary(BaseModel):
    """Archive-compatible stage containing only newly executed solver curves."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = Field(gt=0)
    evaluation_budget: int = Field(gt=0)
    solver_mode_counts: dict[str, int]
    candidate: FrozenFinalCandidate
    curves: tuple[TimedInstrumentCurve, ...]
    openems_decision: OpenEMSInstrumentDecision | None = None


class FinalConvergenceSeries(BaseModel):
    """Combined old/new sequence that determines the final instrument settings."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    candidate: FrozenFinalCandidate
    prior_run_id: str
    new_run_ids: tuple[str, ...]
    openems_curves: tuple[TimedInstrumentCurve, ...]
    nec2_curves: tuple[TimedInstrumentCurve, ...]
    selected_openems_refinement: float | None = Field(default=None, gt=0.0)
    selected_nec2_density: int = 160
    openems_decision: OpenEMSInstrumentDecision
    attribution: FinalInstrumentAttribution


def _write_stage(run_directory: Path, summary: FinalConvergenceStageSummary) -> None:
    run_directory.mkdir(parents=True, exist_ok=False)
    log = "".join(
        json.dumps(
            {
                "schema_version": 1,
                "event_type": "final_instrument_convergence",
                "run_id": summary.run_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "candidate_label": summary.candidate.label,
                "timed_curve": item.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
        for item in summary.curves
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


async def _run_openems(
    geometry: Geometry, *, refinement: float, run_id: str
) -> TimedInstrumentCurve:
    spec = SimulationSpec(
        name=run_id,
        frequency_range=WIDEBAND_FREQUENCY_RANGE_HZ,
        frequency_points=WIDEBAND_FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings={"openems_mesh_refinement": refinement},
    )
    adapter = OpenEMSAdapter()
    started = time.perf_counter()
    curve = _curve(await adapter.solve(await adapter.mesh(geometry, spec), spec))
    wall_time = time.perf_counter() - started
    if curve.solver_mode != "subprocess":
        raise CrossCheckError(f"openEMS {refinement}x result is not subprocess")
    return TimedInstrumentCurve(
        solver="openems",
        setting_name="mesh_refinement",
        setting_value=refinement,
        wall_time_seconds=wall_time,
        curve=curve,
    )


async def _run_nec2(
    geometry: Geometry, *, density: int, run_id: str
) -> TimedInstrumentCurve:
    spec = SimulationSpec(
        name=run_id,
        frequency_range=WIDEBAND_FREQUENCY_RANGE_HZ,
        frequency_points=WIDEBAND_FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings={"nec2_segments_per_wavelength": density},
    )
    adapter = NEC2Adapter()
    started = time.perf_counter()
    curve = _curve(await adapter.solve(await adapter.mesh(geometry, spec), spec))
    wall_time = time.perf_counter() - started
    if curve.solver_mode != "subprocess":
        raise CrossCheckError(f"NEC2 lambda/{density} result is not subprocess")
    return TimedInstrumentCurve(
        solver="nec2",
        setting_name="segments_per_wavelength",
        setting_value=float(density),
        wall_time_seconds=wall_time,
        curve=curve,
    )


def _stage_config(
    candidate: FrozenFinalCandidate,
    curves: tuple[TimedInstrumentCurve, ...],
    *,
    prior_run_id: str,
) -> dict[str, Any]:
    return {
        "execution_note": "docs/cross-solver-protocol-v2.1-execution-note.md",
        "protocol_version": "day4-wideband-resonance-v2.1",
        "candidate": candidate.model_dump(mode="json"),
        "prior_convergence_run_id": prior_run_id,
        "frequency_range_hz": WIDEBAND_FREQUENCY_RANGE_HZ,
        "frequency_points": WIDEBAND_FREQUENCY_POINTS,
        "new_settings": [
            {
                "solver": item.solver,
                "setting_name": item.setting_name,
                "setting_value": item.setting_value,
            }
            for item in curves
        ],
    }


def _load_prior(repo_root: Path) -> Day5ConvergenceSummary:
    path = (
        repo_root
        / "artifacts"
        / "runs"
        / "day5-wire-v6r2-convergence-top1"
        / "summary.json"
    )
    try:
        return Day5ConvergenceSummary.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load prior convergence evidence: {error}") from error


def _prior_timed_curves(
    prior: Day5ConvergenceSummary,
) -> tuple[tuple[TimedInstrumentCurve, ...], tuple[TimedInstrumentCurve, ...]]:
    openems = tuple(
        TimedInstrumentCurve(
            solver="openems",
            setting_name="mesh_refinement",
            setting_value=refinement,
            wall_time_seconds=curve.simulation_time_seconds,
            curve=curve,
        )
        for refinement, curve in zip(
            (1.0, 2.0),
            (prior.openems_default, prior.openems_refined),
            strict=True,
        )
    )
    nec2 = tuple(
        TimedInstrumentCurve(
            solver="nec2",
            setting_name="segments_per_wavelength",
            setting_value=float(density),
            wall_time_seconds=curve.simulation_time_seconds,
            curve=curve,
        )
        for density, curve in zip((20, 40, 80), prior.nec2_curves, strict=True)
    )
    return openems, nec2


def _combine_series(
    candidate: FrozenFinalCandidate,
    prior: Day5ConvergenceSummary,
    stages: tuple[FinalConvergenceStageSummary, ...],
) -> FinalConvergenceSeries:
    prior_openems, prior_nec2 = _prior_timed_curves(prior)
    new_curves = tuple(item for stage in stages for item in stage.curves)
    openems = (*prior_openems, *(item for item in new_curves if item.solver == "openems"))
    nec2 = (*prior_nec2, *(item for item in new_curves if item.solver == "nec2"))
    decision = stages[-1].openems_decision or stages[0].openems_decision
    if decision is None:
        raise CrossCheckError("final stage has no openEMS instrument decision")
    selected_refinement = decision.selected_refinement
    final_openems = openems[-1]
    if selected_refinement is not None:
        final_openems = next(
            item for item in openems if item.setting_value == selected_refinement
        )
    gaps = tuple(
        abs(
            item.curve.resonance_frequency_hz
            - final_openems.curve.resonance_frequency_hz
        )
        / final_openems.curve.resonance_frequency_hz
        for item in nec2
    )
    openems_by_refinement = {item.setting_value: item for item in openems}
    if selected_refinement == 3.0:
        adjacent_openems = (openems_by_refinement[2.0], openems_by_refinement[3.0])
    elif selected_refinement == 4.0:
        adjacent_openems = (openems_by_refinement[2.0], openems_by_refinement[4.0])
    elif selected_refinement == 8.0:
        adjacent_openems = (openems_by_refinement[4.0], openems_by_refinement[8.0])
    else:
        adjacent_openems = (openems[-2], openems[-1])
    attribution = classify_final_instrument_attribution(
        openems_adjacent_frequencies_hz=(
            adjacent_openems[0].curve.resonance_frequency_hz,
            adjacent_openems[1].curve.resonance_frequency_hz,
        ),
        nec2_adjacent_frequencies_hz=(
            nec2[-2].curve.resonance_frequency_hz,
            nec2[-1].curve.resonance_frequency_hz,
        ),
        nec2_to_final_openems_gaps=gaps,
    )
    return FinalConvergenceSeries(
        candidate=candidate,
        prior_run_id=prior.run_id,
        new_run_ids=tuple(stage.run_id for stage in stages),
        openems_curves=openems,
        nec2_curves=nec2,
        selected_openems_refinement=selected_refinement,
        openems_decision=decision,
        attribution=attribution,
    )


async def run_final_convergence(
    repo_root: Path,
    *,
    anchor_run_id: str = "day4-dipole-anchor",
    on_stage: StageHook | None = None,
) -> tuple[FinalConvergenceSeries, tuple[FinalConvergenceStageSummary, ...]]:
    """Run stage 1 and only the mechanically requested optional stage 2."""

    _load_anchor_gate(repo_root, anchor_run_id)
    candidate = load_frozen_final_candidates(repo_root)[0]
    _config, geometry, seed = reconstruct_selected_design(repo_root, candidate.design)
    prior = _load_prior(repo_root)
    if (repo_root / "runs" / STAGE1_RUN_ID).exists():
        raise CrossCheckError(f"final convergence run already exists: {STAGE1_RUN_ID}")
    started_at = datetime.now(UTC)
    openems_4x = await _run_openems(
        geometry, refinement=4.0, run_id=f"{STAGE1_RUN_ID}-openems-4x"
    )
    nec2_160 = await _run_nec2(
        geometry, density=160, run_id=f"{STAGE1_RUN_ID}-nec2-lambda-160"
    )
    stage1_curves = (openems_4x, nec2_160)
    openems_decision = decide_openems_instrument(
        (2.0, 4.0),
        (
            prior.openems_refined.resonance_frequency_hz,
            openems_4x.curve.resonance_frequency_hz,
        ),
        (prior.openems_refined.simulation_time_seconds, openems_4x.wall_time_seconds),
    )
    config = _stage_config(candidate, stage1_curves, prior_run_id=prior.run_id)
    stage1 = FinalConvergenceStageSummary(
        run_id=STAGE1_RUN_ID,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=seed,
        config_hash=_canonical_hash(config),
        config=config,
        steps_completed=2,
        evaluation_budget=2,
        solver_mode_counts={"subprocess": 2},
        candidate=candidate,
        curves=stage1_curves,
        openems_decision=openems_decision,
    )
    _write_stage(repo_root / "runs" / STAGE1_RUN_ID, stage1)
    if on_stage is not None:
        on_stage(stage1)
    stages = [stage1]
    if openems_decision.action in {"run_8x", "run_3x"}:
        refinement = 8.0 if openems_decision.action == "run_8x" else 3.0
        stage2_run_id = f"{FINAL_ANALYSIS_ID}-convergence-stage2-openems-{refinement:g}x"
        if (repo_root / "runs" / stage2_run_id).exists():
            raise CrossCheckError(f"final convergence run already exists: {stage2_run_id}")
        stage2_started = datetime.now(UTC)
        openems_final = await _run_openems(
            geometry,
            refinement=refinement,
            run_id=stage2_run_id,
        )
        base_refinement = 4.0 if refinement == 8.0 else 2.0
        base_curve = (
            openems_4x.curve if refinement == 8.0 else prior.openems_refined
        )
        base_time = (
            openems_4x.wall_time_seconds
            if refinement == 8.0
            else prior.openems_refined.simulation_time_seconds
        )
        final_decision = decide_openems_instrument(
            (base_refinement, refinement),
            (
                base_curve.resonance_frequency_hz,
                openems_final.curve.resonance_frequency_hz,
            ),
            (base_time, openems_final.wall_time_seconds),
        )
        stage2_curves = (openems_final,)
        stage2_config = _stage_config(
            candidate, stage2_curves, prior_run_id=stage1.run_id
        )
        stage2 = FinalConvergenceStageSummary(
            run_id=stage2_run_id,
            started_at=stage2_started,
            finished_at=datetime.now(UTC),
            seed=seed,
            config_hash=_canonical_hash(stage2_config),
            config=stage2_config,
            steps_completed=1,
            evaluation_budget=1,
            solver_mode_counts={"subprocess": 1},
            candidate=candidate,
            curves=stage2_curves,
            openems_decision=final_decision,
        )
        _write_stage(repo_root / "runs" / stage2_run_id, stage2)
        if on_stage is not None:
            on_stage(stage2)
        stages.append(stage2)
    return _combine_series(candidate, prior, tuple(stages)), tuple(stages)
