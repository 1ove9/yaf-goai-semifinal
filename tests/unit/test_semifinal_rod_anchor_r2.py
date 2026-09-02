"""Pure regression tests for the terminal rod-renderer anchor r2."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

import scripts.semifinal_rod_anchor_r2 as rod_r2_cli
import yaf_ai.exploration.semifinal_rod_anchor_r2 as rod_r2
import yaf_solvers.openems_adapter.adapter as openems_adapter_module
from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve
from yaf_ai.exploration.freeform_wire import build_freeform_wire
from yaf_ai.exploration.semifinal_anchor import _spec
from yaf_ai.exploration.semifinal_anchor_r2 import (
    R2_GEOMETRY_SHA256,
    R2_SWEEP_HZ,
    semifinal_anchor_r2_geometry,
)
from yaf_ai.exploration.semifinal_anchor_r3 import R3_RUN_ID
from yaf_ai.exploration.semifinal_rod_anchor import (
    BUILD_ONLY_RELATIVE_PATH as ROD_R1_BUILD_ONLY_RELATIVE_PATH,
)
from yaf_ai.exploration.semifinal_rod_anchor import (
    ROD_RUN_ID as ROD_R1_RUN_ID,
)
from yaf_core.domain.geometry import Geometry, Mesh
from yaf_core.domain.simulation import SimulationSpec
from yaf_core.geometry.parametric import ParametricGenerator
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter
from yaf_solvers.openems_adapter.xml_writer import LumpedPort, OpenEMSXmlWriter

LEGACY_MEANDER_XML_SHA256_BY_REFINEMENT = (
    (1.0, "cfeb036bb550cf2a5847f4388b8ac2556a8752eff70180d555e6d1ce29aa94ad"),
    (2.0, "73e1997bba9d54793392121a4f2d951b91702ca65fa12dd8354426ec7c99c4b7"),
    (4.0, "2d62bbd9322b6c931788bae62a796479ffb58d02b013b48170f97daec8e7bb2e"),
    (8.0, "5aec11444ca0b182982c48deab7efe850954a9cef1f02cb98cb8a594541fa3cd"),
    (16.0, "98f567a8292e054a0ba6fce7ae5bca64ff36f77bbf2d5a7a24c2ef0644fb5426"),
    (32.0, "a7dcd6db50c63136ac2e97135a13a7f9a8034e5ea0c4e4d2cbac33a53fc9916d"),
)


class _LegacyProbeWriter(OpenEMSXmlWriter):
    """Pre-repair writer used only to prove line-port byte identity."""

    def add_lumped_port(self, port: LumpedPort) -> None:
        n = port.number
        lumped = ET.SubElement(
            self._properties,
            "LumpedElement",
            ID=self._next_id(),
            Name=f"port_resist_{n}",
            Direction=str(port.direction),
            Caps="1",
            R=f"{port.resistance:.6e}",
        )
        self._add_box(lumped, 5, port.start, port.stop)
        if port.excite:
            vector = [0.0, 0.0, 0.0]
            vector[port.direction] = -1.0
            excitation = ET.SubElement(
                self._properties,
                "Excitation",
                ID=self._next_id(),
                Name=f"port_excite_{n}",
                Number="0",
                Type="0",
                Excite=",".join(f"{value:g}" for value in vector),
            )
            self._add_box(excitation, 5, port.start, port.stop)
            ET.SubElement(excitation, "Weight", X="1", Y="1", Z="1")
        voltage = ET.SubElement(
            self._properties,
            "ProbeBox",
            ID=self._next_id(),
            Name=f"port_ut_{n}",
            Number="0",
            Type="0",
            Weight="-1",
            NormDir="-1",
        )
        self._add_box(voltage, 0, port.start, port.stop)
        midpoint = tuple(
            (start + stop) / 2.0 for start, stop in zip(port.start, port.stop, strict=True)
        )
        current = ET.SubElement(
            self._properties,
            "ProbeBox",
            ID=self._next_id(),
            Name=f"port_it_{n}",
            Number="0",
            Type="1",
            Weight="1",
            NormDir=str(port.direction),
        )
        self._add_box(current, 0, midpoint, midpoint)


@pytest.fixture(scope="module")
def disclosure() -> rod_r2.RodR2BuildOnlyDisclosure:
    return rod_r2.build_rod_r2_disclosure()


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _probe(
    name: str,
    *,
    exists: bool,
    samples: int = 0,
    byte_size: int | None = None,
) -> rod_r2.ProbeEvidence:
    size = (16 if byte_size is None else byte_size) if exists else None
    return rod_r2.ProbeEvidence(
        name=name,
        exists=exists,
        byte_size=size,
        sha256=("a" * 64 if exists else None),
        parseable_sample_count=samples,
        parse_error=None,
    )


def _diagnostic(
    label: rod_r2.DiagnosticLabel,
    xml_hash: str,
    *,
    normal_exit: bool = True,
    voltage: rod_r2.ProbeEvidence | None = None,
    current: rod_r2.ProbeEvidence | None = None,
) -> rod_r2.DiagnosticExecution:
    return rod_r2.DiagnosticExecution(
        label=label,
        xml_sha256=xml_hash,
        launched=True,
        exit_code=0 if normal_exit else 1,
        timed_out=False,
        normal_exit=normal_exit,
        process_error=None,
        elapsed_seconds=0.01,
        stdout_text="diagnostic stdout\n",
        stderr_text="diagnostic stderr\n",
        stdout_sha256=_digest(b"diagnostic stdout\n"),
        stderr_sha256=_digest(b"diagnostic stderr\n"),
        output_files=(),
        voltage_probe=voltage or _probe("port_ut_1", exists=False),
        current_probe=current or _probe("port_it_1", exists=False),
    )


def _passing_diagnostics(
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
) -> tuple[rod_r2.DiagnosticExecution, rod_r2.DiagnosticExecution]:
    xml = disclosure.diagnostic_xml
    legacy = _diagnostic("legacy_a", xml.legacy_diagnostic_xml_sha256)
    repaired = _diagnostic(
        "repaired_b",
        xml.repaired_diagnostic_xml_sha256,
        voltage=_probe("port_ut_1", exists=True, samples=2),
        current=_probe("port_it_1", exists=True, samples=2),
    )
    return legacy, repaired


def _terminal_summary(
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
) -> rod_r2.RodR2RepairNotConfirmedSummary:
    legacy, repaired = _passing_diagnostics(disclosure)
    unexpected_voltage = legacy.model_copy(
        update={"voltage_probe": _probe("port_ut_1", exists=True, samples=2)}
    )
    repair = rod_r2.evaluate_repair_gate(
        disclosure.diagnostic_xml,
        unexpected_voltage,
        repaired,
    )
    now = datetime.now(UTC)
    geometry = semifinal_anchor_r2_geometry()
    return rod_r2.RodR2RepairNotConfirmedSummary(
        started_at=now,
        finished_at=now,
        config_hash="0" * 64,
        config={"protocol_version": rod_r2.ROD_R2_PROTOCOL},
        steps_completed=2,
        solver_mode_counts={"subprocess": 2},
        geometry_hash=R2_GEOMETRY_SHA256,
        geometry=geometry.model_dump(mode="json", exclude={"id"}),
        build_only=disclosure,
        repair_diagnostic=repair,
    )


def _write_committed_disclosure(
    repo_root: Path,
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
) -> None:
    path = repo_root / rod_r2.ROD_R2_BUILD_ONLY_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            disclosure.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _curve(solver: str = "nec2") -> SolverCurve:
    frequencies = np.linspace(R2_SWEEP_HZ[0], R2_SWEEP_HZ[1], 251)
    s11_db = -0.1 - 14.0 * np.exp(-(((frequencies - 5.8e9) / 0.1e9) ** 2))
    index = int(np.argmin(s11_db))
    return SolverCurve(
        solver_name=solver,
        solver_mode="subprocess",
        frequency_hz=tuple(float(value) for value in frequencies),
        s11_db=tuple(float(value) for value in s11_db),
        resonance_frequency_hz=float(frequencies[index]),
        resonance_s11_db=float(s11_db[index]),
        simulation_time_seconds=0.01,
    )


def test_build_disclosure_freezes_ab_and_all_rod_hashes(
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
) -> None:
    diagnostic = disclosure.diagnostic_xml
    assert diagnostic.legacy_diagnostic_xml_sha256 == (rod_r2.ROD_R2_LEGACY_DIAGNOSTIC_XML_SHA256)
    assert diagnostic.repaired_diagnostic_xml_sha256 == (
        rod_r2.ROD_R2_REPAIRED_DIAGNOSTIC_XML_SHA256
    )
    assert diagnostic.maximum_timesteps == 10
    assert diagnostic.full_xml_identical_except_probe_bounds
    assert diagnostic.diagnostic_xml_identical_except_probe_bounds
    assert diagnostic.legacy_derivation_changed_only_timesteps
    assert diagnostic.repaired_derivation_changed_only_timesteps
    assert (
        tuple((row.refinement, row.legacy_xml_sha256) for row in disclosure.xml_identities)
        == rod_r2.ROD_R1_XML_SHA256_BY_REFINEMENT
    )
    assert (
        tuple((row.refinement, row.repaired_xml_sha256) for row in disclosure.xml_identities)
        == rod_r2.ROD_R2_REPAIRED_XML_SHA256_BY_REFINEMENT
    )
    assert all(row.identical_except_probe_bounds for row in disclosure.xml_identities)


def test_diagnostic_pair_bytes_match_frozen_hashes(
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
) -> None:
    pair = rod_r2.build_repair_diagnostic_xml_pair(
        semifinal_anchor_r2_geometry(),
        disclosure.refinements[0],
    )
    assert _digest(pair.legacy_full_xml) == dict(rod_r2.ROD_R1_XML_SHA256_BY_REFINEMENT)[1.0]
    assert (
        _digest(pair.repaired_full_xml)
        == dict(rod_r2.ROD_R2_REPAIRED_XML_SHA256_BY_REFINEMENT)[1.0]
    )
    assert _digest(pair.legacy_diagnostic_xml) == (rod_r2.ROD_R2_LEGACY_DIAGNOSTIC_XML_SHA256)
    assert _digest(pair.repaired_diagnostic_xml) == (rod_r2.ROD_R2_REPAIRED_DIAGNOSTIC_XML_SHA256)


def test_six_legacy_meander_xml_hashes_are_byte_identical() -> None:
    geometry = semifinal_anchor_r2_geometry()
    adapter = OpenEMSAdapter()
    for refinement, expected in LEGACY_MEANDER_XML_SHA256_BY_REFINEMENT:
        run_id = f"{R3_RUN_ID}-openems-{refinement:g}x"
        mesh = Mesh(
            geometry_id=geometry.id,
            solver_name="openems",
            nodes=geometry.vertices,
            elements=[list(edge) for edge in geometry.faces],
            element_type="mixed",
            metadata={"job_id": run_id, **geometry.metadata},
        )
        xml_bytes, _ = adapter._build_sim_xml(
            mesh,
            _spec(run_id, refinement=refinement),
        )
        assert _digest(xml_bytes) == expected


def _generic_wire_case() -> tuple[Mesh, SimulationSpec]:
    geometry = Geometry(
        name="line-port-generic-wire",
        representation="mesh",
        vertices=[[0.0, 0.0, -0.03], [0.0, 0.0, 0.03]],
        faces=[[0, 1]],
    )
    spec = SimulationSpec(
        name="line-port-generic-wire",
        frequency_range=(2.0e9, 3.0e9),
        frequency_points=11,
        far_field_request=None,
    )
    return asyncio.run(OpenEMSAdapter().mesh(geometry, spec)), spec


def _meander_line_case() -> tuple[Mesh, SimulationSpec]:
    geometry = semifinal_anchor_r2_geometry()
    spec = _spec("line-port-meander", refinement=2.0)
    return asyncio.run(OpenEMSAdapter().mesh(geometry, spec)), spec


def _freeform_line_case() -> tuple[Mesh, SimulationSpec]:
    points = (
        (0.004, 0.001, 0.002),
        (0.008, 0.005, -0.002),
        (0.012, -0.003, 0.005),
        (0.016, 0.002, -0.004),
        (0.019, 0.007, 0.003),
    )
    parameters = {
        f"node_{index}_{axis}_m": points[index][axis_index]
        for index in range(5)
        for axis_index, axis in enumerate(("x", "y", "z"))
    }
    geometry = build_freeform_wire(parameters, 5, "line-port-freeform")
    spec = SimulationSpec(
        name="line-port-freeform",
        frequency_range=(1.5e9, 6.5e9),
        frequency_points=251,
        solver_settings={"openems_mesh_refinement": 1.0},
        far_field_request=None,
    )
    return asyncio.run(OpenEMSAdapter().mesh(geometry, spec)), spec


def _patch_line_case() -> tuple[Mesh, SimulationSpec]:
    geometry = ParametricGenerator.rectangular_patch(
        width=40e-3,
        length=32e-3,
        substrate_thickness=1.524e-3,
        substrate_width=60e-3,
        substrate_length=60e-3,
        eps_r=3.38,
        loss_tangent=1e-3,
        feed_x=-6e-3,
    )
    spec = SimulationSpec(
        name="line-port-patch",
        frequency_range=(1e9, 3e9),
        frequency_points=101,
        far_field_request=None,
    )
    return asyncio.run(OpenEMSAdapter().mesh(geometry, spec)), spec


def _pixel_line_case() -> tuple[Mesh, SimulationSpec]:
    half_x, half_y = 16e-3, 20e-3
    geometry = Geometry(
        name="line-port-pixel",
        representation="mesh",
        vertices=[
            [-half_x, -half_y, 0.0],
            [half_x, -half_y, 0.0],
            [half_x, half_y, 0.0],
            [-half_x, half_y, 0.0],
        ],
        faces=[[0, 1, 2], [0, 2, 3]],
        metadata={
            "antenna_class": "pixel_patch",
            "substrate_thickness": 1.524e-3,
            "eps_r": 3.38,
            "loss_tangent": 1e-3,
            "substrate_length": 60e-3,
            "substrate_width": 60e-3,
            "feed_x": -6e-3,
            "feed_y": 0.0,
            "pixel_size": 2e-3,
        },
    )
    spec = SimulationSpec(
        name="line-port-pixel",
        frequency_range=(1e9, 3e9),
        frequency_points=101,
        far_field_request=None,
    )
    return asyncio.run(OpenEMSAdapter().mesh(geometry, spec)), spec


@pytest.mark.parametrize(
    "case_builder",
    [
        _generic_wire_case,
        _meander_line_case,
        _freeform_line_case,
        _patch_line_case,
        _pixel_line_case,
    ],
    ids=("generic-wire", "meander-thin", "freeform", "patch", "pixel-patch"),
)
def test_every_line_port_adapter_path_is_byte_identical(
    case_builder: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert callable(case_builder)
    mesh, spec = case_builder()
    current_xml, current_impedance = OpenEMSAdapter()._build_sim_xml(mesh, spec)
    monkeypatch.setattr(
        openems_adapter_module,
        "OpenEMSXmlWriter",
        _LegacyProbeWriter,
    )
    legacy_xml, legacy_impedance = OpenEMSAdapter()._build_sim_xml(mesh, spec)
    assert current_xml == legacy_xml
    assert current_impedance == legacy_impedance


def test_repair_gate_passes_only_frozen_ab_boundary(
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
) -> None:
    legacy, repaired = _passing_diagnostics(disclosure)
    gate = rod_r2.evaluate_repair_gate(disclosure.diagnostic_xml, legacy, repaired)
    assert gate.gate_passed
    assert gate.failure_reasons == ()
    assert not gate.s11_evaluated


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("legacy_process", "legacy_diagnostic_process_failed"),
        ("legacy_voltage", "legacy_voltage_probe_unexpectedly_present"),
        ("repaired_process", "repaired_diagnostic_process_failed"),
        ("voltage_missing", "repaired_voltage_probe_missing"),
        ("current_missing", "repaired_current_probe_missing"),
        ("voltage_empty", "repaired_voltage_probe_empty"),
        ("current_unparseable", "repaired_current_probe_unparseable"),
        ("legacy_hash", "legacy_diagnostic_xml_hash_mismatch"),
        ("repaired_hash", "repaired_diagnostic_xml_hash_mismatch"),
    ],
)
def test_repair_gate_failure_boundaries(
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
    case: str,
    reason: str,
) -> None:
    legacy, repaired = _passing_diagnostics(disclosure)
    if case == "legacy_process":
        legacy = legacy.model_copy(update={"normal_exit": False, "exit_code": 1})
    elif case == "legacy_voltage":
        legacy = legacy.model_copy(
            update={"voltage_probe": _probe("port_ut_1", exists=True, samples=2)}
        )
    elif case == "repaired_process":
        repaired = repaired.model_copy(update={"normal_exit": False, "exit_code": 1})
    elif case == "voltage_missing":
        repaired = repaired.model_copy(update={"voltage_probe": _probe("port_ut_1", exists=False)})
    elif case == "current_missing":
        repaired = repaired.model_copy(update={"current_probe": _probe("port_it_1", exists=False)})
    elif case == "voltage_empty":
        repaired = repaired.model_copy(
            update={
                "voltage_probe": _probe(
                    "port_ut_1",
                    exists=True,
                    samples=2,
                    byte_size=0,
                )
            }
        )
    elif case == "current_unparseable":
        repaired = repaired.model_copy(
            update={"current_probe": _probe("port_it_1", exists=True, samples=1)}
        )
    elif case == "legacy_hash":
        legacy = legacy.model_copy(update={"xml_sha256": "f" * 64})
    elif case == "repaired_hash":
        repaired = repaired.model_copy(update={"xml_sha256": "f" * 64})
    gate = rod_r2.evaluate_repair_gate(disclosure.diagnostic_xml, legacy, repaired)
    assert not gate.gate_passed
    assert reason in gate.failure_reasons


@pytest.mark.asyncio
async def test_gate_failure_prevents_nec2_and_scientific_ladder_calls(
    tmp_path: Path,
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_committed_disclosure(tmp_path, disclosure)
    monkeypatch.setattr(rod_r2, "_validate_r1_evidence", lambda _root: None)
    monkeypatch.setattr(
        rod_r2,
        "verify_official_add_lumped_port_source",
        lambda: rod_r2.ROD_R2_OFFICIAL_ADD_LUMPED_PORT_SOURCE_SHA256,
    )
    monkeypatch.setattr(rod_r2, "build_rod_r2_disclosure", lambda _geometry: disclosure)
    monkeypatch.setattr(
        rod_r2.OpenEMSAdapter,
        "_resolve_executable",
        lambda _self: "never-executed-openems",
    )
    pair = rod_r2.build_repair_diagnostic_xml_pair(
        semifinal_anchor_r2_geometry(),
        disclosure.refinements[0],
    )
    calls: list[str] = []

    def fake_diagnostic(
        _executable: str,
        _xml: bytes,
        label: rod_r2.DiagnosticLabel,
        _geometry: Geometry,
    ) -> rod_r2.DiagnosticExecution:
        calls.append(label)
        legacy, repaired = _passing_diagnostics(disclosure)
        if label == "legacy_a":
            return legacy.model_copy(
                update={"voltage_probe": _probe("port_ut_1", exists=True, samples=2)}
            )
        return repaired

    class ForbiddenNEC2:
        def __init__(self) -> None:
            raise AssertionError("NEC2 must not be constructed after a failed A/B gate")

    def forbidden_ladder(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("scientific openEMS ladder must not run after failed A/B gate")

    monkeypatch.setattr(rod_r2, "_execute_diagnostic", fake_diagnostic)
    monkeypatch.setattr(rod_r2, "NEC2Adapter", ForbiddenNEC2)
    monkeypatch.setattr(rod_r2, "_run_rod_level_r2", forbidden_ladder)
    summary = await rod_r2.run_rod_anchor_r2(tmp_path)
    assert isinstance(summary, rod_r2.RodR2RepairNotConfirmedSummary)
    assert calls == ["legacy_a", "repaired_b"]
    assert summary.result_status == "repair_not_confirmed"
    assert summary.failure_type == "repair_not_confirmed"
    assert summary.scientific_verdict is None
    assert summary.verdict is None
    assert not summary.anchor_released
    assert summary.steps_completed == 2
    assert summary.solver_mode_counts == {"subprocess": 2}
    persisted = json.loads(
        (tmp_path / "runs" / rod_r2.ROD_R2_RUN_ID / "summary.json").read_text(encoding="utf-8")
    )
    assert persisted["result_status"] == "repair_not_confirmed"
    assert persisted["scientific_verdict"] is None
    assert pair.disclosure == disclosure.diagnostic_xml


@pytest.mark.asyncio
async def test_scientific_failure_retains_full_stderr(
    tmp_path: Path,
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_committed_disclosure(tmp_path, disclosure)
    monkeypatch.setattr(rod_r2, "_validate_r1_evidence", lambda _root: None)
    monkeypatch.setattr(
        rod_r2,
        "verify_official_add_lumped_port_source",
        lambda: rod_r2.ROD_R2_OFFICIAL_ADD_LUMPED_PORT_SOURCE_SHA256,
    )
    monkeypatch.setattr(rod_r2, "build_rod_r2_disclosure", lambda _geometry: disclosure)
    monkeypatch.setattr(
        rod_r2.OpenEMSAdapter,
        "_resolve_executable",
        lambda _self: "never-executed-openems",
    )
    legacy, repaired = _passing_diagnostics(disclosure)
    monkeypatch.setattr(
        rod_r2,
        "_execute_diagnostic",
        lambda _exe, _xml, label, _geometry: legacy if label == "legacy_a" else repaired,
    )

    class FakeNEC2:
        async def mesh(self, _geometry: Geometry, _specification: SimulationSpec) -> object:
            return object()

        async def solve(self, _mesh: object, _specification: SimulationSpec) -> object:
            return object()

    expected_stderr = "first diagnostic line\nsecond diagnostic line\nlast line\n"

    def fail_scientific_level(*_args: object, **_kwargs: object) -> None:
        raise rod_r2._RodR2LevelError(
            "nonzero_exit",
            "synthetic scientific failure",
            refinement=1.0,
            stdout_tail=("tail",),
            stderr_text=expected_stderr,
        )

    monkeypatch.setattr(rod_r2, "NEC2Adapter", FakeNEC2)
    monkeypatch.setattr(rod_r2, "_curve", lambda _result: _curve())
    monkeypatch.setattr(rod_r2, "_run_rod_level_r2", fail_scientific_level)
    summary = await rod_r2.run_rod_anchor_r2(tmp_path)
    assert isinstance(summary, rod_r2.RodR2ExecutionFailureSummary)
    assert summary.failure.stderr_text == expected_stderr
    assert summary.failure.stderr_sha256 == _digest(expected_stderr.encode())
    persisted = json.loads(
        (tmp_path / "runs" / rod_r2.ROD_R2_RUN_ID / "summary.json").read_text(encoding="utf-8")
    )
    assert persisted["failure"]["stderr_text"] == expected_stderr


@pytest.mark.asyncio
async def test_fallback_nec2_is_recorded_in_its_real_mode_not_as_subprocess(
    tmp_path: Path,
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_committed_disclosure(tmp_path, disclosure)
    monkeypatch.setattr(rod_r2, "_validate_r1_evidence", lambda _root: None)
    monkeypatch.setattr(
        rod_r2,
        "verify_official_add_lumped_port_source",
        lambda: rod_r2.ROD_R2_OFFICIAL_ADD_LUMPED_PORT_SOURCE_SHA256,
    )
    monkeypatch.setattr(rod_r2, "build_rod_r2_disclosure", lambda _geometry: disclosure)
    monkeypatch.setattr(
        rod_r2.OpenEMSAdapter,
        "_resolve_executable",
        lambda _self: "never-executed-openems",
    )
    legacy, repaired = _passing_diagnostics(disclosure)
    monkeypatch.setattr(
        rod_r2,
        "_execute_diagnostic",
        lambda _exe, _xml, label, _geometry: legacy if label == "legacy_a" else repaired,
    )

    class FakeNEC2:
        async def mesh(self, _geometry: Geometry, _specification: SimulationSpec) -> object:
            return object()

        async def solve(self, _mesh: object, _specification: SimulationSpec) -> object:
            return object()

    fallback = _curve().model_copy(update={"solver_mode": "fallback_analytical"})

    def forbidden_ladder(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("fallback NEC2 must not release the scientific ladder")

    monkeypatch.setattr(rod_r2, "NEC2Adapter", FakeNEC2)
    monkeypatch.setattr(rod_r2, "_curve", lambda _result: fallback)
    monkeypatch.setattr(rod_r2, "_run_rod_level_r2", forbidden_ladder)
    summary = await rod_r2.run_rod_anchor_r2(tmp_path)
    assert isinstance(summary, rod_r2.RodR2ExecutionFailureSummary)
    assert summary.failure.failure_type == "fallback"
    assert summary.solver_mode_counts == {
        "subprocess": 2,
        "fallback_analytical": 1,
    }


@pytest.mark.parametrize("failure_stage", ["termination", "calc_port", "curve"])
def test_normal_exit_postprocess_errors_are_wrapped_with_full_stderr(
    failure_stage: str,
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_stderr = "warning one\nfull diagnostic detail\nwarning last\n"

    class FakeProcess:
        returncode = 0
        pid = 12345

        def __init__(
            self,
            _command: list[str],
            *,
            cwd: Path,
            stdout: object,
            stderr: object,
        ) -> None:
            del cwd
            stdout.write(b"Time for 100 iterations with 1 cells : 1 sec\n")
            stdout.flush()
            stderr.write(expected_stderr.encode("utf-8"))
            stderr.flush()

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(
        rod_r2.OpenEMSAdapter,
        "_resolve_executable",
        lambda _self: "never-executed-openems",
    )
    monkeypatch.setattr(rod_r2.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(rod_r2, "_process_tree_rss_bytes", lambda _pid: 0)
    if failure_stage == "termination":
        monkeypatch.setattr(
            rod_r2,
            "parse_termination",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValueError("synthetic termination parser failure")
            ),
        )
    elif failure_stage == "calc_port":
        monkeypatch.setattr(
            rod_r2,
            "calc_port",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValueError("synthetic port parser failure")
            ),
        )
    else:
        spectra = type("SyntheticSpectra", (), {"s11": [0.0j] * 251})()
        monkeypatch.setattr(rod_r2, "calc_port", lambda *_args, **_kwargs: spectra)
        monkeypatch.setattr(
            rod_r2,
            "_curve_from_spectra",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValueError("synthetic curve conversion failure")
            ),
        )
    with pytest.raises(rod_r2._RodR2LevelError) as caught:
        rod_r2._run_rod_level_r2(
            semifinal_anchor_r2_geometry(),
            disclosure.refinements[0],
        )
    assert caught.value.record.stderr_text == expected_stderr
    assert caught.value.record.stderr_sha256 == _digest(expected_stderr.encode())
    assert caught.value.record.scientific_verdict is None
    assert not caught.value.record.anchor_released


def test_repair_not_confirmed_cli_returns_nonzero(
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    summary = _terminal_summary(disclosure)

    async def fake_run(_repo_root: Path) -> rod_r2.RodR2RunSummary:
        return summary

    monkeypatch.setattr(rod_r2_cli, "run_rod_anchor_r2", fake_run)
    monkeypatch.setattr(sys, "argv", ["semifinal_rod_anchor_r2.py", "--repo-root", str(tmp_path)])
    assert rod_r2_cli.main() == 1
    output = capsys.readouterr().out
    assert "result_status=repair_not_confirmed" in output
    assert "repair_gate_passed=False" in output


def test_existing_summary_loader_accepts_only_fixed_run_id(
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
    tmp_path: Path,
) -> None:
    summary = _terminal_summary(disclosure)
    valid = tmp_path / "valid"
    rod_r2._write_payload(valid, summary)
    assert rod_r2._load_existing(valid) == summary
    payload = summary.model_dump(mode="json")
    payload["run_id"] = "unregistered-run-id"
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "summary.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CrossCheckError, match="run_id"):
        rod_r2._load_existing(invalid)


@pytest.mark.asyncio
async def test_existing_fixed_run_is_idempotently_loaded_without_any_gate(
    disclosure: rod_r2.RodR2BuildOnlyDisclosure,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _terminal_summary(disclosure)
    run_directory = tmp_path / "runs" / rod_r2.ROD_R2_RUN_ID
    rod_r2._write_payload(run_directory, summary)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("existing fixed run must load before rebuilding or solving")

    monkeypatch.setattr(rod_r2, "semifinal_anchor_r2_geometry", forbidden)
    assert await rod_r2.run_rod_anchor_r2(tmp_path) == summary


def test_r1_log_summary_build_only_and_preregistration_bytes_are_immutable() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    r1_run = repo_root / "artifacts" / "runs" / ROD_R1_RUN_ID
    frozen = (
        (r1_run / "log.jsonl", rod_r2.ROD_R1_LOG_SHA256),
        (r1_run / "summary.json", rod_r2.ROD_R1_SUMMARY_SHA256),
        (
            repo_root / ROD_R1_BUILD_ONLY_RELATIVE_PATH,
            rod_r2.ROD_R1_BUILD_ONLY_SHA256,
        ),
        (
            repo_root / "docs" / "semifinal-wifi58-rod-renderer-anchor-r1-preregistration.md",
            rod_r2.ROD_R1_PREREGISTRATION_SHA256,
        ),
    )
    for path, expected in frozen:
        assert path.is_file()
        assert _digest(path.read_bytes()) == expected
