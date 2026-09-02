"""Terminal rod-r2 harness repair and frozen 5.8 GHz qualification.

The r2 sequence is intentionally self-contained.  It first executes the
pre-registered ten-step legacy/repaired probe A/B check.  Only a passing
repair gate can dispatch the unchanged NEC2 plus openEMS 1x/2x/4x/8x
scientific ladder.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve, _curve
from yaf_ai.exploration.cross_check_v2 import (
    ANCHOR_CORRELATION_THRESHOLD,
    ANCHOR_RESONANCE_THRESHOLD,
)
from yaf_ai.exploration.patch_mesh_audit import parse_mesh_statistics
from yaf_ai.exploration.semifinal_anchor import (
    MEMORY_POLL_SECONDS,
    _curve_from_spectra,
    _process_tree_rss_bytes,
    _spec,
    _terminate_process_tree,
)
from yaf_ai.exploration.semifinal_anchor_r2 import (
    R2_FREQUENCY_POINTS,
    R2_GEOMETRY_SHA256,
    R2_SWEEP_HZ,
    semifinal_anchor_r2_geometry,
    validate_semifinal_anchor_r2_geometry,
)
from yaf_ai.exploration.semifinal_anchor_r3 import (
    RichardsonEstimate,
    richardson_estimate,
)
from yaf_ai.exploration.semifinal_rod_anchor import (
    BUILD_ONLY_RELATIVE_PATH as ROD_R1_BUILD_ONLY_RELATIVE_PATH,
)
from yaf_ai.exploration.semifinal_rod_anchor import (
    LEGACY_R3_1X_XML_SHA256,
    ROD_AGREEMENT_REFINEMENT,
    ROD_CONVERGENCE_PAIR,
    ROD_CONVERGENCE_THRESHOLD,
    ROD_RADIUS_M,
    ROD_REFINEMENTS,
    ROD_REPRESENTATION,
    ROD_TIMEOUT_SECONDS,
    NEC2Reproduction,
    RetrospectiveRadiusDiagnostic,
    RodAnchorDecision,
    RodMeshDisclosure,
    RodOpenEMSResult,
    _load_r3_summary,
    _mesh,
    _rod_spec,
    build_rod_disclosures,
    evaluate_rod_anchor,
    parse_termination,
    retrospective_radius_diagnostic,
)
from yaf_ai.exploration.semifinal_rod_anchor import (
    ROD_RUN_ID as ROD_R1_RUN_ID,
)
from yaf_core.domain.geometry import Geometry
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter
from yaf_solvers.openems_adapter.port_parser import (
    OpenEMSParseError,
    calc_port,
    read_probe,
)

ROD_R2_PROTOCOL = "semifinal-wifi58-rod-renderer-anchor-r2"
ROD_R2_RUN_ID = f"{ROD_R2_PROTOCOL}-combined"
ROD_R2_PREREGISTRATION_COMMIT = "905efdb"
ROD_R2_BUILD_ONLY_RELATIVE_PATH = (
    "artifacts/analysis/semifinal-wifi58-rod-renderer-anchor-r2/build-only.json"
)
ROD_R2_DIAGNOSTIC_MAXIMUM_TIMESTEPS = 10
ROD_R2_OFFICIAL_ADD_LUMPED_PORT_SOURCE = r"C:\opt\openEMS\matlab\AddLumpedPort.m"
ROD_R2_OFFICIAL_ADD_LUMPED_PORT_SOURCE_SHA256 = (
    "9384e5eb78dbb3998d3e9b75662b9be29e9c18b6681beacf973c102f89b4ced9"
)
ROD_R1_LOG_SHA256 = "39414489ba7b34f8b94526f03c657741ce879b2d521a4061df58b93b802c699f"
ROD_R1_SUMMARY_SHA256 = "152710277aa5f8b4586185a0a00fd77d2d0d1ebf9907d3b130fe0e0972a06d0e"
ROD_R1_BUILD_ONLY_SHA256 = "388e32317e6c97525fdb2e759b14bdfc212c75e8f9b320cc733a22cb3b4c409f"
ROD_R1_PREREGISTRATION_SHA256 = "9294229d8ac05bac34964783bd739b247d90b76ffe6d294135591cefc85b9b6d"
ROD_R1_XML_SHA256_BY_REFINEMENT: tuple[tuple[float, str], ...] = (
    (
        1.0,
        "bf6706ccfe2be6543f407fc0a15621bc4f14c826054b8c76d9e228cd5c2153bc",
    ),
    (
        2.0,
        "2436998a324e56d02ed8a62f39e12b38e2ea93a08b386831c307115c1eff0242",
    ),
    (
        4.0,
        "55f0ad0d87cbdb00783311cdcf30361b6783e01b2c9ccfad34a83e5d2e4771a4",
    ),
    (
        8.0,
        "32c8748a4c5978d198c7865dd7f48e2f79096cb3bbb67040236343092ce88a34",
    ),
)
ROD_R2_REPAIRED_XML_SHA256_BY_REFINEMENT: tuple[tuple[float, str], ...] = (
    (1.0, "32f4fe9ba7874429de0c96f0ce6768fba23590fffa4237a8b4458427b1dbb974"),
    (2.0, "fe6528c10c80bfb05ec0be3a2e360a0abdf9c70de99487806f16abdb102b6b31"),
    (4.0, "9c9489a2ef42925750dc7b5faba44f12fc754308fe01f46952c469e175787f61"),
    (8.0, "9033129f1a5045d846dc33f6c85b45c9183648ed4478d467b89e0c6e590d3be9"),
)
ROD_R2_LEGACY_DIAGNOSTIC_XML_SHA256 = (
    "967179fc1e62d51c4e3090885f22c3346b2476d0b2954435f5be9b9a5bec5853"
)
ROD_R2_REPAIRED_DIAGNOSTIC_XML_SHA256 = (
    "36d7e73684a3007f87aaf2a904112a1e46ea9e52980cfa3eb147435a9e39650d"
)

Sha256 = str
DiagnosticLabel = Literal["legacy_a", "repaired_b"]


class RodXmlIdentity(BaseModel):
    """Byte and normalized-tree identity for one rod ladder level."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    refinement: float = Field(gt=0.0)
    legacy_xml_sha256: Sha256
    repaired_xml_sha256: Sha256
    identical_except_probe_bounds: bool


class RepairDiagnosticXmlDisclosure(BaseModel):
    """No-solve identity record for the frozen ten-step A/B pair."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    maximum_timesteps: int = ROD_R2_DIAGNOSTIC_MAXIMUM_TIMESTEPS
    legacy_full_xml_sha256: Sha256
    repaired_full_xml_sha256: Sha256
    legacy_diagnostic_xml_sha256: Sha256
    repaired_diagnostic_xml_sha256: Sha256
    full_xml_identical_except_probe_bounds: bool
    diagnostic_xml_identical_except_probe_bounds: bool
    legacy_derivation_changed_only_timesteps: bool
    repaired_derivation_changed_only_timesteps: bool


class RodR2BuildOnlyDisclosure(BaseModel):
    """Independent deterministic build-only schema for rod-r2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    protocol_version: str = ROD_R2_PROTOCOL
    preregistration_commit: str = ROD_R2_PREREGISTRATION_COMMIT
    solver_invoked: bool = False
    geometry_hash: str = R2_GEOMETRY_SHA256
    official_add_lumped_port_source_sha256: str = ROD_R2_OFFICIAL_ADD_LUMPED_PORT_SOURCE_SHA256
    legacy_xml_sha256: str = LEGACY_R3_1X_XML_SHA256
    legacy_dt_proxy_seconds: float = Field(gt=0.0)
    target_physical_time_seconds: float = Field(gt=0.0)
    refinements: tuple[
        RodMeshDisclosure,
        RodMeshDisclosure,
        RodMeshDisclosure,
        RodMeshDisclosure,
    ]
    xml_identities: tuple[
        RodXmlIdentity,
        RodXmlIdentity,
        RodXmlIdentity,
        RodXmlIdentity,
    ]
    diagnostic_xml: RepairDiagnosticXmlDisclosure


class OutputFileEvidence(BaseModel):
    """One immutable file in a diagnostic scratch-directory inventory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relative_path: str
    byte_size: int = Field(ge=0)
    sha256: Sha256


class ProbeEvidence(BaseModel):
    """Existence and sample completeness of one openEMS time probe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    exists: bool
    byte_size: int | None = Field(default=None, ge=0)
    sha256: Sha256 | None
    parseable_sample_count: int = Field(ge=0)
    parse_error: str | None


class DiagnosticExecution(BaseModel):
    """Complete process and output evidence for diagnostic A or B."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: DiagnosticLabel
    maximum_timesteps: int = ROD_R2_DIAGNOSTIC_MAXIMUM_TIMESTEPS
    xml_sha256: Sha256
    launched: bool
    exit_code: int | None
    timed_out: bool
    normal_exit: bool
    process_error: str | None
    elapsed_seconds: float = Field(ge=0.0)
    stdout_text: str
    stderr_text: str
    stdout_sha256: Sha256
    stderr_sha256: Sha256
    output_files: tuple[OutputFileEvidence, ...]
    voltage_probe: ProbeEvidence
    current_probe: ProbeEvidence


class RepairDiagnosticEvidence(BaseModel):
    """Frozen A/B execution and the deterministic repair-gate decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    xml: RepairDiagnosticXmlDisclosure
    legacy_a: DiagnosticExecution
    repaired_b: DiagnosticExecution
    gate_passed: bool
    failure_reasons: tuple[str, ...]
    s11_evaluated: bool = False


class RodR2OpenEMSResult(RodOpenEMSResult):
    """Rod result extended with the full stderr required by r2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stderr_text: str
    stderr_sha256: Sha256


class RodR2ExecutionFailure(BaseModel):
    """Terminal scientific execution failure outside the verdict space."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    failure_type: str
    refinement: float | None = Field(default=None, gt=0.0)
    message: str
    stdout_tail: tuple[str, ...]
    stderr_text: str
    stderr_sha256: Sha256
    scientific_verdict: None = None
    anchor_released: bool = False


class RodR2RepairNotConfirmedSummary(BaseModel):
    """Archive-compatible terminal preflight result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    result_status: Literal["repair_not_confirmed"] = "repair_not_confirmed"
    run_id: str = ROD_R2_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = Field(ge=0, le=2)
    evaluation_budget: int = 7
    solver_mode_counts: dict[str, int]
    geometry_hash: str
    geometry: dict[str, Any]
    build_only: RodR2BuildOnlyDisclosure
    repair_diagnostic: RepairDiagnosticEvidence
    failure_type: Literal["repair_not_confirmed"] = "repair_not_confirmed"
    scientific_verdict: None = None
    verdict: None = None
    anchor_released: bool = False


class RodR2ExecutionFailureSummary(BaseModel):
    """Archive-compatible failure after the repair gate passed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    result_status: Literal["execution_failed"] = "execution_failed"
    run_id: str = ROD_R2_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = Field(ge=2, le=6)
    evaluation_budget: int = 7
    solver_mode_counts: dict[str, int]
    geometry_hash: str
    geometry: dict[str, Any]
    build_only: RodR2BuildOnlyDisclosure
    repair_diagnostic: RepairDiagnosticEvidence
    nec2: SolverCurve | None
    completed_openems: tuple[RodR2OpenEMSResult, ...]
    failure: RodR2ExecutionFailure
    scientific_verdict: None = None
    verdict: None = None
    anchor_released: bool = False


class RodR2AnchorSummary(BaseModel):
    """Archive-compatible completed rod-r2 qualification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    result_status: Literal["completed"] = "completed"
    run_id: str = ROD_R2_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 7
    evaluation_budget: int = 7
    solver_mode_counts: dict[str, int]
    geometry_hash: str
    geometry: dict[str, Any]
    build_only: RodR2BuildOnlyDisclosure
    repair_diagnostic: RepairDiagnosticEvidence
    nec2: SolverCurve
    openems_1x: RodR2OpenEMSResult
    openems_2x: RodR2OpenEMSResult
    openems_4x: RodR2OpenEMSResult
    openems_8x: RodR2OpenEMSResult
    decision: RodAnchorDecision
    richardson_estimate: RichardsonEstimate
    nec2_reproduction: NEC2Reproduction
    radius_diagnostic: RetrospectiveRadiusDiagnostic


RodR2RunSummary = RodR2RepairNotConfirmedSummary | RodR2ExecutionFailureSummary | RodR2AnchorSummary


@dataclass(frozen=True)
class RodR2DiagnosticXmlPair:
    """In-memory XML bytes; persisted evidence stores only their hashes."""

    legacy_full_xml: bytes
    repaired_full_xml: bytes
    legacy_diagnostic_xml: bytes
    repaired_diagnostic_xml: bytes
    disclosure: RepairDiagnosticXmlDisclosure


class _RodR2LevelError(RuntimeError):
    def __init__(
        self,
        failure_type: str,
        message: str,
        *,
        refinement: float | None = None,
        stdout_tail: tuple[str, ...] = (),
        stderr_text: str = "",
    ) -> None:
        super().__init__(message)
        self.record = RodR2ExecutionFailure(
            failure_type=failure_type,
            refinement=refinement,
            message=message,
            stdout_tail=stdout_tail,
            stderr_text=stderr_text,
            stderr_sha256=_sha256(stderr_text.encode("utf-8")),
        )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _canonical_hash(payload: object) -> str:
    return _sha256(_canonical_bytes(payload))


def _serialize_xml(root: ET.Element) -> bytes:
    return bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


def _box_for_property(root: ET.Element, tag: str, name: str) -> ET.Element:
    element = root.find(f".//{tag}[@Name='{name}']/Primitives/Box")
    if element is None:
        raise CrossCheckError(f"XML lacks {tag} {name!r} box")
    return element


def _points(box: ET.Element) -> tuple[ET.Element, ET.Element]:
    p1 = box.find("P1")
    p2 = box.find("P2")
    if p1 is None or p2 is None:
        raise CrossCheckError("XML box lacks P1 or P2")
    return p1, p2


def _coordinates(point: ET.Element) -> tuple[float, float, float]:
    try:
        return tuple(float(point.attrib[name]) for name in ("X", "Y", "Z"))  # type: ignore[return-value]
    except (KeyError, ValueError) as error:
        raise CrossCheckError("XML point has invalid coordinates") from error


def _set_coordinates(point: ET.Element, values: tuple[float, float, float]) -> None:
    for name, value in zip(("X", "Y", "Z"), values, strict=True):
        point.set(name, f"{value:.12g}")


def _legacy_probe_xml(repaired_xml: bytes) -> bytes:
    """Recreate only the pre-repair probe bounds for diagnostic A."""

    try:
        root = ET.fromstring(repaired_xml)
    except ET.ParseError as error:
        raise CrossCheckError(f"invalid repaired rod XML: {error}") from error
    resistance_box = _box_for_property(root, "LumpedElement", "port_resist_1")
    start_element, stop_element = _points(resistance_box)
    start = _coordinates(start_element)
    stop = _coordinates(stop_element)
    voltage_box = _box_for_property(root, "ProbeBox", "port_ut_1")
    voltage_start, voltage_stop = _points(voltage_box)
    _set_coordinates(voltage_start, start)
    _set_coordinates(voltage_stop, stop)
    midpoint = (
        (start[0] + stop[0]) / 2.0,
        (start[1] + stop[1]) / 2.0,
        (start[2] + stop[2]) / 2.0,
    )
    current_box = _box_for_property(root, "ProbeBox", "port_it_1")
    current_start, current_stop = _points(current_box)
    _set_coordinates(current_start, midpoint)
    _set_coordinates(current_stop, midpoint)
    return _serialize_xml(root)


def _normalized_probe_bounds(xml_bytes: bytes) -> bytes:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        raise CrossCheckError(f"invalid rod XML: {error}") from error
    for name in ("port_ut_1", "port_it_1"):
        box = _box_for_property(root, "ProbeBox", name)
        for point in _points(box):
            for axis in ("X", "Y", "Z"):
                point.set(axis, "<frozen-probe-bound>")
    return _serialize_xml(root)


def _with_maximum_timesteps(xml_bytes: bytes, maximum_timesteps: int) -> bytes:
    if maximum_timesteps <= 0:
        raise ValueError("maximum_timesteps must be positive")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        raise CrossCheckError(f"invalid rod XML: {error}") from error
    fdtd = root.find("./FDTD")
    if fdtd is None or "NumberOfTimesteps" not in fdtd.attrib:
        raise CrossCheckError("rod XML lacks NumberOfTimesteps")
    fdtd.set("NumberOfTimesteps", str(maximum_timesteps))
    return _serialize_xml(root)


def _normalized_timesteps(xml_bytes: bytes) -> bytes:
    root = ET.fromstring(xml_bytes)
    fdtd = root.find("./FDTD")
    if fdtd is None or "NumberOfTimesteps" not in fdtd.attrib:
        raise CrossCheckError("rod XML lacks NumberOfTimesteps")
    fdtd.set("NumberOfTimesteps", "<frozen-timestep-count>")
    return _serialize_xml(root)


def _require_frozen_geometry(geometry: Geometry) -> str:
    digest = validate_semifinal_anchor_r2_geometry(geometry)
    if digest != R2_GEOMETRY_SHA256:
        raise CrossCheckError("rod-r2 geometry differs from the frozen r2 geometry")
    if geometry.metadata.get("wire_radius_m") != ROD_RADIUS_M:
        raise CrossCheckError("rod-r2 radius differs from the frozen value")
    return digest


def _expected_r1_xml_hash(refinement: float) -> str:
    for frozen_refinement, digest in ROD_R1_XML_SHA256_BY_REFINEMENT:
        if refinement == frozen_refinement:
            return digest
    raise CrossCheckError(f"unexpected rod refinement {refinement:g}x")


def _expected_repaired_xml_hash(refinement: float) -> str:
    for frozen_refinement, digest in ROD_R2_REPAIRED_XML_SHA256_BY_REFINEMENT:
        if refinement == frozen_refinement:
            return digest
    raise CrossCheckError(f"unexpected repaired rod refinement {refinement:g}x")


def _repaired_xml(
    geometry: Geometry,
    disclosure: RodMeshDisclosure,
    *,
    run_id: str,
) -> bytes:
    _require_frozen_geometry(geometry)
    adapter = OpenEMSAdapter()
    spec = _rod_spec(
        f"{run_id}-openems-{disclosure.refinement:g}x",
        disclosure.refinement,
        disclosure.maximum_timesteps,
    )
    xml_bytes, _ = adapter._build_sim_xml(_mesh(geometry, run_id), spec)
    return xml_bytes


def build_repair_diagnostic_xml_pair(
    geometry: Geometry,
    one_x: RodMeshDisclosure,
) -> RodR2DiagnosticXmlPair:
    """Build and byte-gate the full-duration and ten-step A/B XML pair."""

    if one_x.refinement != 1.0:
        raise ValueError("repair diagnostic requires the 1x disclosure")
    repaired_full = _repaired_xml(geometry, one_x, run_id=ROD_R1_RUN_ID)
    repaired_full_hash = _sha256(repaired_full)
    if repaired_full_hash != one_x.mesh.xml_sha256:
        raise CrossCheckError("repaired 1x XML differs from its mesh disclosure")
    legacy_full = _legacy_probe_xml(repaired_full)
    legacy_full_hash = _sha256(legacy_full)
    expected_legacy_hash = _expected_r1_xml_hash(1.0)
    if legacy_full_hash != expected_legacy_hash:
        raise CrossCheckError("legacy diagnostic builder does not reproduce rod-r1")
    full_identity = _normalized_probe_bounds(legacy_full) == _normalized_probe_bounds(repaired_full)
    if not full_identity:
        raise CrossCheckError("full A/B XML differs beyond the two probe bounds")
    legacy_diagnostic = _with_maximum_timesteps(legacy_full, ROD_R2_DIAGNOSTIC_MAXIMUM_TIMESTEPS)
    repaired_diagnostic = _with_maximum_timesteps(
        repaired_full, ROD_R2_DIAGNOSTIC_MAXIMUM_TIMESTEPS
    )
    if _sha256(legacy_diagnostic) != ROD_R2_LEGACY_DIAGNOSTIC_XML_SHA256:
        raise CrossCheckError("legacy ten-step diagnostic XML SHA-256 changed")
    if _sha256(repaired_diagnostic) != ROD_R2_REPAIRED_DIAGNOSTIC_XML_SHA256:
        raise CrossCheckError("repaired ten-step diagnostic XML SHA-256 changed")
    legacy_steps_only = _normalized_timesteps(legacy_full) == _normalized_timesteps(
        legacy_diagnostic
    )
    repaired_steps_only = _normalized_timesteps(repaired_full) == _normalized_timesteps(
        repaired_diagnostic
    )
    diagnostic_identity = _normalized_probe_bounds(legacy_diagnostic) == _normalized_probe_bounds(
        repaired_diagnostic
    )
    if not legacy_steps_only or not repaired_steps_only:
        raise CrossCheckError("diagnostic derivation changed more than timesteps")
    if not diagnostic_identity:
        raise CrossCheckError("diagnostic A/B XML differs beyond probe bounds")
    disclosure = RepairDiagnosticXmlDisclosure(
        legacy_full_xml_sha256=legacy_full_hash,
        repaired_full_xml_sha256=repaired_full_hash,
        legacy_diagnostic_xml_sha256=_sha256(legacy_diagnostic),
        repaired_diagnostic_xml_sha256=_sha256(repaired_diagnostic),
        full_xml_identical_except_probe_bounds=full_identity,
        diagnostic_xml_identical_except_probe_bounds=diagnostic_identity,
        legacy_derivation_changed_only_timesteps=legacy_steps_only,
        repaired_derivation_changed_only_timesteps=repaired_steps_only,
    )
    return RodR2DiagnosticXmlPair(
        legacy_full_xml=legacy_full,
        repaired_full_xml=repaired_full,
        legacy_diagnostic_xml=legacy_diagnostic,
        repaired_diagnostic_xml=repaired_diagnostic,
        disclosure=disclosure,
    )


def build_rod_r2_disclosure(
    geometry: Geometry | None = None,
) -> RodR2BuildOnlyDisclosure:
    """Build all r2 XML without running either numerical solver."""

    frozen_geometry = semifinal_anchor_r2_geometry() if geometry is None else geometry
    _require_frozen_geometry(frozen_geometry)
    base = build_rod_disclosures(frozen_geometry)
    identities: list[RodXmlIdentity] = []
    for row in base.refinements:
        repaired = _repaired_xml(frozen_geometry, row, run_id=ROD_R1_RUN_ID)
        if _sha256(repaired) != row.mesh.xml_sha256:
            raise CrossCheckError("repaired rod XML differs from its disclosure")
        if _sha256(repaired) != _expected_repaired_xml_hash(row.refinement):
            raise CrossCheckError(f"rod-r2 {row.refinement:g}x XML SHA-256 changed")
        legacy = _legacy_probe_xml(repaired)
        legacy_hash = _sha256(legacy)
        if legacy_hash != _expected_r1_xml_hash(row.refinement):
            raise CrossCheckError(f"rod-r1 {row.refinement:g}x XML SHA-256 changed")
        same = _normalized_probe_bounds(legacy) == _normalized_probe_bounds(repaired)
        if not same:
            raise CrossCheckError("r2 rod XML differs beyond probe bounds")
        identities.append(
            RodXmlIdentity(
                refinement=row.refinement,
                legacy_xml_sha256=legacy_hash,
                repaired_xml_sha256=_sha256(repaired),
                identical_except_probe_bounds=same,
            )
        )
    one, two, four, eight = base.refinements
    identity_one, identity_two, identity_four, identity_eight = identities
    pair = build_repair_diagnostic_xml_pair(frozen_geometry, one)
    return RodR2BuildOnlyDisclosure(
        legacy_dt_proxy_seconds=base.legacy_dt_proxy_seconds,
        target_physical_time_seconds=base.target_physical_time_seconds,
        refinements=(one, two, four, eight),
        xml_identities=(
            identity_one,
            identity_two,
            identity_four,
            identity_eight,
        ),
        diagnostic_xml=pair.disclosure,
    )


def write_rod_r2_build_only_disclosure(
    repo_root: Path,
) -> RodR2BuildOnlyDisclosure:
    """Create the deterministic r2 disclosure without overwriting evidence."""

    disclosure = build_rod_r2_disclosure()
    path = repo_root / ROD_R2_BUILD_ONLY_RELATIVE_PATH
    encoded = (
        json.dumps(
            disclosure.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    if path.exists():
        existing = RodR2BuildOnlyDisclosure.model_validate_json(path.read_bytes())
        if existing != disclosure or path.read_bytes() != encoded:
            raise CrossCheckError("existing rod-r2 build-only disclosure differs")
        return disclosure
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return disclosure


def verify_official_add_lumped_port_source(
    source_path: Path = Path(ROD_R2_OFFICIAL_ADD_LUMPED_PORT_SOURCE),
) -> str:
    """Verify the installed official source used by the frozen repair."""

    if not source_path.is_file():
        raise CrossCheckError(f"official AddLumpedPort source missing: {source_path}")
    digest = _sha256(source_path.read_bytes())
    if digest != ROD_R2_OFFICIAL_ADD_LUMPED_PORT_SOURCE_SHA256:
        raise CrossCheckError("official AddLumpedPort source SHA-256 changed")
    return digest


def _inventory(directory: Path) -> tuple[OutputFileEvidence, ...]:
    rows: list[OutputFileEvidence] = []
    for path in sorted(
        (item for item in directory.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(directory).as_posix(),
    ):
        payload = path.read_bytes()
        rows.append(
            OutputFileEvidence(
                relative_path=path.relative_to(directory).as_posix(),
                byte_size=len(payload),
                sha256=_sha256(payload),
            )
        )
    return tuple(rows)


def _probe_evidence(directory: Path, name: str) -> ProbeEvidence:
    path = directory / name
    if not path.is_file():
        return ProbeEvidence(
            name=name,
            exists=False,
            byte_size=None,
            sha256=None,
            parseable_sample_count=0,
            parse_error=None,
        )
    payload = path.read_bytes()
    sample_count = 0
    parse_error: str | None = None
    try:
        times, _values = read_probe(path)
        sample_count = int(len(times))
    except (OpenEMSParseError, OSError, UnicodeError, ValueError) as error:
        parse_error = str(error)
    return ProbeEvidence(
        name=name,
        exists=True,
        byte_size=len(payload),
        sha256=_sha256(payload),
        parseable_sample_count=sample_count,
        parse_error=parse_error,
    )


def _execute_diagnostic(
    executable: str,
    xml_bytes: bytes,
    label: DiagnosticLabel,
    geometry: Geometry,
) -> DiagnosticExecution:
    _require_frozen_geometry(geometry)
    with tempfile.TemporaryDirectory(prefix=f"rod_r2_{label}_") as temporary:
        directory = Path(temporary)
        (directory / "sim.xml").write_bytes(xml_bytes)
        stdout_path = directory / "openems.stdout.log"
        stderr_path = directory / "openems.stderr.log"
        started = time.monotonic()
        launched = False
        timed_out = False
        exit_code: int | None = None
        process_error: str | None = None
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            try:
                process = subprocess.Popen(
                    [executable, "sim.xml"],
                    cwd=directory,
                    stdout=stdout,
                    stderr=stderr,
                )
                launched = True
                while process.poll() is None:
                    if time.monotonic() - started > ROD_TIMEOUT_SECONDS:
                        _terminate_process_tree(process)
                        process.wait()
                        timed_out = True
                        break
                    time.sleep(MEMORY_POLL_SECONDS)
                exit_code = process.returncode
            except OSError as error:
                process_error = f"openEMS could not be launched: {error}"
        elapsed = time.monotonic() - started
        stdout_bytes = stdout_path.read_bytes()
        stderr_bytes = stderr_path.read_bytes()
        voltage = _probe_evidence(directory, "port_ut_1")
        current = _probe_evidence(directory, "port_it_1")
        files = _inventory(directory)
    return DiagnosticExecution(
        label=label,
        xml_sha256=_sha256(xml_bytes),
        launched=launched,
        exit_code=exit_code,
        timed_out=timed_out,
        normal_exit=launched and not timed_out and exit_code == 0,
        process_error=process_error,
        elapsed_seconds=elapsed,
        stdout_text=stdout_bytes.decode("utf-8", errors="replace"),
        stderr_text=stderr_bytes.decode("utf-8", errors="replace"),
        stdout_sha256=_sha256(stdout_bytes),
        stderr_sha256=_sha256(stderr_bytes),
        output_files=files,
        voltage_probe=voltage,
        current_probe=current,
    )


def _unavailable_diagnostic(
    label: DiagnosticLabel,
    xml_bytes: bytes,
) -> DiagnosticExecution:
    empty_hash = _sha256(b"")
    absent_voltage = ProbeEvidence(
        name="port_ut_1",
        exists=False,
        byte_size=None,
        sha256=None,
        parseable_sample_count=0,
        parse_error=None,
    )
    absent_current = ProbeEvidence(
        name="port_it_1",
        exists=False,
        byte_size=None,
        sha256=None,
        parseable_sample_count=0,
        parse_error=None,
    )
    return DiagnosticExecution(
        label=label,
        xml_sha256=_sha256(xml_bytes),
        launched=False,
        exit_code=None,
        timed_out=False,
        normal_exit=False,
        process_error="real openEMS executable is unavailable",
        elapsed_seconds=0.0,
        stdout_text="",
        stderr_text="",
        stdout_sha256=empty_hash,
        stderr_sha256=empty_hash,
        output_files=(),
        voltage_probe=absent_voltage,
        current_probe=absent_current,
    )


def evaluate_repair_gate(
    xml: RepairDiagnosticXmlDisclosure,
    legacy_a: DiagnosticExecution,
    repaired_b: DiagnosticExecution,
) -> RepairDiagnosticEvidence:
    """Apply the frozen harness-only A/B gate without evaluating S11."""

    reasons: list[str] = []
    if not xml.full_xml_identical_except_probe_bounds:
        reasons.append("full_xml_differs_beyond_probe_bounds")
    if not xml.diagnostic_xml_identical_except_probe_bounds:
        reasons.append("diagnostic_xml_differs_beyond_probe_bounds")
    if not xml.legacy_derivation_changed_only_timesteps:
        reasons.append("legacy_diagnostic_changed_beyond_timesteps")
    if not xml.repaired_derivation_changed_only_timesteps:
        reasons.append("repaired_diagnostic_changed_beyond_timesteps")
    if legacy_a.xml_sha256 != xml.legacy_diagnostic_xml_sha256:
        reasons.append("legacy_diagnostic_xml_hash_mismatch")
    if repaired_b.xml_sha256 != xml.repaired_diagnostic_xml_sha256:
        reasons.append("repaired_diagnostic_xml_hash_mismatch")
    if not legacy_a.normal_exit:
        reasons.append("legacy_diagnostic_process_failed")
    if legacy_a.voltage_probe.exists:
        reasons.append("legacy_voltage_probe_unexpectedly_present")
    if not repaired_b.normal_exit:
        reasons.append("repaired_diagnostic_process_failed")
    for label, probe in (
        ("voltage", repaired_b.voltage_probe),
        ("current", repaired_b.current_probe),
    ):
        if not probe.exists:
            reasons.append(f"repaired_{label}_probe_missing")
        elif probe.byte_size is None or probe.byte_size <= 0:
            reasons.append(f"repaired_{label}_probe_empty")
        elif probe.parseable_sample_count < 2:
            reasons.append(f"repaired_{label}_probe_unparseable")
    return RepairDiagnosticEvidence(
        xml=xml,
        legacy_a=legacy_a,
        repaired_b=repaired_b,
        gate_passed=not reasons,
        failure_reasons=tuple(reasons),
    )


def _validate_r1_evidence(repo_root: Path) -> None:
    run_directory = repo_root / "artifacts" / "runs" / ROD_R1_RUN_ID
    paths = (
        (run_directory / "log.jsonl", ROD_R1_LOG_SHA256),
        (run_directory / "summary.json", ROD_R1_SUMMARY_SHA256),
        (repo_root / ROD_R1_BUILD_ONLY_RELATIVE_PATH, ROD_R1_BUILD_ONLY_SHA256),
        (
            repo_root / "docs" / "semifinal-wifi58-rod-renderer-anchor-r1-preregistration.md",
            ROD_R1_PREREGISTRATION_SHA256,
        ),
    )
    for path, expected in paths:
        if not path.is_file() or _sha256(path.read_bytes()) != expected:
            raise CrossCheckError(f"immutable rod-r1 evidence changed: {path}")


def _config(
    geometry: Geometry,
    build_only: RodR2BuildOnlyDisclosure,
) -> dict[str, Any]:
    return {
        "protocol_version": ROD_R2_PROTOCOL,
        "preregistration_commit": ROD_R2_PREREGISTRATION_COMMIT,
        "geometry_hash": R2_GEOMETRY_SHA256,
        "geometry": geometry.metadata,
        "frequency_range_hz": R2_SWEEP_HZ,
        "frequency_points": R2_FREQUENCY_POINTS,
        "wire_representation": ROD_REPRESENTATION,
        "wire_radius_m": ROD_RADIUS_M,
        "openems_refinements": ROD_REFINEMENTS,
        "openems_convergence_pair": ROD_CONVERGENCE_PAIR,
        "cross_solver_openems_refinement": ROD_AGREEMENT_REFINEMENT,
        "openems_convergence_threshold": ROD_CONVERGENCE_THRESHOLD,
        "anchor_resonance_threshold": ANCHOR_RESONANCE_THRESHOLD,
        "anchor_pearson_threshold": ANCHOR_CORRELATION_THRESHOLD,
        "openems_timeout_seconds": ROD_TIMEOUT_SECONDS,
        "diagnostic_maximum_timesteps": ROD_R2_DIAGNOSTIC_MAXIMUM_TIMESTEPS,
        "official_add_lumped_port_source_sha256": (ROD_R2_OFFICIAL_ADD_LUMPED_PORT_SOURCE_SHA256),
        "target_physical_time_seconds": build_only.target_physical_time_seconds,
        "build_only_file": ROD_R2_BUILD_ONLY_RELATIVE_PATH,
    }


def _solver_mode_counts(
    diagnostic_processes: int,
    nec2: SolverCurve | None,
    completed_openems: int,
) -> dict[str, int]:
    """Count each launched solver under its actual recorded mode."""

    if diagnostic_processes < 0 or completed_openems < 0:
        raise ValueError("solver process counts cannot be negative")
    counts: dict[str, int] = {}
    subprocess_count = diagnostic_processes + completed_openems
    if subprocess_count:
        counts["subprocess"] = subprocess_count
    if nec2 is not None:
        counts[nec2.solver_mode] = counts.get(nec2.solver_mode, 0) + 1
    return counts


def _run_rod_level_r2(
    geometry: Geometry,
    disclosure: RodMeshDisclosure,
) -> RodR2OpenEMSResult:
    _require_frozen_geometry(geometry)
    adapter = OpenEMSAdapter()
    executable = adapter._resolve_executable()
    if executable is None:
        raise _RodR2LevelError(
            "solver_unavailable",
            "real openEMS executable is unavailable",
            refinement=disclosure.refinement,
        )
    level_run_id = f"{ROD_R2_RUN_ID}-openems-{disclosure.refinement:g}x"
    spec = _rod_spec(
        level_run_id,
        disclosure.refinement,
        disclosure.maximum_timesteps,
    )
    mesh = _mesh(geometry, level_run_id)
    xml_bytes, impedance = adapter._build_sim_xml(mesh, spec)
    statistics = parse_mesh_statistics(xml_bytes, disclosure.refinement)
    if statistics.xml_sha256 != disclosure.mesh.xml_sha256:
        raise _RodR2LevelError(
            "xml_identity_mismatch",
            "rod-r2 XML differs from the committed build-only disclosure",
            refinement=disclosure.refinement,
        )
    with tempfile.TemporaryDirectory(prefix="semifinal_rod_anchor_r2_") as temp:
        directory = Path(temp)
        (directory / "sim.xml").write_bytes(xml_bytes)
        stdout_path = directory / "openems.stdout.log"
        stderr_path = directory / "openems.stderr.log"
        started = time.monotonic()
        peak_bytes = 0
        timed_out = False
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            try:
                process = subprocess.Popen(
                    [executable, "sim.xml"],
                    cwd=directory,
                    stdout=stdout,
                    stderr=stderr,
                )
            except OSError as error:
                raise _RodR2LevelError(
                    "solver_launch_failed",
                    f"openEMS could not be launched: {error}",
                    refinement=disclosure.refinement,
                ) from error
            while process.poll() is None:
                peak_bytes = max(peak_bytes, _process_tree_rss_bytes(process.pid))
                if time.monotonic() - started > ROD_TIMEOUT_SECONDS:
                    _terminate_process_tree(process)
                    process.wait()
                    timed_out = True
                    break
                time.sleep(MEMORY_POLL_SECONDS)
        elapsed = time.monotonic() - started
        peak_bytes = max(peak_bytes, _process_tree_rss_bytes(process.pid))
        stdout_bytes = stdout_path.read_bytes()
        stderr_bytes = stderr_path.read_bytes()
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        stdout_tail = tuple(stdout_text.splitlines()[-20:])
        if timed_out:
            raise _RodR2LevelError(
                "timeout",
                (
                    f"openEMS rod-r2 {disclosure.refinement:g}x exceeded "
                    f"{ROD_TIMEOUT_SECONDS:.0f} seconds"
                ),
                refinement=disclosure.refinement,
                stdout_tail=stdout_tail,
                stderr_text=stderr_text,
            )
        if process.returncode != 0:
            raise _RodR2LevelError(
                "nonzero_exit",
                (f"openEMS rod-r2 {disclosure.refinement:g}x exited {process.returncode}"),
                refinement=disclosure.refinement,
                stdout_tail=stdout_tail,
                stderr_text=stderr_text,
            )
        try:
            termination = parse_termination(
                stdout_text,
                maximum_steps=disclosure.maximum_timesteps,
                dt_proxy_seconds=disclosure.dt_proxy_seconds,
            )
        except (CrossCheckError, OpenEMSParseError, ValueError) as error:
            raise _RodR2LevelError(
                "termination_parse_failed",
                f"openEMS termination evidence could not be parsed: {error}",
                refinement=disclosure.refinement,
                stdout_tail=stdout_tail,
                stderr_text=stderr_text,
            ) from error
        if termination.terminated_by == "unknown":
            raise _RodR2LevelError(
                "termination_unknown",
                "openEMS termination reason could not be parsed",
                refinement=disclosure.refinement,
                stdout_tail=termination.stdout_tail,
                stderr_text=stderr_text,
            )
        frequency_hz = np.linspace(R2_SWEEP_HZ[0], R2_SWEEP_HZ[1], R2_FREQUENCY_POINTS).tolist()
        try:
            spectra = calc_port(directory, 1, frequency_hz, z_ref=impedance)
        except (OpenEMSParseError, OSError, ValueError) as error:
            raise _RodR2LevelError(
                "port_data_missing",
                f"openEMS port data could not be parsed: {error}",
                refinement=disclosure.refinement,
                stdout_tail=termination.stdout_tail,
                stderr_text=stderr_text,
            ) from error
        try:
            curve = _curve_from_spectra(frequency_hz, spectra.s11, elapsed)
            result = RodR2OpenEMSResult(
                refinement=disclosure.refinement,
                curve=curve,
                mesh=statistics,
                maximum_timesteps=disclosure.maximum_timesteps,
                termination=termination,
                peak_process_tree_memory_mb=peak_bytes / (1024.0 * 1024.0),
                elapsed_seconds=elapsed,
                stderr_text=stderr_text,
                stderr_sha256=_sha256(stderr_bytes),
            )
        except (CrossCheckError, OpenEMSParseError, ValueError) as error:
            raise _RodR2LevelError(
                "curve_postprocess_failed",
                f"openEMS curve evidence could not be constructed: {error}",
                refinement=disclosure.refinement,
                stdout_tail=termination.stdout_tail,
                stderr_text=stderr_text,
            ) from error
    return result


def _write_payload(run_directory: Path, summary: RodR2RunSummary) -> None:
    run_directory.mkdir(parents=True, exist_ok=False)
    event = {
        "schema_version": 1,
        "event_type": "semifinal_rod_anchor_r2_result",
        "run_id": summary.run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "result_status": summary.result_status,
        "summary": summary.model_dump(mode="json"),
    }
    (run_directory / "log.jsonl").write_bytes(
        (json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
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


def _load_existing(run_directory: Path) -> RodR2RunSummary:
    payload = json.loads((run_directory / "summary.json").read_text(encoding="utf-8"))
    if payload.get("run_id") != ROD_R2_RUN_ID:
        raise CrossCheckError(
            f"existing rod-r2 run_id differs from the frozen value: {payload.get('run_id')!r}"
        )
    status = payload.get("result_status")
    if status == "repair_not_confirmed":
        return RodR2RepairNotConfirmedSummary.model_validate(payload)
    if status == "execution_failed":
        return RodR2ExecutionFailureSummary.model_validate(payload)
    if status == "completed":
        return RodR2AnchorSummary.model_validate(payload)
    raise CrossCheckError(f"unknown rod-r2 result_status: {status!r}")


async def run_rod_anchor_r2(repo_root: Path) -> RodR2RunSummary:
    """Run the fixed r2 A/B gate and, only if released, the frozen ladder."""

    run_directory = repo_root / "runs" / ROD_R2_RUN_ID
    if run_directory.exists():
        return _load_existing(run_directory)
    started_at = datetime.now(UTC)
    geometry = semifinal_anchor_r2_geometry()
    geometry_hash = _require_frozen_geometry(geometry)
    _validate_r1_evidence(repo_root)
    verify_official_add_lumped_port_source()
    build_only = build_rod_r2_disclosure(geometry)
    committed_path = repo_root / ROD_R2_BUILD_ONLY_RELATIVE_PATH
    if not committed_path.is_file():
        raise CrossCheckError("committed rod-r2 build-only disclosure is missing")
    committed = RodR2BuildOnlyDisclosure.model_validate_json(committed_path.read_bytes())
    if committed != build_only:
        raise CrossCheckError("committed rod-r2 build-only disclosure changed")
    config = _config(geometry, build_only)
    config_hash = _canonical_hash(config)
    pair = build_repair_diagnostic_xml_pair(geometry, build_only.refinements[0])
    if pair.disclosure != build_only.diagnostic_xml:
        raise CrossCheckError("diagnostic XML differs from build-only disclosure")
    executable = OpenEMSAdapter()._resolve_executable()
    if executable is None:
        legacy_a = _unavailable_diagnostic("legacy_a", pair.legacy_diagnostic_xml)
        repaired_b = _unavailable_diagnostic("repaired_b", pair.repaired_diagnostic_xml)
    else:
        legacy_a = _execute_diagnostic(executable, pair.legacy_diagnostic_xml, "legacy_a", geometry)
        repaired_b = _execute_diagnostic(
            executable, pair.repaired_diagnostic_xml, "repaired_b", geometry
        )
    repair = evaluate_repair_gate(pair.disclosure, legacy_a, repaired_b)
    diagnostic_steps = sum(int(item.normal_exit) for item in (legacy_a, repaired_b))
    diagnostic_processes = sum(int(item.launched) for item in (legacy_a, repaired_b))
    geometry_payload = geometry.model_dump(mode="json", exclude={"id"})
    if not repair.gate_passed:
        terminal = RodR2RepairNotConfirmedSummary(
            run_id=ROD_R2_RUN_ID,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            config_hash=config_hash,
            config=config,
            steps_completed=diagnostic_steps,
            solver_mode_counts={"subprocess": diagnostic_processes},
            geometry_hash=geometry_hash,
            geometry=geometry_payload,
            build_only=build_only,
            repair_diagnostic=repair,
        )
        _write_payload(run_directory, terminal)
        return terminal

    completed: list[RodR2OpenEMSResult] = []
    nec2: SolverCurve | None = None
    try:
        _require_frozen_geometry(geometry)
        adapter = NEC2Adapter()
        nec2_spec = _spec(f"{ROD_R2_RUN_ID}-nec2")
        try:
            nec2_mesh = await adapter.mesh(geometry, nec2_spec)
            nec2 = _curve(await adapter.solve(nec2_mesh, nec2_spec))
        except (CrossCheckError, OSError, subprocess.SubprocessError, ValueError) as error:
            raise _RodR2LevelError(
                "nec2_execution_failed",
                f"NEC2 rod-r2 execution failed: {error}",
            ) from error
        if nec2.solver_mode != "subprocess":
            raise _RodR2LevelError("fallback", f"rod-r2 NEC2 is not real: {nec2.solver_mode}")
        for disclosure in build_only.refinements:
            completed.append(_run_rod_level_r2(geometry, disclosure))
    except _RodR2LevelError as error:
        failure = RodR2ExecutionFailureSummary(
            run_id=ROD_R2_RUN_ID,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            config_hash=config_hash,
            config=config,
            steps_completed=(diagnostic_steps + (1 if nec2 is not None else 0) + len(completed)),
            solver_mode_counts=_solver_mode_counts(diagnostic_processes, nec2, len(completed)),
            geometry_hash=geometry_hash,
            geometry=geometry_payload,
            build_only=build_only,
            repair_diagnostic=repair,
            nec2=nec2,
            completed_openems=tuple(completed),
            failure=error.record,
        )
        _write_payload(run_directory, failure)
        return failure

    if nec2 is None or len(completed) != 4:
        raise AssertionError("rod-r2 completed an impossible scientific solve count")
    one, two, four, eight = completed
    decision = evaluate_rod_anchor(nec2, four, eight)
    r3 = _load_r3_summary(repo_root)
    reproduction = NEC2Reproduction(
        archived_frequency_hz=r3.nec2.resonance_frequency_hz,
        rerun_frequency_hz=nec2.resonance_frequency_hz,
        frequency_difference_hz=(nec2.resonance_frequency_hz - r3.nec2.resonance_frequency_hz),
        archived_s11_db=r3.nec2.resonance_s11_db,
        rerun_s11_db=nec2.resonance_s11_db,
        s11_difference_db=nec2.resonance_s11_db - r3.nec2.resonance_s11_db,
    )
    summary = RodR2AnchorSummary(
        run_id=ROD_R2_RUN_ID,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        config_hash=config_hash,
        config=config,
        solver_mode_counts=_solver_mode_counts(diagnostic_processes, nec2, len(completed)),
        geometry_hash=geometry_hash,
        geometry=geometry_payload,
        build_only=build_only,
        repair_diagnostic=repair,
        nec2=nec2,
        openems_1x=one,
        openems_2x=two,
        openems_4x=four,
        openems_8x=eight,
        decision=decision,
        richardson_estimate=richardson_estimate(two.curve, four.curve, eight.curve),
        nec2_reproduction=reproduction,
        radius_diagnostic=retrospective_radius_diagnostic(),
    )
    _write_payload(run_directory, summary)
    return summary
