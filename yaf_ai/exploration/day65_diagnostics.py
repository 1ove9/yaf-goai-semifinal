"""Pre-registered Day 6.5 bias and compute-feasibility diagnostics."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve, _curve
from yaf_ai.exploration.day6_cross_check import (
    SelectedDay6Design,
    reconstruct_day6_design,
)
from yaf_ai.exploration.day65 import (
    DAY65_DIPOLE_LENGTH_M,
    DAY65_FEED_GAP_M,
    DAY65_PROTOCOL_VERSION,
    DAY65_ROTATION_POINTS,
    DAY65_ROTATION_RUN_ID,
    DAY65_ROTATION_SWEEP_HZ,
    DAY65_WIRE_RADIUS_M,
    Day65RotationSummary,
    RotationResonance,
    build_rotation_dipole,
    rotation_resonance,
)
from yaf_ai.exploration.day65_repair import (
    DAY65_OPENEMS_BASE_TIMESTEPS,
    DAY65_OPENEMS_TIMEOUT_SECONDS,
    DAY65_RELEASED_REFINEMENT,
    frozen_candidates,
)
from yaf_ai.exploration.freeform_wire import (
    FREEFORM_FREQUENCY_POINTS,
    FREEFORM_SWEEP_HZ,
)
from yaf_ai.exploration.patch_mesh_audit import (
    PatchMeshStatistics,
    parse_mesh_statistics,
)
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

RADIUS_DIAGNOSTIC_RUN_ID = "day65-nec2-surrogate-radius-diagnostic"
ANALYSIS_RELATIVE_DIRECTORY = Path(
    "artifacts/analysis/day65-bias-compute-diagnostics"
)
PREREGISTRATION_PATH = "DECISIONS.md"
BASELINE_NEC2_FREQUENCY_HZ = 2.330e9
BASELINE_OPENEMS_FREQUENCY_HZ = 2.210e9
SURROGATE_RADIUS_M = 0.00025
ATTRIBUTED_FRACTION = 0.8
PARTIAL_FRACTION = 0.3
COMPUTE_SCALE_RATIO = 1.35
AUTHORIZED_FUTURE_TIMEOUT_SECONDS = 43_200.0
MEMORY_FIELD_COMPONENTS = 6
MEMORY_BYTES_PER_COMPONENT = 8
MEMORY_ESTIMATE_METHOD = "six_float64_field_components_per_Yee_cell_lower_bound"
TIMEOUT_EVIDENCE_PATHS = (
    "runs/day65-pipeline.stdout.log",
    "runs/day65-pipeline.stderr.log",
)

RadiusAttribution = Literal[
    "surrogate_radius_systematic_effect",
    "partial_attribution",
    "attribution_not_supported",
]
ComputeClassification = Literal[
    "infeasible_at_current_compute",
    "future_timeout_extension_authorized",
]


class RadiusAttributionDecision(BaseModel):
    """Frozen interpretation of the measured resonance shift."""

    model_config = ConfigDict(frozen=True)

    explained_fraction: float
    classification: RadiusAttribution


class RadiusDiagnosticSummary(BaseModel):
    """Archive-compatible result of the single authorized NEC2 sweep."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str = RADIUS_DIAGNOSTIC_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 1
    evaluation_budget: int = 1
    solver_mode_counts: dict[str, int]
    source_run_id: str = DAY65_ROTATION_RUN_ID
    source_orientation: Literal["y_axis"] = "y_axis"
    baseline_nec2_frequency_hz: float = BASELINE_NEC2_FREQUENCY_HZ
    baseline_openems_frequency_hz: float = BASELINE_OPENEMS_FREQUENCY_HZ
    tested_wire_radius_m: float = SURROGATE_RADIUS_M
    baseline_deck_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tested_deck_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    radius_only_changed_gw_lines: int = Field(ge=1)
    curve: SolverCurve
    resonance: RotationResonance
    decision: RadiusAttributionDecision


class CandidateMeshAudit(BaseModel):
    """Build-only XML grid statistics for one frozen candidate."""

    model_config = ConfigDict(frozen=True)

    candidate: Literal["A", "B"]
    rank: int = Field(ge=1, le=2)
    source_run_id: str
    source_step_index: int = Field(ge=0)
    source_geometry_hash: str
    seed: int
    xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mesh: PatchMeshStatistics
    estimated_field_memory_bytes: int = Field(ge=1)
    estimated_field_memory_gib: float = Field(gt=0.0)
    memory_estimate_method: str = MEMORY_ESTIMATE_METHOD
    openems_solve_invoked: Literal[False] = False


class ComputeFeasibilityDecision(BaseModel):
    """Frozen interpretation of the candidate-B to candidate-A cell ratio."""

    model_config = ConfigDict(frozen=True)

    cells_b_over_a: float = Field(gt=0.0)
    threshold: float = COMPUTE_SCALE_RATIO
    classification: ComputeClassification
    future_timeout_seconds: float | None
    retry_in_this_task: Literal[False] = False


class Day65DiagnosticsAnalysis(BaseModel):
    """Machine-readable build-only analysis paired with the radius run."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    generated_at: datetime
    preregistration_path: str = PREREGISTRATION_PATH
    radius_run_id: str = RADIUS_DIAGNOSTIC_RUN_ID
    radius_decision: RadiusAttributionDecision
    candidate_a: CandidateMeshAudit
    candidate_b: CandidateMeshAudit
    compute_decision: ComputeFeasibilityDecision
    timeout_evidence_paths: tuple[str, str] = TIMEOUT_EVIDENCE_PATHS
    correction_proposal: tuple[str, ...]
    solver_invocations: dict[str, int]


def _canonical_hash(payload: object) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
            + "\n"
        ).encode("utf-8")
    )
    os.replace(temporary, path)


def classify_radius_attribution(explained_fraction: float) -> RadiusAttributionDecision:
    """Apply the preregistered inclusive 0.3 and 0.8 boundaries."""

    if explained_fraction >= ATTRIBUTED_FRACTION:
        classification: RadiusAttribution = "surrogate_radius_systematic_effect"
    elif explained_fraction >= PARTIAL_FRACTION:
        classification = "partial_attribution"
    else:
        classification = "attribution_not_supported"
    return RadiusAttributionDecision(
        explained_fraction=explained_fraction,
        classification=classification,
    )


def classify_compute_feasibility(cells_b_over_a: float) -> ComputeFeasibilityDecision:
    """Apply the preregistered inclusive 1.35 compute-scale boundary."""

    if cells_b_over_a <= 0.0:
        raise ValueError("candidate mesh cell ratio must be positive")
    if cells_b_over_a >= COMPUTE_SCALE_RATIO:
        return ComputeFeasibilityDecision(
            cells_b_over_a=cells_b_over_a,
            classification="infeasible_at_current_compute",
            future_timeout_seconds=None,
        )
    return ComputeFeasibilityDecision(
        cells_b_over_a=cells_b_over_a,
        classification="future_timeout_extension_authorized",
        future_timeout_seconds=AUTHORIZED_FUTURE_TIMEOUT_SECONDS,
    )


def estimated_field_memory_bytes(total_cells: int) -> int:
    """Return a disclosed six-float64-field lower-bound estimate."""

    if total_cells < 1:
        raise ValueError("total_cells must be positive")
    return total_cells * MEMORY_FIELD_COMPONENTS * MEMORY_BYTES_PER_COMPONENT


def validate_radius_only_deck_change(
    baseline_deck: bytes, tested_deck: bytes
) -> int:
    """Prove every changed NEC deck token is a GW-card radius field."""

    baseline_lines = baseline_deck.decode("utf-8").splitlines()
    tested_lines = tested_deck.decode("utf-8").splitlines()
    if len(baseline_lines) != len(tested_lines):
        raise CrossCheckError("radius diagnostic changed NEC deck line count")
    changed = 0
    for baseline, tested in zip(baseline_lines, tested_lines, strict=True):
        if baseline == tested:
            continue
        baseline_tokens = baseline.split()
        tested_tokens = tested.split()
        if (
            not baseline_tokens
            or baseline_tokens[0] != "GW"
            or len(baseline_tokens) != len(tested_tokens)
            or baseline_tokens[:-1] != tested_tokens[:-1]
            or baseline_tokens[-1] == tested_tokens[-1]
        ):
            raise CrossCheckError("NEC deck changed outside GW radius fields")
        changed += 1
    if changed < 1:
        raise CrossCheckError("radius diagnostic did not change a NEC GW radius")
    return changed


def _rotation_source(repo_root: Path) -> Day65RotationSummary:
    path = (
        repo_root
        / "artifacts"
        / "runs"
        / DAY65_ROTATION_RUN_ID
        / "summary.json"
    )
    summary = Day65RotationSummary.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    if summary.config.get("protocol_version") != DAY65_PROTOCOL_VERSION:
        raise CrossCheckError("archived r12 protocol changed")
    y_axis = next(
        item for item in summary.orientations if item.orientation == "y_axis"
    )
    if (
        y_axis.nec2_resonance.frequency_hz != BASELINE_NEC2_FREQUENCY_HZ
        or y_axis.openems_resonance.frequency_hz != BASELINE_OPENEMS_FREQUENCY_HZ
        or y_axis.nec2.solver_mode != "subprocess"
        or y_axis.openems.solver_mode != "subprocess"
    ):
        raise CrossCheckError("archived r12 y-axis anchor changed")
    return summary


def _rotation_spec() -> SimulationSpec:
    return SimulationSpec(
        name=DAY65_ROTATION_RUN_ID,
        frequency_range=DAY65_ROTATION_SWEEP_HZ,
        frequency_points=DAY65_ROTATION_POINTS,
        far_field_request=None,
        solver_settings={
            "openems_mesh_refinement": 6.0,
            "openems_base_timesteps": 40000,
            "openems_timeout_seconds": 7200.0,
            "nec2_segments_per_wavelength": 160,
            "nec2_timeout_seconds": 1800.0,
        },
    )


def _with_wire_radius(geometry: Geometry, radius_m: float) -> Geometry:
    metadata = dict(geometry.metadata)
    metadata["wire_radius_m"] = radius_m
    return geometry.model_copy(update={"metadata": metadata})


def _write_radius_run(directory: Path, summary: RadiusDiagnosticSummary) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    events = [
        {
            "schema_version": 1,
            "event_type": "day65_nec2_surrogate_radius_diagnostic",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "source_run_id": summary.source_run_id,
            "source_orientation": summary.source_orientation,
            "tested_wire_radius_m": summary.tested_wire_radius_m,
            "curve": summary.curve.model_dump(mode="json"),
            "resonance": summary.resonance.model_dump(mode="json"),
            "decision": summary.decision.model_dump(mode="json"),
        }
    ]
    (directory / "log.jsonl").write_bytes(
        "".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
            for event in events
        ).encode("utf-8")
    )
    _write_json(directory / "summary.json", summary.model_dump(mode="json"))


async def run_radius_diagnostic(repo_root: Path) -> RadiusDiagnosticSummary:
    """Run the one authorized real NEC2 sweep after validating its sole change."""

    run_directory = repo_root / "runs" / RADIUS_DIAGNOSTIC_RUN_ID
    if run_directory.exists():
        raise CrossCheckError(f"radius diagnostic run already exists: {run_directory}")
    _rotation_source(repo_root)
    baseline_geometry = build_rotation_dipole("y_axis")
    if baseline_geometry.metadata.get("wire_radius_m") != DAY65_WIRE_RADIUS_M:
        raise CrossCheckError("r12 geometry baseline radius changed")
    tested_geometry = _with_wire_radius(baseline_geometry, SURROGATE_RADIUS_M)
    spec = _rotation_spec()
    adapter = NEC2Adapter()
    baseline_mesh = await adapter.mesh(baseline_geometry, spec)
    tested_mesh = await adapter.mesh(tested_geometry, spec)
    baseline_deck = adapter._build_nec_deck(baseline_mesh, spec).to_bytes()
    tested_deck = adapter._build_nec_deck(tested_mesh, spec).to_bytes()
    changed_lines = validate_radius_only_deck_change(baseline_deck, tested_deck)
    config: dict[str, Any] = {
        "preregistration_path": PREREGISTRATION_PATH,
        "source_run_id": DAY65_ROTATION_RUN_ID,
        "source_orientation": "y_axis",
        "protocol_version": DAY65_PROTOCOL_VERSION,
        "frequency_range_hz": DAY65_ROTATION_SWEEP_HZ,
        "frequency_points": DAY65_ROTATION_POINTS,
        "dipole_length_m": DAY65_DIPOLE_LENGTH_M,
        "feed_gap_m": DAY65_FEED_GAP_M,
        "baseline_wire_radius_m": DAY65_WIRE_RADIUS_M,
        "tested_wire_radius_m": SURROGATE_RADIUS_M,
        "baseline_nec2_frequency_hz": BASELINE_NEC2_FREQUENCY_HZ,
        "baseline_openems_frequency_hz": BASELINE_OPENEMS_FREQUENCY_HZ,
        "attributed_fraction_threshold": ATTRIBUTED_FRACTION,
        "partial_fraction_threshold": PARTIAL_FRACTION,
        "nec2_segments_per_wavelength": 160,
        "nec2_timeout_seconds": 1800.0,
        "openems_solver_invoked": False,
    }
    started_at = datetime.now(UTC)
    previous_no_fallback = os.environ.get("YAF_NO_FALLBACK")
    os.environ["YAF_NO_FALLBACK"] = "1"
    try:
        curve = _curve(await adapter.solve(tested_mesh, spec))
    finally:
        if previous_no_fallback is None:
            os.environ.pop("YAF_NO_FALLBACK", None)
        else:
            os.environ["YAF_NO_FALLBACK"] = previous_no_fallback
    if curve.solver_mode != "subprocess":
        raise CrossCheckError(f"radius diagnostic is not real: {curve.solver_mode}")
    resonance = rotation_resonance(curve)
    denominator = BASELINE_NEC2_FREQUENCY_HZ - BASELINE_OPENEMS_FREQUENCY_HZ
    explained_fraction = (
        BASELINE_NEC2_FREQUENCY_HZ - resonance.frequency_hz
    ) / denominator
    summary = RadiusDiagnosticSummary(
        started_at=started_at,
        finished_at=datetime.now(UTC),
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 1},
        baseline_deck_sha256=hashlib.sha256(baseline_deck).hexdigest(),
        tested_deck_sha256=hashlib.sha256(tested_deck).hexdigest(),
        radius_only_changed_gw_lines=changed_lines,
        curve=curve,
        resonance=resonance,
        decision=classify_radius_attribution(explained_fraction),
    )
    _write_radius_run(run_directory, summary)
    return summary


def _released_openems_spec() -> SimulationSpec:
    return SimulationSpec(
        name="day65-repair-crosscheck-build-only",
        frequency_range=FREEFORM_SWEEP_HZ,
        frequency_points=FREEFORM_FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings={
            "openems_mesh_refinement": DAY65_RELEASED_REFINEMENT,
            "openems_base_timesteps": DAY65_OPENEMS_BASE_TIMESTEPS,
            "openems_timeout_seconds": DAY65_OPENEMS_TIMEOUT_SECONDS,
        },
    )


async def build_candidate_mesh_audit(
    repo_root: Path,
    selected: SelectedDay6Design,
    candidate: Literal["A", "B"],
) -> CandidateMeshAudit:
    """Build and parse one released 6x XML without calling openEMS solve."""

    geometry, seed = reconstruct_day6_design(repo_root, selected)
    spec = _released_openems_spec()
    adapter = OpenEMSAdapter()
    mesh = await adapter.mesh(geometry, spec)
    xml_bytes, _impedance = adapter._build_sim_xml(mesh, spec)
    statistics = parse_mesh_statistics(xml_bytes, DAY65_RELEASED_REFINEMENT)
    memory_bytes = estimated_field_memory_bytes(statistics.total_cells)
    return CandidateMeshAudit(
        candidate=candidate,
        rank=selected.rank,
        source_run_id=selected.source_run_id,
        source_step_index=selected.source_step_index,
        source_geometry_hash=selected.source_geometry_hash,
        seed=seed,
        xml_sha256=hashlib.sha256(xml_bytes).hexdigest(),
        mesh=statistics,
        estimated_field_memory_bytes=memory_bytes,
        estimated_field_memory_gib=memory_bytes / 1024**3,
    )


def _correction_proposal(
    radius: RadiusAttributionDecision,
    compute: ComputeFeasibilityDecision,
) -> tuple[str, ...]:
    if radius.classification == "surrogate_radius_systematic_effect":
        radius_text = (
            "Pre-register a radius-matched dual-solver anchor using either a "
            "resolved 0.05 mm openEMS conductor or a disclosed 0.25 mm NEC2 "
            "control before proposing any protocol calibration; do not "
            "retroactively adjust the existing 5% threshold or archived verdicts."
        )
    elif radius.classification == "partial_attribution":
        radius_text = (
            "Treat conductor radius as one contributor and pre-register a factorial "
            "anchor audit of radius, feed representation, and grid resolution before "
            "changing any protocol threshold."
        )
    else:
        radius_text = (
            "Do not attribute the systematic offset to conductor radius; pre-register "
            "separate feed and spatial-dispersion diagnostics before changing the protocol."
        )
    if compute.classification == "infeasible_at_current_compute":
        compute_text = (
            "Record candidate B as infeasible_at_current_compute and do not rerun it; "
            "future candidate selection should disclose released-instrument mesh size "
            "before time stepping."
        )
    else:
        compute_text = (
            "A future, separately executed candidate-B audit may raise only "
            "openems_timeout_seconds to 43200; geometry, mesh, sweep, and every verdict "
            "gate must remain unchanged."
        )
    return radius_text, compute_text


def _report_markdown(analysis: Day65DiagnosticsAnalysis) -> str:
    def mesh_row(value: CandidateMeshAudit) -> str:
        mesh = value.mesh
        minimum = min(
            mesh.x.minimum_cell_size_m,
            mesh.y.minimum_cell_size_m,
            mesh.z.minimum_cell_size_m,
        )
        maximum = max(
            mesh.x.maximum_cell_size_m,
            mesh.y.maximum_cell_size_m,
            mesh.z.maximum_cell_size_m,
        )
        return (
            f"| {value.candidate} | {mesh.x.line_count} | {mesh.y.line_count} | "
            f"{mesh.z.line_count} | {mesh.total_cells} | {minimum:.9g} | "
            f"{maximum:.9g} | {value.estimated_field_memory_gib:.6f} | "
            f"`{value.xml_sha256}` |"
        )

    radius = analysis.radius_decision
    compute = analysis.compute_decision
    recommendations = "\n".join(
        f"{index}. {item}"
        for index, item in enumerate(analysis.correction_proposal, start=1)
    )
    return f"""# Day 6.5 frequency-bias and candidate-B compute diagnostics

## Result

The radius-only NEC2 run is `{analysis.radius_run_id}`. Its frozen
`explained_fraction` is **{radius.explained_fraction:.9f}**, classified as
`{radius.classification}`. Candidate B's released-instrument cell ratio to A is
**{compute.cells_b_over_a:.9f}**, classified as
`{compute.classification}`.

No openEMS time stepping was invoked. The only solver invocation was one real
NEC2 subprocess sweep. No ES/random batch was started.

## Released 6x build-only XML mesh audit

| Candidate | X lines | Y lines | Z lines | Total cells | Min cell (m) | Max cell (m) | Six-field lower bound (GiB) | XML SHA-256 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
{mesh_row(analysis.candidate_a)}
{mesh_row(analysis.candidate_b)}

Memory estimate method: `{MEMORY_ESTIMATE_METHOD}`. It is a transparent lower
bound of `cells * 6 field components * 8 bytes`, not a prediction of total
openEMS process memory.

## Frozen classification

`cells_B / cells_A = {compute.cells_b_over_a:.9f}` against the inclusive
threshold `{compute.threshold:.2f}`. Future timeout authorization:
`{compute.future_timeout_seconds}` seconds. No retry is executed in this task.

## Formal timeout evidence

- `{TIMEOUT_EVIDENCE_PATHS[0]}`
- `{TIMEOUT_EVIDENCE_PATHS[1]}`

## Correction proposal draft (not implemented)

{recommendations}

Existing protocols, thresholds, sweeps, scores, candidates, and archived runs
remain unchanged.
"""


async def run_compute_audit(repo_root: Path) -> Day65DiagnosticsAnalysis:
    """Build both frozen XMLs, classify the ratio, and write analysis files."""

    output_directory = repo_root / ANALYSIS_RELATIVE_DIRECTORY
    if output_directory.exists():
        raise CrossCheckError(f"diagnostic analysis already exists: {output_directory}")
    radius_path = (
        repo_root
        / "artifacts"
        / "runs"
        / RADIUS_DIAGNOSTIC_RUN_ID
        / "summary.json"
    )
    if not radius_path.is_file():
        raise CrossCheckError("radius diagnostic must be archived before mesh audit")
    radius = RadiusDiagnosticSummary.model_validate_json(
        radius_path.read_text(encoding="utf-8")
    )
    candidate_a, candidate_b = frozen_candidates(repo_root)
    audit_a = await build_candidate_mesh_audit(repo_root, candidate_a, "A")
    audit_b = await build_candidate_mesh_audit(repo_root, candidate_b, "B")
    compute = classify_compute_feasibility(
        audit_b.mesh.total_cells / audit_a.mesh.total_cells
    )
    analysis = Day65DiagnosticsAnalysis(
        generated_at=datetime.now(UTC),
        radius_decision=radius.decision,
        candidate_a=audit_a,
        candidate_b=audit_b,
        compute_decision=compute,
        correction_proposal=_correction_proposal(radius.decision, compute),
        solver_invocations={"nec2_subprocess": 1, "openems_time_stepping": 0},
    )
    output_directory.mkdir(parents=True, exist_ok=False)
    _write_json(output_directory / "summary.json", analysis.model_dump(mode="json"))
    (output_directory / "report.md").write_bytes(
        _report_markdown(analysis).encode("utf-8")
    )
    correction = "# Proposed correction (not implemented)\n\n" + "\n\n".join(
        f"{index}. {item}"
        for index, item in enumerate(analysis.correction_proposal, start=1)
    )
    correction += (
        "\n\nNo protocol, threshold, sweep, score, candidate, or archived evidence "
        "is changed by this draft.\n"
    )
    (output_directory / "correction-proposal.md").write_bytes(
        correction.encode("utf-8")
    )
    return analysis
