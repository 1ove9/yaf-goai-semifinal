"""One-shot real openEMS 2x recheck after patch refinement propagation repair."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve, _curve
from yaf_ai.exploration.cross_check_v2 import _canonical_hash
from yaf_ai.exploration.patch_final_convergence import (
    OpenEMSRefinementRunSummary,
    _air_geometry,
    _read_model,
    _relative_shift,
    _source,
)
from yaf_ai.exploration.patch_final_protocol import (
    FREQUENCY_POINTS,
    FREQUENCY_RANGE_HZ,
    SOURCE_GEOMETRY_HASH,
    SOURCE_RUN_ID,
)
from yaf_ai.exploration.patch_mesh_audit import (
    ARCHIVED_REFINEMENT_RUN_ID,
    INTERPRETATION_NOTE,
    MESH_AUDIT_RUN_ID,
    MeshCountDecision,
    PatchMeshAuditSummary,
    PatchMeshStatistics,
    build_patch_xml,
    classify_mesh_ratio,
    parse_mesh_statistics,
)
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

MESH_RECHECK_RUN_ID = "day5-patch-final-openems-2x-mesh-recheck"
SELF_CONVERGENCE_THRESHOLD = 0.03
RecheckClaim = Literal[
    "established_after_refinement_repair", "self_convergence_not_established"
]


class PatchMeshRecheckSummary(BaseModel):
    """Archive-compatible one-shot solver result with corrected mesh evidence."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str = MESH_RECHECK_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 1
    evaluation_budget: int = 1
    solver_mode_counts: dict[str, int]
    source_run_id: str = SOURCE_RUN_ID
    source_geometry_hash: str = SOURCE_GEOMETRY_HASH
    pre_fix_audit_run_id: str = MESH_AUDIT_RUN_ID
    invalid_archived_refinement_run_id: str = ARCHIVED_REFINEMENT_RUN_ID
    refinement_1x_xml_unchanged: Literal[True] = True
    mesh_1x_after_fix: PatchMeshStatistics
    mesh_2x_after_fix: PatchMeshStatistics
    repaired_mesh_decision: MeshCountDecision
    predicted_seconds: float = Field(gt=0.0)
    actual_wall_seconds: float = Field(ge=0.0)
    baseline_curve: SolverCurve
    curve: SolverCurve
    resonance_shift: float = Field(ge=0.0)
    self_convergence_threshold: float = SELF_CONVERGENCE_THRESHOLD
    claim_status: RecheckClaim


def classify_recheck_shift(shift: float) -> RecheckClaim:
    """Apply the unchanged inclusive 3% self-convergence movement gate."""

    if shift < 0.0:
        raise ValueError("resonance shift must be nonnegative")
    if shift <= SELF_CONVERGENCE_THRESHOLD:
        return "established_after_refinement_repair"
    return "self_convergence_not_established"


def _write_run(directory: Path, summary: PatchMeshRecheckSummary) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    events = [
        {
            "schema_version": 1,
            "event_type": "patch_mesh_repair_verification",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "mesh_1x": summary.mesh_1x_after_fix.model_dump(mode="json"),
            "mesh_2x": summary.mesh_2x_after_fix.model_dump(mode="json"),
            "mesh_decision": summary.repaired_mesh_decision.model_dump(mode="json"),
        },
        {
            "schema_version": 1,
            "event_type": "patch_openems_2x_recheck",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "actual_wall_seconds": summary.actual_wall_seconds,
            "resonance_shift": summary.resonance_shift,
            "claim_status": summary.claim_status,
            "curve": summary.curve.model_dump(mode="json"),
        },
    ]
    log = "".join(
        json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
        for event in events
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


async def run_patch_mesh_recheck(repo_root: Path) -> PatchMeshRecheckSummary:
    """Verify the repair and execute the single authorized real 2x solver run."""

    run_directory = repo_root / "runs" / MESH_RECHECK_RUN_ID
    if run_directory.exists():
        raise CrossCheckError(f"mesh recheck run already exists: {MESH_RECHECK_RUN_ID}")
    audit = _read_model(
        repo_root / "artifacts" / "runs" / MESH_AUDIT_RUN_ID / "summary.json",
        PatchMeshAuditSummary,
    )
    if not audit.decision.requires_part2:
        raise CrossCheckError("pre-fix audit does not authorize a Part 2 recheck")
    xml_1x, seed_1x = await build_patch_xml(repo_root, 1.0)
    mesh_1x = parse_mesh_statistics(xml_1x, 1.0)
    if mesh_1x.xml_sha256 != audit.mesh_1x.xml_sha256:
        raise CrossCheckError("refinement=1.0 XML changed during the propagation repair")

    source = _source(repo_root)
    geometry, seed_2x = _air_geometry(repo_root, source)
    if seed_1x != seed_2x:
        raise CrossCheckError("mesh repair verification returned inconsistent seeds")
    spec = SimulationSpec(
        name=MESH_RECHECK_RUN_ID,
        frequency_range=FREQUENCY_RANGE_HZ,
        frequency_points=FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings={"openems_mesh_refinement": 2.0},
    )
    adapter = OpenEMSAdapter()
    mesh = await adapter.mesh(geometry, spec)
    xml_2x, _impedance = adapter._build_sim_xml(mesh, spec)
    mesh_2x = parse_mesh_statistics(xml_2x, 2.0)
    mesh_decision = classify_mesh_ratio(mesh_2x.total_cells / mesh_1x.total_cells)
    if mesh_2x.xml_sha256 == audit.mesh_2x.xml_sha256:
        raise CrossCheckError("repaired 2x XML still equals the ineffective archived XML")

    archived = _read_model(
        repo_root
        / "artifacts"
        / "runs"
        / ARCHIVED_REFINEMENT_RUN_ID
        / "summary.json",
        OpenEMSRefinementRunSummary,
    )
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    curve = _curve(await adapter.solve(mesh, spec))
    wall = time.perf_counter() - started
    if curve.solver_mode != "subprocess":
        raise CrossCheckError(f"repaired openEMS 2x used {curve.solver_mode}")
    shift = _relative_shift(
        archived.baseline_curve.resonance_frequency_hz,
        curve.resonance_frequency_hz,
    )
    claim = classify_recheck_shift(shift)
    config = {
        "execution_note": INTERPRETATION_NOTE,
        "pre_fix_audit_run_id": MESH_AUDIT_RUN_ID,
        "invalid_archived_refinement_run_id": ARCHIVED_REFINEMENT_RUN_ID,
        "source_run_id": SOURCE_RUN_ID,
        "source_geometry_hash": SOURCE_GEOMETRY_HASH,
        "frequency_range_hz": FREQUENCY_RANGE_HZ,
        "frequency_points": FREQUENCY_POINTS,
        "refinement": 2.0,
        "self_convergence_threshold": SELF_CONVERGENCE_THRESHOLD,
        "refinement_1x_xml_sha256": mesh_1x.xml_sha256,
        "refinement_2x_xml_sha256": mesh_2x.xml_sha256,
    }
    summary = PatchMeshRecheckSummary(
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=seed_1x,
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 1},
        mesh_1x_after_fix=mesh_1x,
        mesh_2x_after_fix=mesh_2x,
        repaired_mesh_decision=mesh_decision,
        predicted_seconds=archived.predicted_seconds,
        actual_wall_seconds=wall,
        baseline_curve=archived.baseline_curve,
        curve=curve,
        resonance_shift=shift,
        claim_status=claim,
    )
    _write_run(run_directory, summary)
    return summary
