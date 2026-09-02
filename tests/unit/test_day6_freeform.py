"""Regression tests for the preregistered Day 6 free-form wire space."""

from __future__ import annotations

import asyncio
import math
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from yaf_ai.analysis.day6 import classify_day6_curve_spans
from yaf_ai.exploration.baselines import GPExplorationAgent, RandomSearchBaseline
from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve
from yaf_ai.exploration.day6_cross_check import (
    band_validity,
    evaluate_day6_curves,
    high_band_shift,
    rank_unique_records,
)
from yaf_ai.exploration.day65 import (
    DAY65_DIPOLE_LENGTH_M,
    RotationOrientationResult,
    RotationStageRecord,
    build_rotation_dipole,
    load_rotation_stage,
    rotation_resonance,
)
from yaf_ai.exploration.day65_repair import (
    repaired_convergence_passed,
)
from yaf_ai.exploration.environment import ExplorationConfig
from yaf_ai.exploration.freeform_wire import (
    FREEFORM_MAX_EDGE_M,
    FREEFORM_PROPOSAL_SPACES,
    HIGH_BAND_HZ,
    LOW_BAND_HZ,
    build_freeform_wire,
    build_ocfd,
    day6_design_spec,
    evaluate_dual_band_metrics,
    parameters_from_freeform_geometry,
    validate_control_arms,
)
from yaf_ai.exploration.logger import AuditStepRecord
from yaf_core.domain.simulation import SimulationResult, SimulationSpec, SParamResult
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import (
    OpenEMSAdapter,
    _partition_mesh_intervals,
)


def _parameters(node_count: int = 5) -> dict[str, float]:
    points = (
        (0.004, 0.001, 0.002),
        (0.008, 0.005, -0.002),
        (0.012, -0.003, 0.005),
        (0.016, 0.002, -0.004),
        (0.019, 0.007, 0.003),
        (0.015, 0.012, -0.006),
        (0.010, 0.018, 0.008),
    )
    return {
        f"node_{index}_{axis}_m": points[index][axis_index]
        for index in range(node_count)
        for axis_index, axis in enumerate(("x", "y", "z"))
    }


def _simulation(low_db: float, high_db: float) -> SimulationResult:
    frequencies = [
        1.5e9,
        LOW_BAND_HZ[0],
        sum(LOW_BAND_HZ) / 2.0,
        LOW_BAND_HZ[1],
        HIGH_BAND_HZ[0],
        sum(HIGH_BAND_HZ) / 2.0,
        HIGH_BAND_HZ[1],
        6.5e9,
    ]
    depths = [-0.1, low_db / 2.0, low_db, low_db / 2.0, high_db / 2.0, high_db, high_db / 2.0, -0.1]
    return SimulationResult(
        job_id=uuid.uuid4(),
        solver_name="nec2",
        solver_version="test",
        status="success",
        s_params=SParamResult(
            frequency=frequencies,
            s_matrix=[[[complex(10.0 ** (depth / 20.0), 0.0)]] for depth in depths],
        ),
        gain_dbi=2.0,
        efficiency=1.0,
        solver_metadata={"solver_mode": "subprocess"},
    )


def test_registered_freeform_dimensions_and_shared_agent_bounds() -> None:
    assert [len(space.parameters) for space in FREEFORM_PROPOSAL_SPACES] == [15, 18, 21]
    space = FREEFORM_PROPOSAL_SPACES[0]
    config = ExplorationConfig(
        spec=day6_design_spec(),
        evaluation_budget=1,
        solver="nec2",
        proposal_space_version=space.version,
    )
    gp = GPExplorationAgent(config)
    random = RandomSearchBaseline(config)
    assert gp.proposal_space == random.proposal_space == space
    assert gp.proposal_space.bounds == random.proposal_space.bounds
    assert config.nec2_segments_per_wavelength == 20


def test_freeform_roundtrip_symmetry_box_and_subdivision() -> None:
    parameters = _parameters()
    geometry = build_freeform_wire(parameters, 5, "test")
    assert parameters_from_freeform_geometry(geometry) == parameters
    assert geometry.metadata["antenna_class"] == "freeform_wire_3d"
    assert max(abs(value) for vertex in geometry.vertices for value in vertex) <= 0.020
    assert all(
        math.dist(geometry.vertices[face[0]], geometry.vertices[face[1]])
        <= FREEFORM_MAX_EDGE_M + 1e-12
        for face in geometry.faces[1:]
    )
    points = {tuple(round(value, 12) for value in vertex) for vertex in geometry.vertices}
    assert all(tuple(-value for value in point) in points for point in points)


def test_control_validation_rejects_short_and_intersecting_segments() -> None:
    with pytest.raises(ValueError, match="shorter than 3 mm"):
        validate_control_arms(
            [(0.0003, 0.0, 0.0), (0.001, 0.0, 0.0)],
            [(-0.0003, 0.0, 0.0), (-0.001, 0.0, 0.0)],
        )
    positive = [
        (0.0003, 0.0, 0.0),
        (0.010, 0.010, 0.0),
        (-0.010, 0.010, 0.0),
        (0.010, -0.010, 0.0),
    ]
    negative = [tuple(-value for value in point) for point in positive]
    with pytest.raises(ValueError, match="clearance"):
        validate_control_arms(positive, negative)


def test_ocfd_body_diagonal_is_deterministic_and_inside_cube() -> None:
    first = build_ocfd(0.069, 0.35)
    second = build_ocfd(0.069, 0.35)
    assert first.vertices == second.vertices
    assert first.faces == second.faces
    assert max(abs(value) for vertex in first.vertices for value in vertex) < 0.020
    assert float(first.metadata["total_wire_length_m"]) == pytest.approx(0.069)


def test_worst_band_score_blocks_single_band_gaming() -> None:
    single_band = evaluate_dual_band_metrics(_simulation(-20.0, -1.0))
    dual_band = evaluate_dual_band_metrics(_simulation(-10.0, -10.0))
    assert single_band["composite_score"] == pytest.approx(1.0 - 10.0 ** -0.1)
    assert dual_band["composite_score"] == pytest.approx(0.9)
    assert dual_band["composite_score"] > single_band["composite_score"]


def test_dual_band_validity_shaping_is_logged_but_base_score_is_unchanged() -> None:
    shallow = evaluate_dual_band_metrics(_simulation(-20.0, -1.0))
    frequencies = np.linspace(1.5e9, 6.5e9, 251)
    depths = np.full(251, -0.1)
    for target in (sum(LOW_BAND_HZ) / 2.0, sum(HIGH_BAND_HZ) / 2.0):
        index = int(np.argmin(np.abs(frequencies - target)))
        depths[index - 1 : index + 2] = (-5.0, -10.0, -5.0)
    source = _simulation(-1.0, -1.0)
    valid_simulation = source.model_copy(
        update={
            "s_params": SParamResult(
                frequency=[float(value) for value in frequencies],
                s_matrix=[[[complex(10.0 ** (float(depth) / 20.0), 0.0)]] for depth in depths],
            )
        }
    )
    valid = evaluate_dual_band_metrics(valid_simulation)
    assert shallow["search_validity_bonus"] == 0.0
    assert shallow["search_score"] == shallow["composite_score"]
    assert valid["valid_both_bands"] == 1.0
    assert valid["search_validity_bonus"] == 0.25
    assert valid["search_score"] == pytest.approx(valid["composite_score"] + 0.25)
    assert valid["composite_score"] == pytest.approx(0.9)


def test_nec2_and_openems_serialize_the_same_freeform_endpoints() -> None:
    geometry = build_freeform_wire(_parameters(), 5, "test")
    spec = SimulationSpec(
        frequency_range=(1.5e9, 6.5e9),
        frequency_points=251,
        solver_settings={
            "nec2_segments_per_wavelength": 160,
            "openems_mesh_refinement": 1.0,
        },
        far_field_request=None,
    )
    nec2 = NEC2Adapter()
    nec2_mesh = asyncio.run(nec2.mesh(geometry, spec))
    deck = nec2._build_nec_deck(nec2_mesh, spec).to_bytes().decode("ascii")
    assert deck.count("GW ") == len(geometry.faces)
    assert "\nXQ\n" in deck
    assert "\nRP " not in deck

    openems = OpenEMSAdapter()
    openems_mesh = asyncio.run(openems.mesh(geometry, spec))
    xml_bytes, _ = openems._build_sim_xml(openems_mesh, spec)
    root = ET.fromstring(xml_bytes)
    assert root.find(".//Cylinder") is None
    wires = root.findall(".//Wire")
    assert len(wires) == 2
    assert all(
        float(wire.get("WireRadius", "0")) == pytest.approx(0.00025)
        for wire in wires
    )
    wire_points = {
        tuple(float(vertex.get(axis, "nan")) for axis in ("X", "Y", "Z"))
        for wire in wires
        for vertex in wire.findall("Vertex")
    }
    assert tuple(geometry.vertices[1]) in wire_points
    assert root.find(".//LumpedElement") is not None
    fdtd = root.find(".//FDTD")
    assert fdtd is not None
    assert fdtd.get("NumberOfTimesteps") == "40000"


def test_freeform_equal_interval_mesh_has_no_direction_dependent_runt() -> None:
    resolution = 0.000125
    for orientation in ("y_axis", "yz45", "z_axis"):
        geometry = build_rotation_dipole(orientation)
        spec = SimulationSpec(
            frequency_range=(1.5e9, 3.5e9),
            frequency_points=201,
            far_field_request=None,
            solver_settings={
                "openems_mesh_refinement": 4.0,
                "openems_base_timesteps": 40000,
            },
        )
        adapter = OpenEMSAdapter()
        mesh = asyncio.run(adapter.mesh(geometry, spec))
        root = ET.fromstring(adapter._build_sim_xml(mesh, spec)[0])
        nodes = np.asarray(mesh.nodes, dtype=float)
        lower = nodes.min(axis=0) - 0.00025
        upper = nodes.max(axis=0) + 0.00025
        grid = root.find(".//RectilinearGrid")
        assert grid is not None
        for dimension, name in enumerate(("XLines", "YLines", "ZLines")):
            element = grid.find(name)
            assert element is not None and element.text is not None
            values = np.asarray([float(value) for value in element.text.split(",")])
            local = values[(values >= lower[dimension]) & (values <= upper[dimension])]
            steps = np.diff(local)
            assert float(steps.min()) >= resolution / 2.0 - 1e-12
            assert float(steps.max()) <= resolution + 1e-12


def test_equal_interval_mesh_rejects_mandatory_runt() -> None:
    with pytest.raises(ValueError, match="runt cell"):
        _partition_mesh_intervals([0.0, 0.00001, 0.001], 0.000125)


def test_rotation_known_answer_geometries_share_length_and_feed() -> None:
    geometries = [
        build_rotation_dipole(orientation)
        for orientation in ("y_axis", "yz45", "z_axis")
    ]
    for geometry in geometries:
        assert geometry.faces[0] == [0, 1]
        assert float(geometry.metadata["total_wire_length_m"]) == pytest.approx(
            DAY65_DIPOLE_LENGTH_M
        )
        assert geometry.metadata["positive_edge_count"] == 1
    assert geometries[0].vertices[2][1] != 0.0
    assert geometries[0].vertices[2][2] == 0.0
    assert geometries[1].vertices[2][1] != 0.0
    assert geometries[1].vertices[2][2] != 0.0
    assert geometries[2].vertices[2][1] == 0.0
    assert geometries[2].vertices[2][2] != 0.0


def test_rotation_resonance_rejects_shallow_or_edge_minimum() -> None:
    valid = _curve(95, 170)
    assert rotation_resonance(valid).valid
    shallow = valid.model_copy(
        update={"s11_db": tuple(max(value, -5.9) for value in valid.s11_db)}
    )
    assert not rotation_resonance(shallow).valid
    edge_values = list(valid.s11_db)
    edge_values[0] = -20.0
    edge = valid.model_copy(update={"s11_db": tuple(edge_values)})
    assert not rotation_resonance(edge).valid


def test_repaired_convergence_missing_resonance_is_not_zero_shift() -> None:
    assert repaired_convergence_passed(0.03)
    assert not repaired_convergence_passed(0.0300001)
    assert not repaired_convergence_passed(None)


def test_rotation_stage_requires_exact_config_and_orientation(tmp_path: Path) -> None:
    curve = _curve(47, 170)
    resonance = rotation_resonance(curve)
    result = RotationOrientationResult(
        orientation="y_axis",
        direction=(0.0, 1.0, 0.0),
        geometry_hash="known-geometry",
        nec2=curve,
        openems=curve,
        nec2_resonance=resonance,
        openems_resonance=resonance,
    )
    now = datetime.now(UTC)
    stage = RotationStageRecord(
        run_id="known-run",
        config_hash="known-config",
        started_at=now,
        finished_at=now,
        result=result,
    )
    path = tmp_path / "y_axis.json"
    path.write_text(stage.model_dump_json(), encoding="utf-8")

    loaded = load_rotation_stage(
        path,
        run_id="known-run",
        config_hash="known-config",
        orientation="y_axis",
    )
    assert loaded == stage
    with pytest.raises(CrossCheckError, match="staging mismatch"):
        load_rotation_stage(
            path,
            run_id="known-run",
            config_hash="different-config",
            orientation="y_axis",
        )


def test_nec2_timeout_override_preserves_default_and_rejects_invalid() -> None:
    default = SimulationSpec(frequency_range=(1.0e9, 2.0e9))
    extended = default.model_copy(
        update={"solver_settings": {"nec2_timeout_seconds": 1800.0}}
    )
    invalid = default.model_copy(
        update={"solver_settings": {"nec2_timeout_seconds": 0.0}}
    )
    assert NEC2Adapter._timeout_seconds(default) == 300.0
    assert NEC2Adapter._timeout_seconds(extended) == 1800.0
    with pytest.raises(ValueError, match="finite and positive"):
        NEC2Adapter._timeout_seconds(invalid)


def test_openems_timeout_setting_rejects_invalid_before_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    geometry = build_rotation_dipole("y_axis")
    spec = SimulationSpec(
        frequency_range=(1.5e9, 3.5e9),
        frequency_points=11,
        far_field_request=None,
        solver_settings={"openems_timeout_seconds": 0.0},
    )
    adapter = OpenEMSAdapter()
    mesh = asyncio.run(adapter.mesh(geometry, spec))
    monkeypatch.setattr(adapter, "_build_sim_xml", lambda _mesh, _spec: (b"<x/>", 50.0))
    with pytest.raises(ValueError, match="finite and positive"):
        adapter._run_subprocess(tmp_path, mesh, spec, str(mesh.id), "openEMS.exe")


def _curve(low_index: int, high_index: int, shift: int = 0) -> SolverCurve:
    frequencies = tuple(float(value) * 1e6 for value in range(1500, 6501, 20))
    values = [-0.2] * len(frequencies)
    for index, depth in ((low_index + shift, -10.0), (high_index + shift, -12.0)):
        values[index - 1] = depth / 2.0
        values[index] = depth
        values[index + 1] = depth / 2.0
    minimum = min(range(len(values)), key=values.__getitem__)
    return SolverCurve(
        solver_name="test",
        solver_mode="subprocess",
        frequency_hz=frequencies,
        s11_db=tuple(values),
        resonance_frequency_hz=frequencies[minimum],
        resonance_s11_db=values[minimum],
        simulation_time_seconds=1.0,
    )


def test_dual_band_decision_requires_two_local_resonances_and_correlation() -> None:
    first = _curve(47, 214)
    same = _curve(47, 214)
    decision = evaluate_day6_curves(first, same)
    assert decision.verdict == "CONFIRMED"
    assert decision.low_band.openems.valid
    assert decision.high_band.nec2.valid
    assert decision.whole_sweep_pearson == pytest.approx(1.0)

    shallow = first.model_copy(
        update={"s11_db": tuple(-5.9 if index == 47 else value for index, value in enumerate(first.s11_db))}
    )
    assert evaluate_day6_curves(shallow, same).verdict == "NO_RESONANCE_IN_BAND"


def test_high_band_shift_and_validity_boundary_are_deterministic() -> None:
    first = _curve(47, 214)
    shifted = _curve(47, 214, shift=1)
    assert high_band_shift(first, shifted) == pytest.approx(20.0 / 5800.0)
    assert band_validity(first, (5.725e9, 5.875e9)).valid
    shallow_values = tuple(
        -5.9 if 5.725e9 <= frequency <= 5.875e9 else value
        for frequency, value in zip(first.frequency_hz, first.s11_db, strict=True)
    )
    shallow = first.model_copy(update={"s11_db": shallow_values})
    assert high_band_shift(shallow, shifted) is None


def test_curve_span_diagnostic_distinguishes_near_flat_from_dynamic() -> None:
    assert (
        classify_day6_curve_spans(10.0, 0.01)
        == "link_or_geometry_coupling_anomaly"
    )
    assert (
        classify_day6_curve_spans(10.0, 0.051)
        == "unresolved_solver_disagreement"
    )
    assert (
        classify_day6_curve_spans(0.9, 0.01)
        == "unresolved_solver_disagreement"
    )


def _audit_record(run_id: str, step: int, score: float, hash_value: str) -> AuditStepRecord:
    return AuditStepRecord(
        run_id=run_id,
        step_index=step,
        timestamp=datetime.now(UTC),
        geometry_summary={},
        geometry_hash=hash_value,
        solver_name="nec2",
        solver_mode="subprocess",
        metrics={},
        score=score,
        seed=1,
        config_hash="0" * 64,
        proposal_parameters={},
        proposer="gp",
    )


def test_top_selector_deduplicates_and_uses_frozen_tie_breakers() -> None:
    records = (
        _audit_record("z-run", 1, 0.9, "same"),
        _audit_record("a-run", 2, 0.9, "same"),
        _audit_record("b-run", 3, 0.9, "second"),
        _audit_record("c-run", 0, 0.8, "third"),
    )
    selected = rank_unique_records(records)
    assert [(row.run_id, row.step_index) for row in selected] == [
        ("a-run", 2),
        ("b-run", 3),
    ]
