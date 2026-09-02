"""Converged-instrument cross-checks for the Day 6.5 v2 hunt."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve, _curve
from yaf_ai.exploration.day6_cross_check import (
    DAY6_OPENEMS_CONVERGENCE_THRESHOLD,
    Day6CrossCheckDecision,
    evaluate_day6_curves,
    high_band_shift,
)
from yaf_ai.exploration.day65_batch import DAY65_OCFD_SCORE
from yaf_ai.exploration.day65_selection import (
    SelectedDay65Design,
    load_day65_selection,
)
from yaf_ai.exploration.environment import geometry_hash
from yaf_ai.exploration.freeform_wire import (
    FREEFORM_FREQUENCY_POINTS,
    FREEFORM_SWEEP_HZ,
    build_freeform_wire,
)
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

DAY65_V2_PROTOCOL = "day65-freeform-v2-v2.1"
DAY65_V2_NEC2_DENSITY = 160
DAY65_V2_OPENEMS_REFINEMENT = 6.0
DAY65_V2_OPENEMS_BASE_TIMESTEPS = 40000
DAY65_V2_OPENEMS_TIMEOUT_SECONDS = 21600.0
DAY65_V2_CONVERGENCE_FILE = (
    "artifacts/analysis/day65-freeform-v2/convergence.json"
)

SolverName = Literal["nec2", "openems"]


class Day65V2InstrumentRunSummary(BaseModel):
    """One archive-compatible real curve in the v2 convergence series."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 1
    evaluation_budget: int = 1
    solver_mode_counts: dict[str, int]
    selected_design: SelectedDay65Design
    curve: SolverCurve


class Day65V2ConvergenceLevel(BaseModel):
    """One ordered high-band self-convergence level."""

    model_config = ConfigDict(frozen=True)

    refinement: float
    run_id: str
    simulation_time_seconds: float
    high_band_shift_from_previous: float | None
    comparison_passed: bool


class Day65V2ConvergenceDocument(BaseModel):
    """Machine-readable result of the frozen source-specific diagnostic."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    protocol_version: str = DAY65_V2_PROTOCOL
    source_run_id: str
    source_step_index: int
    threshold: float = DAY6_OPENEMS_CONVERGENCE_THRESHOLD
    levels: tuple[Day65V2ConvergenceLevel, ...]
    self_convergence_established: bool
    first_passing_refinement: float | None
    claim_refinement: float = DAY65_V2_OPENEMS_REFINEMENT


class Day65V2CrossCheckRunSummary(BaseModel):
    """Archive-compatible final two-solver decision for one v2 candidate."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 2
    evaluation_budget: int = 2
    solver_mode_counts: dict[str, int]
    selected_design: SelectedDay65Design
    nec2: SolverCurve
    openems: SolverCurve
    openems_curve_source_run_id: str | None
    decision: Day6CrossCheckDecision
    reference_gate_met: bool
    high_band_self_convergence_established: bool
    discovery_verdict: Literal["confirmed_improvement", "insufficient_evidence"]


def _canonical_hash(payload: object) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def _write_run(
    run_directory: Path,
    summary: Day65V2InstrumentRunSummary | Day65V2CrossCheckRunSummary,
    records: list[dict[str, object]],
) -> None:
    run_directory.mkdir(parents=True, exist_ok=False)
    payload = "".join(
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
        for record in records
    )
    (run_directory / "log.jsonl").write_bytes(payload.encode("utf-8"))
    _write_json(run_directory / "summary.json", summary.model_dump(mode="json"))


def reconstruct_day65_v2_design(
    repo_root: Path, selected: SelectedDay65Design
) -> tuple[Geometry, int]:
    """Rebuild one selected source geometry and verify its immutable hash."""

    path = repo_root / "artifacts" / "runs" / selected.source_run_id / "summary.json"
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
        version = str(summary["config"]["proposal_space_version"])
        seed = int(summary["seed"])
        node_count = int(version.rsplit("-n", 1)[1])
    except (OSError, KeyError, IndexError, ValueError, json.JSONDecodeError) as error:
        raise CrossCheckError(f"cannot reconstruct Day 6.5 source: {error}") from error
    geometry = build_freeform_wire(
        selected.proposal_parameters, node_count, selected.proposer
    )
    actual_hash = geometry_hash(geometry)
    if actual_hash != selected.source_geometry_hash:
        raise CrossCheckError(
            "Day 6.5 source geometry hash mismatch: "
            f"expected={selected.source_geometry_hash} actual={actual_hash}"
        )
    return geometry, seed


async def _solve(
    geometry: Geometry,
    run_id: str,
    solver: SolverName,
    *,
    openems_refinement: float = DAY65_V2_OPENEMS_REFINEMENT,
) -> SolverCurve:
    settings: dict[str, float | int] = {
        "nec2_segments_per_wavelength": DAY65_V2_NEC2_DENSITY,
        "nec2_timeout_seconds": 1800.0,
        "openems_mesh_refinement": openems_refinement,
        "openems_base_timesteps": DAY65_V2_OPENEMS_BASE_TIMESTEPS,
        "openems_timeout_seconds": DAY65_V2_OPENEMS_TIMEOUT_SECONDS,
    }
    spec = SimulationSpec(
        name=run_id,
        frequency_range=FREEFORM_SWEEP_HZ,
        frequency_points=FREEFORM_FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings=settings,
    )
    adapter = NEC2Adapter() if solver == "nec2" else OpenEMSAdapter()
    mesh = await adapter.mesh(geometry, spec)
    curve = _curve(await adapter.solve(mesh, spec))
    if curve.solver_mode != "subprocess":
        raise CrossCheckError(f"Day 6.5 v2 {solver} was not real: {curve.solver_mode}")
    return curve


async def run_day65_v2_instrument(
    repo_root: Path,
    selected: SelectedDay65Design,
    refinement: float,
) -> Day65V2InstrumentRunSummary:
    """Run or integrity-check one top-1 openEMS convergence level."""

    suffix = f"{refinement:g}x"
    run_id = f"day65-freeform-v2-openems-convergence-top1-{suffix}"
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        summary = Day65V2InstrumentRunSummary.model_validate_json(
            (run_directory / "summary.json").read_text(encoding="utf-8")
        )
        if (
            summary.selected_design != selected
            or summary.config.get("openems_mesh_refinement") != refinement
        ):
            raise CrossCheckError(f"existing v2 instrument run changed: {run_id}")
        return summary
    geometry, seed = reconstruct_day65_v2_design(repo_root, selected)
    config: dict[str, Any] = {
        "protocol_version": DAY65_V2_PROTOCOL,
        "purpose": "top-1 high-band self-convergence",
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "source_geometry_hash": selected.source_geometry_hash,
        "solver": "openems",
        "frequency_range_hz": FREEFORM_SWEEP_HZ,
        "frequency_points": FREEFORM_FREQUENCY_POINTS,
        "openems_mesh_refinement": refinement,
        "openems_base_timesteps": DAY65_V2_OPENEMS_BASE_TIMESTEPS,
        "openems_timeout_seconds": DAY65_V2_OPENEMS_TIMEOUT_SECONDS,
    }
    started_at = datetime.now(UTC)
    curve = await _solve(
        geometry, run_id, "openems", openems_refinement=refinement
    )
    summary = Day65V2InstrumentRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=seed,
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 1},
        selected_design=selected,
        curve=curve,
    )
    record: dict[str, object] = {
        "schema_version": 1,
        "event_type": "day65_v2_instrument_result",
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "protocol_version": DAY65_V2_PROTOCOL,
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "instrument": f"openems-{suffix}",
        "curve": curve.model_dump(mode="json"),
    }
    _write_run(run_directory, summary, [record])
    return summary


def build_day65_v2_convergence(
    summaries: list[Day65V2InstrumentRunSummary],
) -> Day65V2ConvergenceDocument:
    """Apply the unchanged valid-resonance and three-percent movement rule."""

    if len(summaries) < 2:
        raise CrossCheckError("v2 convergence needs at least 1x and 2x")
    levels: list[Day65V2ConvergenceLevel] = []
    first_passing: float | None = None
    previous: Day65V2InstrumentRunSummary | None = None
    for summary in summaries:
        refinement = float(summary.config["openems_mesh_refinement"])
        shift = None if previous is None else high_band_shift(
            previous.curve, summary.curve
        )
        passed = (
            shift is not None and shift <= DAY6_OPENEMS_CONVERGENCE_THRESHOLD
        )
        if passed and first_passing is None:
            first_passing = refinement
        levels.append(
            Day65V2ConvergenceLevel(
                refinement=refinement,
                run_id=summary.run_id,
                simulation_time_seconds=summary.curve.simulation_time_seconds,
                high_band_shift_from_previous=shift,
                comparison_passed=passed,
            )
        )
        previous = summary
    selected = summaries[0].selected_design
    return Day65V2ConvergenceDocument(
        source_run_id=selected.source_run_id,
        source_step_index=selected.source_step_index,
        levels=tuple(levels),
        self_convergence_established=first_passing is not None,
        first_passing_refinement=first_passing,
    )


def write_day65_v2_convergence(
    repo_root: Path, document: Day65V2ConvergenceDocument
) -> None:
    """Write the source-specific convergence decision as LF-only JSON."""

    _write_json(repo_root / DAY65_V2_CONVERGENCE_FILE, document.model_dump(mode="json"))


def load_day65_v2_convergence(repo_root: Path) -> Day65V2ConvergenceDocument:
    """Load the frozen complete diagnostic before a final cross-check."""

    try:
        return Day65V2ConvergenceDocument.model_validate_json(
            (repo_root / DAY65_V2_CONVERGENCE_FILE).read_text(encoding="utf-8")
        )
    except OSError as error:
        raise CrossCheckError("Day 6.5 v2 convergence must run first") from error


def _load_reusable_openems_curve(
    repo_root: Path, selected: SelectedDay65Design
) -> tuple[SolverCurve, str] | None:
    run_id = "day65-freeform-v2-openems-convergence-top1-6x"
    path = repo_root / "runs" / run_id / "summary.json"
    if selected.rank != 1 or not path.is_file():
        return None
    summary = Day65V2InstrumentRunSummary.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    if summary.selected_design != selected:
        raise CrossCheckError("top-1 reusable 6x curve belongs to another design")
    return summary.curve, run_id


async def run_day65_v2_final(
    repo_root: Path, selected: SelectedDay65Design
) -> Day65V2CrossCheckRunSummary:
    """Run both released instruments and apply all unchanged discovery gates."""

    convergence = load_day65_v2_convergence(repo_root)
    run_id = f"day65-freeform-v2-final-crosscheck-top{selected.rank}"
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        return Day65V2CrossCheckRunSummary.model_validate_json(
            (run_directory / "summary.json").read_text(encoding="utf-8")
        )
    geometry, seed = reconstruct_day65_v2_design(repo_root, selected)
    started_at = datetime.now(UTC)
    nec2 = await _solve(geometry, run_id, "nec2")
    reused = _load_reusable_openems_curve(repo_root, selected)
    if reused is None:
        openems = await _solve(geometry, run_id, "openems")
        openems_source = None
    else:
        openems, openems_source = reused
    decision = evaluate_day6_curves(openems, nec2)
    reference_met = selected.source_base_score >= 1.10 * DAY65_OCFD_SCORE
    discovery = (
        "confirmed_improvement"
        if reference_met
        and convergence.self_convergence_established
        and decision.verdict == "CONFIRMED"
        else "insufficient_evidence"
    )
    config: dict[str, Any] = {
        "protocol_version": DAY65_V2_PROTOCOL,
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "source_geometry_hash": selected.source_geometry_hash,
        "frequency_range_hz": FREEFORM_SWEEP_HZ,
        "frequency_points": FREEFORM_FREQUENCY_POINTS,
        "nec2_segments_per_wavelength": DAY65_V2_NEC2_DENSITY,
        "nec2_timeout_seconds": 1800.0,
        "openems_mesh_refinement": DAY65_V2_OPENEMS_REFINEMENT,
        "openems_base_timesteps": DAY65_V2_OPENEMS_BASE_TIMESTEPS,
        "openems_timeout_seconds": DAY65_V2_OPENEMS_TIMEOUT_SECONDS,
        "openems_curve_source_run_id": openems_source,
        "high_band_self_convergence_established": (
            convergence.self_convergence_established
        ),
    }
    summary = Day65V2CrossCheckRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=seed,
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 2},
        selected_design=selected,
        nec2=nec2,
        openems=openems,
        openems_curve_source_run_id=openems_source,
        decision=decision,
        reference_gate_met=reference_met,
        high_band_self_convergence_established=(
            convergence.self_convergence_established
        ),
        discovery_verdict=discovery,
    )
    records = [
        {
            "schema_version": 1,
            "event_type": "day65_v2_cross_solver_result",
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "protocol_version": DAY65_V2_PROTOCOL,
            "source_run_id": selected.source_run_id,
            "source_step_index": selected.source_step_index,
            "instrument": "nec2-lambda160",
            "curve": nec2.model_dump(mode="json"),
        },
        {
            "schema_version": 1,
            "event_type": "day65_v2_cross_solver_result",
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "protocol_version": DAY65_V2_PROTOCOL,
            "source_run_id": selected.source_run_id,
            "source_step_index": selected.source_step_index,
            "instrument": "openems-6x-repaired",
            "instrument_source_run_id": openems_source,
            "curve": openems.model_dump(mode="json"),
        },
    ]
    _write_run(run_directory, summary, records)
    return summary


def frozen_day65_v2_candidates(
    repo_root: Path,
) -> tuple[SelectedDay65Design, SelectedDay65Design]:
    """Recompute and return exactly the two committed source-only candidates."""

    return load_day65_selection(repo_root).candidates
