"""Mesh-only audit of the archived Day 5-2 openEMS refinement claim."""

from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.cross_check_v2 import _canonical_hash
from yaf_ai.exploration.patch_final_convergence import (
    OpenEMSRefinementRunSummary,
    _air_geometry,
    _read_model,
    _source,
)
from yaf_ai.exploration.patch_final_protocol import (
    FREQUENCY_POINTS,
    FREQUENCY_RANGE_HZ,
    SOURCE_GEOMETRY_HASH,
    SOURCE_RUN_ID,
)
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

MESH_AUDIT_RUN_ID = "day5-patch-final-mesh-count-audit"
ARCHIVED_REFINEMENT_RUN_ID = "day5-patch-final-openems-2x"
INTERPRETATION_NOTE = "docs/patch-mesh-count-execution-note.md"
PARTIAL_RATIO = 1.2
EFFECTIVE_RATIO = 3.0

MeshInterpretation = Literal["effective", "partially_supported", "ineffective"]
ClaimStatus = Literal[
    "established_with_mesh_evidence",
    "partially_supported",
    "self_convergence_not_established",
]


class MeshAxisStatistics(BaseModel):
    """Grid-line and adjacent-cell statistics for one Cartesian axis."""

    model_config = ConfigDict(frozen=True)

    line_count: int = Field(ge=2)
    cell_count: int = Field(ge=1)
    minimum_cell_size_m: float = Field(gt=0.0)
    maximum_cell_size_m: float = Field(gt=0.0)


class PatchMeshStatistics(BaseModel):
    """Auditable statistics parsed from one complete simulation XML."""

    model_config = ConfigDict(frozen=True)

    refinement: float = Field(gt=0.0)
    x: MeshAxisStatistics
    y: MeshAxisStatistics
    z: MeshAxisStatistics
    total_cells: int = Field(ge=1)
    xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MeshCountDecision(BaseModel):
    """Frozen interpretation of the 2x-to-1x total-cell ratio."""

    model_config = ConfigDict(frozen=True)

    total_cell_ratio: float = Field(gt=0.0)
    interpretation: MeshInterpretation
    claim_status: ClaimStatus
    requires_part2: bool


class PatchMeshAuditSummary(BaseModel):
    """Archive-compatible evidence from two XML builds and no solver call."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str = MESH_AUDIT_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 2
    evaluation_budget: int = 0
    solver_mode_counts: dict[str, int]
    source_run_id: str = SOURCE_RUN_ID
    source_geometry_hash: str = SOURCE_GEOMETRY_HASH
    archived_refinement_run_id: str = ARCHIVED_REFINEMENT_RUN_ID
    archived_resonance_shift: float = Field(ge=0.0)
    mesh_1x: PatchMeshStatistics
    mesh_2x: PatchMeshStatistics
    decision: MeshCountDecision


def classify_mesh_ratio(ratio: float) -> MeshCountDecision:
    """Apply the frozen inclusive 1.2 and 3.0 interpretation boundaries."""

    if ratio <= 0.0:
        raise ValueError("mesh cell ratio must be positive")
    if ratio >= EFFECTIVE_RATIO:
        return MeshCountDecision(
            total_cell_ratio=ratio,
            interpretation="effective",
            claim_status="established_with_mesh_evidence",
            requires_part2=False,
        )
    if ratio >= PARTIAL_RATIO:
        return MeshCountDecision(
            total_cell_ratio=ratio,
            interpretation="partially_supported",
            claim_status="partially_supported",
            requires_part2=True,
        )
    return MeshCountDecision(
        total_cell_ratio=ratio,
        interpretation="ineffective",
        claim_status="self_convergence_not_established",
        requires_part2=True,
    )


def _axis_statistics(grid: ET.Element, tag: str) -> MeshAxisStatistics:
    element = grid.find(tag)
    if element is None or element.text is None:
        raise CrossCheckError(f"simulation XML lacks {tag}")
    try:
        lines = sorted({float(item) for item in element.text.split(",")})
    except ValueError as error:
        raise CrossCheckError(f"simulation XML has invalid {tag}") from error
    if len(lines) < 2:
        raise CrossCheckError(f"simulation XML has fewer than two {tag}")
    if element.get("Qty") != str(len(lines)):
        raise CrossCheckError(f"simulation XML {tag} Qty does not match its values")
    cells = [
        right - left for left, right in zip(lines, lines[1:], strict=False)
    ]
    if any(size <= 0.0 for size in cells):
        raise CrossCheckError(f"simulation XML {tag} is not strictly increasing")
    return MeshAxisStatistics(
        line_count=len(lines),
        cell_count=len(cells),
        minimum_cell_size_m=min(cells),
        maximum_cell_size_m=max(cells),
    )


def parse_mesh_statistics(xml_bytes: bytes, refinement: float) -> PatchMeshStatistics:
    """Parse grid counts and sizes without changing or executing the XML."""

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        raise CrossCheckError(f"invalid openEMS XML: {error}") from error
    grid = root.find("./ContinuousStructure/RectilinearGrid")
    if grid is None:
        raise CrossCheckError("simulation XML lacks RectilinearGrid")
    x = _axis_statistics(grid, "XLines")
    y = _axis_statistics(grid, "YLines")
    z = _axis_statistics(grid, "ZLines")
    return PatchMeshStatistics(
        refinement=refinement,
        x=x,
        y=y,
        z=z,
        total_cells=x.cell_count * y.cell_count * z.cell_count,
        xml_sha256=hashlib.sha256(xml_bytes).hexdigest(),
    )


async def build_patch_xml(
    repo_root: Path, refinement: float
) -> tuple[bytes, int]:
    """Reconstruct the frozen air variant and build, but never solve, its XML."""

    source = _source(repo_root)
    geometry, seed = _air_geometry(repo_root, source)
    spec = SimulationSpec(
        name=f"{MESH_AUDIT_RUN_ID}-{refinement:g}x",
        frequency_range=FREQUENCY_RANGE_HZ,
        frequency_points=FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings={"openems_mesh_refinement": refinement},
    )
    adapter = OpenEMSAdapter()
    mesh = await adapter.mesh(geometry, spec)
    xml_bytes, _impedance = adapter._build_sim_xml(mesh, spec)
    return xml_bytes, seed


def _write_run(directory: Path, summary: PatchMeshAuditSummary) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    events = [
        {
            "schema_version": 1,
            "event_type": "patch_mesh_count",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "mesh": mesh.model_dump(mode="json"),
        }
        for mesh in (summary.mesh_1x, summary.mesh_2x)
    ]
    events.append(
        {
            "schema_version": 1,
            "event_type": "patch_mesh_interpretation",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "decision": summary.decision.model_dump(mode="json"),
        }
    )
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


async def run_patch_mesh_audit(repo_root: Path) -> PatchMeshAuditSummary:
    """Build both diagnostic XMLs once, classify them, and persist the result."""

    run_directory = repo_root / "runs" / MESH_AUDIT_RUN_ID
    if run_directory.exists():
        raise CrossCheckError(f"mesh audit run already exists: {MESH_AUDIT_RUN_ID}")
    started_at = datetime.now(UTC)
    xml_1x, seed_1x = await build_patch_xml(repo_root, 1.0)
    xml_2x, seed_2x = await build_patch_xml(repo_root, 2.0)
    if seed_1x != seed_2x:
        raise CrossCheckError("mesh audit reconstruction returned inconsistent seeds")
    mesh_1x = parse_mesh_statistics(xml_1x, 1.0)
    mesh_2x = parse_mesh_statistics(xml_2x, 2.0)
    decision = classify_mesh_ratio(mesh_2x.total_cells / mesh_1x.total_cells)
    archived = _read_model(
        repo_root
        / "artifacts"
        / "runs"
        / ARCHIVED_REFINEMENT_RUN_ID
        / "summary.json",
        OpenEMSRefinementRunSummary,
    )
    config = {
        "execution_note": INTERPRETATION_NOTE,
        "source_run_id": SOURCE_RUN_ID,
        "source_geometry_hash": SOURCE_GEOMETRY_HASH,
        "frequency_range_hz": FREQUENCY_RANGE_HZ,
        "frequency_points": FREQUENCY_POINTS,
        "refinements": (1.0, 2.0),
        "partially_supported_ratio": PARTIAL_RATIO,
        "effective_ratio": EFFECTIVE_RATIO,
        "solver_invoked": False,
    }
    summary = PatchMeshAuditSummary(
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=seed_1x,
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"xml_build_only": 2},
        archived_resonance_shift=archived.adjacent_resonance_shift,
        mesh_1x=mesh_1x,
        mesh_2x=mesh_2x,
        decision=decision,
    )
    _write_run(run_directory, summary)
    return summary
