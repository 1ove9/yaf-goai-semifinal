"""Native NEC2/openEMS verification for archived Day 4 meander designs."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yaf_ai.exploration.baselines import _proposal_from_parameters
from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve, _curve
from yaf_ai.exploration.cross_check_v2 import (
    CurveDecision,
    _canonical_hash,
    _load_anchor_gate,
)
from yaf_ai.exploration.cross_check_v21 import (
    PROTOCOL_VERSION,
    WIDEBAND_FREQUENCY_POINTS,
    WIDEBAND_FREQUENCY_RANGE_HZ,
    CurveDecisionV21,
    evaluate_curves_v21,
)
from yaf_ai.exploration.environment import ExplorationConfig, geometry_hash
from yaf_ai.exploration.logger import AuditStepRecord, RunSummary
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

TARGET_BAND_FREQUENCY_POINTS = 51


class SelectedWireDesign(BaseModel):
    """One source-addressed GP design selected without reranking by cross-check."""

    model_config = ConfigDict(frozen=True)

    rank: int = Field(gt=0)
    source_run_id: str
    source_config_hash: str
    source_geometry_hash: str
    source_score: float
    source_step_index: int = Field(default=0, ge=0)
    target_band_resonance_valid: bool = False
    classic_source_run_id: str
    classic_score: float
    oracle_improvement_fraction: float
    proposal_parameters: dict[str, float]
    proposer: str


class WireCrossCheckRunSummary(BaseModel):
    """Archive-compatible native-geometry verification of one selected design."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1, 2] = 2
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 2
    evaluation_budget: int = 2
    solver_mode_counts: dict[str, int]
    selected_design: SelectedWireDesign
    openems: SolverCurve
    nec2: SolverCurve
    decision: CurveDecisionV21 | CurveDecision


def _load_summary(path: Path) -> RunSummary:
    try:
        return RunSummary.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load archived wire run: {error}") from error


def select_top_gp_designs(
    repo_root: Path, *, batch_id: str = "day4-wire", count: int = 2
) -> tuple[SelectedWireDesign, ...]:
    """Select designs by the batch's preregistered, source-only ranking rule."""

    state_path = repo_root / "runs" / f"batch_{batch_id}" / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CrossCheckError(f"cannot load wire batch state: {error}") from error
    artifacts = repo_root / "artifacts" / "runs"
    classic = _load_summary(artifacts / f"{batch_id}-wifi24-classic-s0" / "summary.json")
    if not classic.top_designs:
        raise CrossCheckError("wire classic run has no design")
    classic_score = classic.top_designs[0].score
    candidates: list[tuple[RunSummary, AuditStepRecord, bool]] = []
    for raw in state.get("runs", []):
        if raw.get("agent") != "gp" or raw.get("status") != "completed":
            continue
        run_id = str(raw["run_id"])
        summary = _load_summary(artifacts / run_id / "summary.json")
        if not summary.top_designs:
            raise CrossCheckError(f"wire GP run {run_id} has no design")
        if batch_id.startswith("day5-wire-v6"):
            log_path = artifacts / run_id / "log.jsonl"
            try:
                records = tuple(
                    AuditStepRecord.model_validate_json(line)
                    for line in log_path.read_text(encoding="utf-8").splitlines()
                    if json.loads(line).get("event_type") == "evaluation"
                )
            except (OSError, ValidationError, json.JSONDecodeError) as error:
                raise CrossCheckError(
                    f"cannot read GP evidence log {run_id}: {error}"
                ) from error
            frequency_points = TARGET_BAND_FREQUENCY_POINTS
            for design in records:
                resonance_index = int(design.metrics["resonance_index"])
                valid = (
                    float(design.metrics["min_s11_db"]) <= -6.0
                    and 3 <= resonance_index < int(frequency_points) - 3
                )
                candidates.append((summary, design, valid))
        else:
            candidates.append((summary, summary.top_designs[0], False))
    if batch_id.startswith("day5-wire-v6"):
        candidates.sort(
            key=lambda item: (
                not item[2],
                -item[1].score,
                item[0].run_id,
                item[1].step_index,
            )
        )
        unique: list[tuple[RunSummary, AuditStepRecord, bool]] = []
        hashes: set[str] = set()
        for candidate in candidates:
            if candidate[1].geometry_hash in hashes:
                continue
            hashes.add(candidate[1].geometry_hash)
            unique.append(candidate)
        candidates = unique
    else:
        candidates.sort(key=lambda item: item[1].score, reverse=True)
    if len(candidates) < count:
        raise CrossCheckError(
            f"wire batch has only {len(candidates)} completed GP seed winners"
        )
    selected: list[SelectedWireDesign] = []
    for rank, (summary, design, valid) in enumerate(candidates[:count], start=1):
        if classic_score == 0.0:
            raise CrossCheckError("wire classic score is zero")
        selected.append(
            SelectedWireDesign(
                rank=rank,
                source_run_id=summary.run_id,
                source_config_hash=summary.config_hash,
                source_geometry_hash=design.geometry_hash,
                source_score=design.score,
                source_step_index=design.step_index,
                target_band_resonance_valid=valid,
                classic_source_run_id=classic.run_id,
                classic_score=classic_score,
                oracle_improvement_fraction=design.score / classic_score - 1.0,
                proposal_parameters=design.proposal_parameters,
                proposer=design.proposer,
            )
        )
    return tuple(selected)


def reconstruct_selected_design(
    repo_root: Path, selected: SelectedWireDesign
) -> tuple[ExplorationConfig, Geometry, int]:
    """Reconstruct and hash-check one archived GP centerline."""

    summary = _load_summary(
        repo_root
        / "artifacts"
        / "runs"
        / selected.source_run_id
        / "summary.json"
    )
    config = ExplorationConfig.model_validate(summary.config)
    proposal = _proposal_from_parameters(
        config, selected.proposal_parameters, selected.proposer
    )
    actual_hash = geometry_hash(proposal.geometry)
    if actual_hash != selected.source_geometry_hash:
        raise CrossCheckError(
            f"wire geometry hash mismatch expected={selected.source_geometry_hash} "
            f"actual={actual_hash}"
        )
    return config, proposal.geometry, summary.seed


def _write_run(
    run_directory: Path,
    summary: WireCrossCheckRunSummary,
) -> None:
    run_directory.mkdir(parents=True, exist_ok=False)
    records = [
        {
            "schema_version": 1,
            "event_type": "wire_cross_solver_result",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "protocol_version": PROTOCOL_VERSION,
            "selected_design": summary.selected_design.model_dump(mode="json"),
            "curve": curve.model_dump(mode="json"),
        }
        for curve in (summary.nec2, summary.openems)
    ]
    payload = "".join(
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
        for record in records
    )
    (run_directory / "log.jsonl").write_bytes(payload.encode("utf-8"))
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


async def run_wire_cross_check(
    repo_root: Path,
    selected: SelectedWireDesign,
    *,
    anchor_run_id: str = "day4-dipole-anchor",
    batch_id: str = "day4-wire",
    nec2_segments_per_wavelength: int = 20,
    openems_mesh_refinement: float = 1.0,
) -> WireCrossCheckRunSummary:
    """Rerun one selected native centerline in both real solvers."""

    _load_anchor_gate(repo_root, anchor_run_id)
    config, geometry, seed = reconstruct_selected_design(repo_root, selected)
    run_id = f"{batch_id}-crosscheck-top{selected.rank}"
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        raise CrossCheckError(f"wire cross-check run already exists: {run_id}")
    spec = SimulationSpec(
        name=run_id,
        frequency_range=WIDEBAND_FREQUENCY_RANGE_HZ,
        frequency_points=WIDEBAND_FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings={
            "nec2_segments_per_wavelength": nec2_segments_per_wavelength,
            "openems_mesh_refinement": openems_mesh_refinement,
        },
    )
    frozen_config = {
        "protocol_version": PROTOCOL_VERSION,
        "anchor_run_id": anchor_run_id,
        "source_run_id": selected.source_run_id,
        "source_config_hash": selected.source_config_hash,
        "source_geometry_hash": selected.source_geometry_hash,
        "proposal_parameters": selected.proposal_parameters,
        "frequency_range_hz": spec.frequency_range,
        "frequency_points": spec.frequency_points,
        "native_geometry": "shared_centerline",
        "nec2_segments_per_wavelength": nec2_segments_per_wavelength,
        "openems_mesh_refinement": openems_mesh_refinement,
    }
    started_at = datetime.now(UTC)
    curves: dict[str, SolverCurve] = {}
    for name, adapter in (
        ("nec2", NEC2Adapter()),
        ("openems", OpenEMSAdapter()),
    ):
        mesh = await adapter.mesh(geometry, spec)
        curve = _curve(await adapter.solve(mesh, spec))
        if curve.solver_mode != "subprocess":
            raise CrossCheckError(
                f"{name} wire cross-check is not real: {curve.solver_mode}"
            )
        curves[name] = curve
    decision = evaluate_curves_v21(curves["openems"], curves["nec2"])
    summary = WireCrossCheckRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=seed,
        config_hash=_canonical_hash(frozen_config),
        config=frozen_config,
        solver_mode_counts={"subprocess": 2},
        selected_design=selected,
        openems=curves["openems"],
        nec2=curves["nec2"],
        decision=decision,
    )
    _write_run(run_directory, summary)
    return summary
