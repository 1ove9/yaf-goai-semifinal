"""Tests for the preregistered semifinal 5.8 GHz anchor r2."""

from __future__ import annotations

import asyncio
import hashlib
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from yaf_ai.exploration.cross_check import SolverCurve
from yaf_ai.exploration.patch_mesh_audit import (
    MeshAxisStatistics,
    PatchMeshStatistics,
)
from yaf_ai.exploration.semifinal_anchor import MonitoredOpenEMSResult
from yaf_ai.exploration.semifinal_anchor_r2 import (
    R1_LENGTH_M,
    R1_LOG_SHA256,
    R1_NEC2_RESONANCE_FREQUENCY_HZ,
    R1_SUMMARY_SHA256,
    R2_FREQUENCY_POINTS,
    R2_GEOMETRY_SHA256,
    R2_LENGTH_M,
    R2_OPENEMS_REFINEMENTS,
    R2_SWEEP_HZ,
    TARGET_FREQUENCY_HZ,
    evaluate_semifinal_anchor_r2,
    run_openems_ladder,
    semifinal_anchor_r2_geometry,
    validate_semifinal_anchor_r2_geometry,
)
from yaf_core.domain.geometry import Geometry
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter


def _curve(
    solver: str,
    resonance_hz: float,
    *,
    depth_db: float = -14.0,
    width_hz: float = 0.10e9,
) -> SolverCurve:
    frequencies = np.linspace(R2_SWEEP_HZ[0], R2_SWEEP_HZ[1], R2_FREQUENCY_POINTS)
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


def _monitored(refinement: float, curve: SolverCurve) -> MonitoredOpenEMSResult:
    axis = MeshAxisStatistics(
        line_count=2,
        cell_count=1,
        minimum_cell_size_m=0.001,
        maximum_cell_size_m=0.001,
    )
    return MonitoredOpenEMSResult(
        refinement=refinement,
        curve=curve,
        mesh=PatchMeshStatistics(
            refinement=refinement,
            x=axis,
            y=axis,
            z=axis,
            total_cells=1,
            xml_sha256="0" * 64,
        ),
        peak_process_tree_memory_mb=1.0,
        elapsed_seconds=1.0,
    )


def test_r2_length_is_bitwise_formula_result() -> None:
    assert R2_LENGTH_M == (
        R1_LENGTH_M
        * R1_NEC2_RESONANCE_FREQUENCY_HZ
        / TARGET_FREQUENCY_HZ
    )


def test_r2_frozen_geometry_nodes_edges_and_sha256() -> None:
    geometry = semifinal_anchor_r2_geometry()
    assert geometry.vertices == [
        [0.0, -0.0003, 0.0],
        [0.0, 0.0003, 0.0],
        [0.0, R2_LENGTH_M / 2.0, 0.0],
        [0.0, -R2_LENGTH_M / 2.0, 0.0],
    ]
    assert geometry.faces == [[0, 1], [1, 2], [0, 3]]
    assert validate_semifinal_anchor_r2_geometry(geometry) == R2_GEOMETRY_SHA256
    total = sum(
        math.dist(geometry.vertices[start], geometry.vertices[stop])
        for start, stop in geometry.faces
    )
    assert total == R2_LENGTH_M


def test_r2_xml_uses_meander_thin_boxes_and_identical_sweep() -> None:
    from yaf_ai.exploration.semifinal_anchor import _spec

    geometry = semifinal_anchor_r2_geometry()
    spec = _spec("test-semifinal-anchor-r2", refinement=1.0)
    adapter = OpenEMSAdapter()
    mesh = asyncio.run(adapter.mesh(geometry, spec))
    xml_bytes, _impedance = adapter._build_sim_xml(mesh, spec)
    root = ET.fromstring(xml_bytes)
    boxes = root.findall("./ContinuousStructure/Properties/Metal/Primitives/Box")
    ports = root.findall(
        "./ContinuousStructure/Properties/LumpedElement/Primitives/Box"
    )
    assert len(boxes) == 2
    assert len(ports) == 1
    assert spec.frequency_range == R2_SWEEP_HZ
    assert spec.frequency_points == R2_FREQUENCY_POINTS
    assert geometry.metadata["wire_radius_m"] == 5e-5
    assert geometry.metadata["nec2_extended_thin_wire_kernel"] is False


def test_r2_ladder_is_exact_and_never_stops_on_intermediate_result() -> None:
    calls: list[float] = []

    def runner(
        geometry: Geometry,
        *,
        refinement: float,
        run_id: str,
    ) -> MonitoredOpenEMSResult:
        del geometry, run_id
        calls.append(refinement)
        return _monitored(refinement, _curve("openems", 5.50e9))

    results = run_openems_ladder(
        semifinal_anchor_r2_geometry(),
        "fixed-ladder",
        runner=runner,
    )
    assert R2_OPENEMS_REFINEMENTS == (1.0, 2.0, 4.0, 8.0)
    assert calls == [1.0, 2.0, 4.0, 8.0]
    assert tuple(result.refinement for result in results) == R2_OPENEMS_REFINEMENTS


def test_r2_convergence_reads_4x_to_8x_and_agreement_reads_8x() -> None:
    nec2 = _curve("nec2", 5.80e9)
    decision = evaluate_semifinal_anchor_r2(
        nec2,
        _curve("openems", 5.40e9),
        _curve("openems", 5.50e9),
        _curve("openems", 5.82e9),
        _curve("openems", 5.80e9),
    )
    assert decision.openems_4x_to_8x_resonance_shift == (
        abs(5.82e9 - 5.80e9) / 5.80e9
    )
    assert decision.openems_convergence_met
    assert decision.cross_solver_decision is not None
    assert decision.cross_solver_decision.resonance_relative_difference == 0.0
    assert decision.verdict == "released"


def test_r2_nec2_out_of_band_has_first_priority() -> None:
    decision = evaluate_semifinal_anchor_r2(
        _curve("nec2", 5.50e9),
        _curve("openems", 5.80e9),
        _curve("openems", 5.80e9),
        _curve("openems", 5.80e9, depth_db=-5.9),
        _curve("openems", 5.80e9),
    )
    assert decision.verdict == "not_released_out_of_band"
    assert not decision.anchor_released


def test_r2_failed_4x_to_8x_is_not_converged() -> None:
    decision = evaluate_semifinal_anchor_r2(
        _curve("nec2", 5.80e9),
        _curve("openems", 5.80e9),
        _curve("openems", 5.80e9),
        _curve("openems", 5.60e9),
        _curve("openems", 5.80e9),
    )
    assert decision.openems_4x_to_8x_resonance_shift is None
    assert decision.verdict == "not_released_not_converged"
    assert not decision.anchor_released


def test_r2_band_valid_but_agreement_failure_is_distinct() -> None:
    decision = evaluate_semifinal_anchor_r2(
        _curve("nec2", 5.74e9),
        _curve("openems", 5.86e9),
        _curve("openems", 5.86e9),
        _curve("openems", 5.86e9),
        _curve("openems", 5.86e9),
    )
    assert decision.nec2_validity.valid
    assert decision.openems_4x_validity.valid
    assert decision.openems_8x_validity.valid
    assert decision.openems_convergence_met
    assert decision.cross_solver_decision is not None
    assert decision.cross_solver_decision.verdict == "DIVERGENT"
    assert decision.verdict == "not_released_agreement"
    assert not decision.anchor_released


def test_r2_all_gates_pass_releases_anchor() -> None:
    curve = _curve("openems", 5.80e9)
    decision = evaluate_semifinal_anchor_r2(
        _curve("nec2", 5.80e9),
        curve,
        curve,
        curve,
        curve,
    )
    assert decision.verdict == "released"
    assert decision.anchor_released


def test_r1_archived_evidence_sha256_is_immutable() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    run = (
        repo_root
        / "artifacts"
        / "runs"
        / "semifinal-wifi58-meander-renderer-anchor-r1-combined"
    )
    assert hashlib.sha256((run / "log.jsonl").read_bytes()).hexdigest() == R1_LOG_SHA256
    assert (
        hashlib.sha256((run / "summary.json").read_bytes()).hexdigest()
        == R1_SUMMARY_SHA256
    )
