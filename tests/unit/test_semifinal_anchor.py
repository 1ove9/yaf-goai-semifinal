"""Tests for the frozen semifinal 5.8 GHz renderer certificate."""

from __future__ import annotations

import asyncio
import math
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from yaf_ai.exploration.cross_check import SolverCurve
from yaf_ai.exploration.patch_mesh_audit import (
    MeshAxisStatistics,
    PatchMeshStatistics,
)
from yaf_ai.exploration.semifinal_anchor import (
    ANCHOR_FEED_GAP_M,
    ANCHOR_FREQUENCY_POINTS,
    ANCHOR_LENGTH_M,
    ANCHOR_SWEEP_HZ,
    SEMIFINAL_ANCHOR_GEOMETRY_SHA256,
    MonitoredOpenEMSResult,
    SemifinalAnchorSummary,
    _spec,
    _write_run,
    evaluate_semifinal_anchor,
    semifinal_anchor_geometry,
    validate_semifinal_anchor_hash,
)
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter


def _curve(
    solver: str,
    resonance_hz: float,
    *,
    depth_db: float = -14.0,
) -> SolverCurve:
    frequencies = np.linspace(ANCHOR_SWEEP_HZ[0], ANCHOR_SWEEP_HZ[1], ANCHOR_FREQUENCY_POINTS)
    width_hz = 0.10e9
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


def test_frozen_anchor_geometry_and_sha256() -> None:
    geometry = semifinal_anchor_geometry()
    assert geometry.faces == [[0, 1], [1, 2], [0, 3]]
    assert geometry.metadata["antenna_class"] == "meander_dipole"
    assert geometry.metadata["anchor_topology"] == "straight_half_wave"
    assert math.dist(geometry.vertices[0], geometry.vertices[1]) == ANCHOR_FEED_GAP_M
    total = sum(
        math.dist(geometry.vertices[start], geometry.vertices[stop])
        for start, stop in geometry.faces
    )
    assert total == ANCHOR_LENGTH_M
    assert validate_semifinal_anchor_hash(geometry) == SEMIFINAL_ANCHOR_GEOMETRY_SHA256


def test_anchor_xml_uses_meander_thin_boxes_and_frozen_sweep() -> None:
    geometry = semifinal_anchor_geometry()
    spec = _spec("test-semifinal-anchor", refinement=1.0)
    adapter = OpenEMSAdapter()
    mesh = asyncio.run(adapter.mesh(geometry, spec))
    xml_bytes, _impedance = adapter._build_sim_xml(mesh, spec)
    root = ET.fromstring(xml_bytes)
    boxes = root.findall("./ContinuousStructure/Properties/Metal/Primitives/Box")
    ports = root.findall("./ContinuousStructure/Properties/LumpedElement/Primitives/Box")
    assert len(boxes) == 2
    assert len(ports) == 1
    assert spec.frequency_range == ANCHOR_SWEEP_HZ
    assert spec.frequency_points == ANCHOR_FREQUENCY_POINTS


def test_anchor_releases_only_when_every_frozen_gate_passes() -> None:
    nec2 = _curve("nec2", 5.80e9)
    openems_1x = _curve("openems", 5.82e9)
    openems_2x = _curve("openems", 5.80e9)
    decision = evaluate_semifinal_anchor(nec2, openems_1x, openems_2x)
    assert decision.nec2_validity.valid
    assert decision.openems_1x_validity.valid
    assert decision.openems_2x_validity.valid
    assert decision.cross_solver_decision is not None
    assert decision.cross_solver_decision.verdict == "CONFIRMED"
    assert decision.openems_convergence_met
    assert decision.anchor_released


def test_anchor_blocks_missing_adjacent_valid_resonance() -> None:
    decision = evaluate_semifinal_anchor(
        _curve("nec2", 5.80e9),
        _curve("openems", 5.60e9),
        _curve("openems", 5.80e9),
    )
    assert decision.openems_resonance_shift is None
    assert not decision.openems_convergence_met
    assert not decision.anchor_released


def test_anchor_blocks_invalid_resonance_depth() -> None:
    decision = evaluate_semifinal_anchor(
        _curve("nec2", 5.80e9),
        _curve("openems", 5.80e9),
        _curve("openems", 5.80e9, depth_db=-5.9),
    )
    assert not decision.openems_2x_validity.depth_threshold_met
    assert not decision.anchor_released


def test_anchor_evidence_files_are_lf_only(tmp_path: Path) -> None:
    nec2 = _curve("nec2", 5.80e9)
    one = _curve("openems", 5.82e9)
    two = _curve("openems", 5.80e9)
    axis = MeshAxisStatistics(
        line_count=2,
        cell_count=1,
        minimum_cell_size_m=0.001,
        maximum_cell_size_m=0.001,
    )

    def monitored(refinement: float, curve: SolverCurve) -> MonitoredOpenEMSResult:
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

    now = datetime.now(UTC)
    summary = SemifinalAnchorSummary(
        started_at=now,
        finished_at=now,
        config_hash="frozen-config",
        config={},
        solver_mode_counts={"subprocess": 3},
        geometry_hash=SEMIFINAL_ANCHOR_GEOMETRY_SHA256,
        geometry=semifinal_anchor_geometry().model_dump(mode="json", exclude={"id"}),
        nec2=nec2,
        openems_1x=monitored(1.0, one),
        openems_2x=monitored(2.0, two),
        decision=evaluate_semifinal_anchor(nec2, one, two),
    )
    directory = tmp_path / summary.run_id
    _write_run(directory, summary)
    for name in ("log.jsonl", "summary.json"):
        payload = (directory / name).read_bytes()
        assert b"\r" not in payload
        assert payload.endswith(b"\n")
