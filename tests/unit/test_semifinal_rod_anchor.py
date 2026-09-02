"""Tests for the bounded semifinal resolved-rod renderer anchor."""

from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from yaf_ai.exploration.cross_check import SolverCurve
from yaf_ai.exploration.patch_mesh_audit import (
    MeshAxisStatistics,
    PatchMeshStatistics,
)
from yaf_ai.exploration.semifinal_anchor_r2 import (
    R2_GEOMETRY_SHA256,
    R2_SWEEP_HZ,
    semifinal_anchor_r2_geometry,
    validate_semifinal_anchor_r2_geometry,
)
from yaf_ai.exploration.semifinal_rod_anchor import (
    LEGACY_R3_1X_XML_SHA256,
    R3_LOG_SHA256_FROZEN,
    R3_RUN_ID,
    R3_SUMMARY_SHA256_FROZEN,
    ROD_AGREEMENT_REFINEMENT,
    ROD_CONVERGENCE_PAIR,
    ROD_RADIUS_M,
    ROD_REFINEMENTS,
    InvalidReason,
    RodOpenEMSResult,
    TerminationEvidence,
    build_rod_disclosures,
    cfl_dt_proxy,
    evaluate_rod_anchor,
    maximum_timesteps,
    parse_termination,
    retrospective_radius_diagnostic,
)
from yaf_core.domain.geometry import Mesh
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter


def _curve(
    solver: str,
    resonance_hz: float,
    *,
    depth_db: float = -14.0,
    width_hz: float = 0.10e9,
) -> SolverCurve:
    frequencies = np.linspace(R2_SWEEP_HZ[0], R2_SWEEP_HZ[1], 251)
    notch = np.exp(-(((frequencies - resonance_hz) / width_hz) ** 2))
    values = -0.2 + (depth_db + 0.2) * notch
    index = int(np.argmin(values))
    return SolverCurve(
        solver_name=solver,
        solver_mode="subprocess",
        frequency_hz=tuple(float(value) for value in frequencies),
        s11_db=tuple(float(value) for value in values),
        resonance_frequency_hz=float(frequencies[index]),
        resonance_s11_db=float(values[index]),
        simulation_time_seconds=1.0,
    )


def _monotonic_curve(solver: str) -> SolverCurve:
    frequencies = np.linspace(R2_SWEEP_HZ[0], R2_SWEEP_HZ[1], 251)
    values = np.linspace(-14.0, -0.1, 251)
    return SolverCurve(
        solver_name=solver,
        solver_mode="subprocess",
        frequency_hz=tuple(float(value) for value in frequencies),
        s11_db=tuple(float(value) for value in values),
        resonance_frequency_hz=float(frequencies[0]),
        resonance_s11_db=float(values[0]),
        simulation_time_seconds=1.0,
    )


def _mesh_statistics(refinement: float) -> PatchMeshStatistics:
    axis = MeshAxisStatistics(
        line_count=2,
        cell_count=1,
        minimum_cell_size_m=0.001,
        maximum_cell_size_m=0.001,
    )
    return PatchMeshStatistics(
        refinement=refinement,
        x=axis,
        y=axis,
        z=axis,
        total_cells=1,
        xml_sha256="0" * 64,
    )


def _termination(
    *,
    kind: str = "end_criteria",
    refinement: float = 4.0,
) -> TerminationEvidence:
    del refinement
    return TerminationEvidence(
        executed_timesteps=100,
        openems_timestep_seconds=1e-12,
        dt_proxy_seconds=0.9e-12,
        actual_simulated_time_seconds=1e-10,
        estimated_simulated_time_seconds=0.9e-10,
        terminated_by=kind,
        stdout_tail=("Time for 100 iterations with 1 cells : 1 sec",),
    )


def _result(
    refinement: float,
    curve: SolverCurve,
    *,
    kind: str = "end_criteria",
) -> RodOpenEMSResult:
    return RodOpenEMSResult(
        refinement=refinement,
        curve=curve,
        mesh=_mesh_statistics(refinement),
        maximum_timesteps=1000,
        termination=_termination(kind=kind, refinement=refinement),
        peak_process_tree_memory_mb=1.0,
        elapsed_seconds=1.0,
    )


def _rod_xml(refinement: float = 2.0, steps: int = 1234) -> bytes:
    geometry = semifinal_anchor_r2_geometry()
    mesh = Mesh(
        geometry_id=geometry.id,
        solver_name="openems",
        nodes=geometry.vertices,
        elements=[list(edge) for edge in geometry.faces],
        element_type="mixed",
        metadata={"job_id": "rod-test", **geometry.metadata},
    )
    spec = SimulationSpec(
        name="rod-test",
        frequency_range=R2_SWEEP_HZ,
        frequency_points=251,
        far_field_request=None,
        solver_settings={
            "openems_mesh_refinement": refinement,
            "openems_wire_representation": "rod",
            "openems_number_of_timesteps": steps,
        },
    )
    xml_bytes, _ = OpenEMSAdapter()._build_sim_xml(mesh, spec)
    return xml_bytes


def _box_bounds(box: ET.Element) -> tuple[tuple[float, ...], tuple[float, ...]]:
    p1 = box.find("P1")
    p2 = box.find("P2")
    assert p1 is not None and p2 is not None
    return (
        tuple(float(p1.get(name, "nan")) for name in ("X", "Y", "Z")),
        tuple(float(p2.get(name, "nan")) for name in ("X", "Y", "Z")),
    )


def test_rod_build_reuses_exact_r2_geometry_and_legacy_xml() -> None:
    geometry = semifinal_anchor_r2_geometry()
    assert validate_semifinal_anchor_r2_geometry(geometry) == R2_GEOMETRY_SHA256
    disclosure = build_rod_disclosures(geometry)
    assert disclosure.legacy_xml_sha256 == LEGACY_R3_1X_XML_SHA256
    assert tuple(row.refinement for row in disclosure.refinements) == ROD_REFINEMENTS
    assert all(row.maximum_timesteps > 40000 for row in disclosure.refinements)
    assert all(
        row.cell_timesteps == row.mesh.total_cells * row.maximum_timesteps
        for row in disclosure.refinements
    )


def test_rod_boxes_and_port_use_frozen_square_cross_section() -> None:
    root = ET.fromstring(_rod_xml())
    metals = [
        element
        for element in root.findall(".//Metal")
        if element.get("Name", "").startswith("meander_wire_")
    ]
    assert len(metals) == 2
    for metal in metals:
        box = metal.find("./Primitives/Box")
        assert box is not None
        p1, p2 = _box_bounds(box)
        assert p1[0] == -ROD_RADIUS_M
        assert p2[0] == ROD_RADIUS_M
        assert p1[2] == -ROD_RADIUS_M
        assert p2[2] == ROD_RADIUS_M
    port = root.find(".//LumpedElement[@Name='port_resist_1']/Primitives/Box")
    assert port is not None
    p1, p2 = _box_bounds(port)
    assert p1[0] == -ROD_RADIUS_M
    assert p2[0] == ROD_RADIUS_M
    assert p1[2] == -ROD_RADIUS_M
    assert p2[2] == ROD_RADIUS_M


def test_rod_grid_contains_surfaces_center_and_exterior_seed_lines() -> None:
    root = ET.fromstring(_rod_xml(refinement=2.0))
    element = root.find(".//RectilinearGrid/XLines")
    assert element is not None and element.text is not None
    lines = {float(item) for item in element.text.split(",")}
    resolution = ROD_RADIUS_M / 2.0
    mandatory = {
        -ROD_RADIUS_M,
        0.0,
        ROD_RADIUS_M,
        -ROD_RADIUS_M - resolution,
        ROD_RADIUS_M + resolution,
        -2.0 * ROD_RADIUS_M,
        2.0 * ROD_RADIUS_M,
    }
    assert all(
        any(math.isclose(value, line, rel_tol=0.0, abs_tol=1e-15) for line in lines)
        for value in mandatory
    )
    cells = [
        right - left
        for left, right in zip(sorted(lines), sorted(lines)[1:], strict=False)
    ]
    assert min(cells) >= 0.5 * resolution - 1e-15
    assert min(cells) <= resolution + 1e-15


def test_rod_number_of_timesteps_is_serialized() -> None:
    root = ET.fromstring(_rod_xml(steps=1234))
    fdtd = root.find("./FDTD")
    assert fdtd is not None
    assert fdtd.get("NumberOfTimesteps") == "1234"


def test_default_representation_remains_thin_line_and_selector_is_not_geometry() -> None:
    geometry = semifinal_anchor_r2_geometry()
    assert "openems_wire_representation" not in geometry.metadata
    mesh = Mesh(
        geometry_id=geometry.id,
        solver_name="openems",
        nodes=geometry.vertices,
        elements=[list(edge) for edge in geometry.faces],
        element_type="mixed",
        metadata={
            "job_id": f"{R3_RUN_ID}-openems-1x",
            **geometry.metadata,
        },
    )
    from yaf_ai.exploration.semifinal_anchor import _spec

    xml_bytes, _ = OpenEMSAdapter()._build_sim_xml(
        mesh,
        _spec(f"{R3_RUN_ID}-openems-1x", refinement=1.0),
    )
    assert hashlib.sha256(xml_bytes).hexdigest() == LEGACY_R3_1X_XML_SHA256


def test_rod_builder_requires_radius_metadata() -> None:
    geometry = semifinal_anchor_r2_geometry()
    metadata = dict(geometry.metadata)
    metadata.pop("wire_radius_m")
    mesh = Mesh(
        geometry_id=geometry.id,
        solver_name="openems",
        nodes=geometry.vertices,
        elements=[list(edge) for edge in geometry.faces],
        element_type="mixed",
        metadata=metadata,
    )
    spec = SimulationSpec(
        name="missing-radius",
        frequency_range=R2_SWEEP_HZ,
        solver_settings={"openems_wire_representation": "rod"},
    )
    with pytest.raises(ValueError, match="wire_radius_m"):
        OpenEMSAdapter()._build_sim_xml(mesh, spec)


def test_fixed_ladder_and_decision_levels() -> None:
    assert ROD_REFINEMENTS == (1.0, 2.0, 4.0, 8.0)
    assert ROD_CONVERGENCE_PAIR == (4.0, 8.0)
    assert ROD_AGREEMENT_REFINEMENT == 8.0


def test_cfl_proxy_and_ceiling_known_answers() -> None:
    proxy = cfl_dt_proxy(
        ((0.0, 1.0), (0.0, 2.0), (0.0, 4.0))
    )
    expected = 1.0 / (299_792_458.0 * math.sqrt(1.0 + 0.25 + 0.0625))
    assert proxy == expected
    assert maximum_timesteps(10.0, 3.0) == 4


@pytest.mark.parametrize(
    ("stdout", "kind", "steps", "real_dt"),
    [
        (
            "FDTD timestep is: 2e-12 s\n"
            "Time for 800 iterations with 10 cells : 1 sec\n",
            "end_criteria",
            800,
            2e-12,
        ),
        (
            "FDTD timestep is: 2e-12 s\n"
            "RunFDTD: Warning: Max. number of timesteps was reached before "
            "the end-criteria\n"
            "Time for 1000 iterations with 10 cells : 1 sec\n",
            "timestep_cap",
            1000,
            2e-12,
        ),
        ("Time for 800 iterations with 10 cells : 1 sec\n", "end_criteria", 800, None),
        ("unrecognized output\n", "unknown", None, None),
    ],
)
def test_termination_parser(
    stdout: str,
    kind: str,
    steps: int | None,
    real_dt: float | None,
) -> None:
    evidence = parse_termination(
        stdout, maximum_steps=1000, dt_proxy_seconds=1e-12
    )
    assert evidence.terminated_by == kind
    assert evidence.executed_timesteps == steps
    assert evidence.openems_timestep_seconds == real_dt
    if real_dt is None:
        assert evidence.actual_simulated_time_seconds is None


def test_released_verdict() -> None:
    curve = _curve("openems", 5.80e9)
    decision = evaluate_rod_anchor(
        _curve("nec2", 5.80e9),
        _result(4.0, curve),
        _result(8.0, curve),
    )
    assert decision.verdict == "released"
    assert decision.anchor_released


def test_nonconvergence_precedes_other_failures() -> None:
    decision = evaluate_rod_anchor(
        _curve("nec2", 5.80e9),
        _result(4.0, _curve("openems", 5.60e9)),
        _result(8.0, _curve("openems", 5.80e9)),
    )
    assert decision.verdict == "not_released_not_converged"


def test_timestep_cap_is_not_converged() -> None:
    curve = _curve("openems", 5.80e9)
    decision = evaluate_rod_anchor(
        _curve("nec2", 5.80e9),
        _result(4.0, curve, kind="timestep_cap"),
        _result(8.0, curve),
    )
    assert decision.verdict == "not_released_not_converged"


@pytest.mark.parametrize(
    ("curve", "reason"),
    [
        (_monotonic_curve("nec2"), "no_internal_minimum"),
        (_curve("nec2", 5.70e9), "out_of_band_low"),
        (_curve("nec2", 5.90e9), "out_of_band_high"),
        (_curve("nec2", 5.80e9, depth_db=-5.9), "depth_above_minus_6_db"),
    ],
)
def test_nec2_invalid_reason_priority(
    curve: SolverCurve,
    reason: InvalidReason,
) -> None:
    openems = _curve("openems", 5.80e9)
    decision = evaluate_rod_anchor(
        curve,
        _result(4.0, openems),
        _result(8.0, openems),
    )
    assert decision.verdict == "not_released_resonance_invalid"
    assert decision.invalid_resonance is not None
    assert decision.invalid_resonance.solver == "nec2"
    assert decision.invalid_resonance.reason == reason


def test_openems_invalid_reason_is_reported_after_nec2() -> None:
    openems = _curve("openems", 5.90e9)
    decision = evaluate_rod_anchor(
        _curve("nec2", 5.80e9),
        _result(4.0, openems),
        _result(8.0, openems),
    )
    assert decision.verdict == "not_released_resonance_invalid"
    assert decision.invalid_resonance is not None
    assert decision.invalid_resonance.solver == "openems_8x"
    assert decision.invalid_resonance.reason == "out_of_band_high"


def test_agreement_failure_is_distinct() -> None:
    openems = _curve("openems", 5.86e9)
    decision = evaluate_rod_anchor(
        _curve("nec2", 5.74e9),
        _result(4.0, openems),
        _result(8.0, openems),
    )
    assert decision.verdict == "not_released_agreement"
    assert decision.invalid_resonance is None


def test_retrospective_model_is_purely_diagnostic() -> None:
    diagnostic = retrospective_radius_diagnostic()
    assert diagnostic.diagnostic_only
    assert diagnostic.retrospective
    assert not diagnostic.affects_verdict
    assert diagnostic.square_rod_equivalent_radius_m == 59e-6
    assert math.isfinite(diagnostic.predicted_square_rod_frequency_hz)


def test_r1_r2_r3_archived_bytes_are_immutable() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    r3 = repo_root / "artifacts" / "runs" / R3_RUN_ID
    assert (
        hashlib.sha256((r3 / "log.jsonl").read_bytes()).hexdigest()
        == R3_LOG_SHA256_FROZEN
    )
    assert (
        hashlib.sha256((r3 / "summary.json").read_bytes()).hexdigest()
        == R3_SUMMARY_SHA256_FROZEN
    )
