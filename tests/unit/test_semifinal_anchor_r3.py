"""Tests for the bounded semifinal 5.8 GHz anchor r3."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from yaf_ai.exploration.cross_check import SolverCurve
from yaf_ai.exploration.patch_mesh_audit import (
    MeshAxisStatistics,
    PatchMeshStatistics,
)
from yaf_ai.exploration.semifinal_anchor import MonitoredOpenEMSResult
from yaf_ai.exploration.semifinal_anchor_r2 import (
    R1_LOG_SHA256,
    R1_SUMMARY_SHA256,
    R2_GEOMETRY_SHA256,
    R2_RUN_ID,
    R2_SWEEP_HZ,
    SemifinalAnchorR2Summary,
    semifinal_anchor_r2_geometry,
)
from yaf_ai.exploration.semifinal_anchor_r3 import (
    R2_LOG_SHA256,
    R2_SUMMARY_SHA256_FROZEN,
    R3_AGREEMENT_REFINEMENT,
    R3_CONVERGENCE_PAIR,
    R3_OPENEMS_REFINEMENTS,
    compare_with_r2,
    evaluate_semifinal_anchor_r3,
    full_sweep_interior_minimum,
    full_sweep_shift,
    richardson_estimate,
    run_openems_r3_ladder,
)
from yaf_core.domain.geometry import Geometry


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


def test_r3_reuses_exact_r2_geometry_sha256() -> None:
    geometry = semifinal_anchor_r2_geometry()
    from yaf_ai.exploration.semifinal_anchor_r2 import (
        validate_semifinal_anchor_r2_geometry,
    )

    assert validate_semifinal_anchor_r2_geometry(geometry) == R2_GEOMETRY_SHA256


def test_r3_ladder_is_exact_and_has_no_adaptive_stop() -> None:
    calls: list[float] = []

    def runner(
        geometry: Geometry,
        *,
        refinement: float,
        run_id: str,
    ) -> MonitoredOpenEMSResult:
        del geometry, run_id
        calls.append(refinement)
        return _monitored(refinement, _curve("openems", 5.60e9))

    results = run_openems_r3_ladder(
        semifinal_anchor_r2_geometry(),
        "fixed-r3-ladder",
        runner=runner,
    )
    assert R3_OPENEMS_REFINEMENTS == (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
    assert calls == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
    assert tuple(result.refinement for result in results) == R3_OPENEMS_REFINEMENTS


def test_r3_decision_inputs_are_only_terminal_pair_and_32x_agreement() -> None:
    assert R3_CONVERGENCE_PAIR == (16.0, 32.0)
    assert R3_AGREEMENT_REFINEMENT == 32.0
    decision = evaluate_semifinal_anchor_r3(
        _curve("nec2", 5.80e9),
        _curve("openems", 5.82e9),
        _curve("openems", 5.80e9),
    )
    assert decision.openems_16x_to_32x_resonance_shift == (
        abs(5.82e9 - 5.80e9) / 5.80e9
    )
    assert decision.cross_solver_decision is not None
    assert decision.cross_solver_decision.resonance_relative_difference == 0.0
    assert decision.verdict == "released"


def test_full_sweep_internal_minimum_is_defined_outside_target_band() -> None:
    curve = _curve("openems", 5.70e9, depth_db=-2.0)
    minimum = full_sweep_interior_minimum(curve)
    assert minimum.valid
    assert minimum.minimum_frequency_hz == 5.70e9
    assert minimum.minimum_s11_db == -2.0
    assert full_sweep_shift(curve, _curve("openems", 5.80e9)) == (
        abs(5.70e9 - 5.80e9) / 5.80e9
    )


def test_only_32x_has_target_band_depth_requirement() -> None:
    decision = evaluate_semifinal_anchor_r3(
        _curve("nec2", 5.80e9),
        _curve("openems", 5.80e9, depth_db=-1.0),
        _curve("openems", 5.80e9, depth_db=-14.0),
    )
    assert decision.openems_16x_full_sweep_minimum.valid
    assert decision.openems_16x_full_sweep_minimum.minimum_s11_db == -1.0
    assert decision.openems_32x_validity.depth_threshold_met
    assert decision.verdict == "released"


def test_r3_non_convergence_has_priority_over_high_side() -> None:
    decision = evaluate_semifinal_anchor_r3(
        _curve("nec2", 5.80e9),
        _curve("openems", 5.60e9),
        _curve("openems", 5.90e9),
    )
    assert not decision.openems_convergence_met
    assert decision.verdict == "not_released_not_converged"
    assert not decision.anchor_released


def test_r3_converged_high_side_has_terminal_verdict() -> None:
    decision = evaluate_semifinal_anchor_r3(
        _curve("nec2", 5.80e9),
        _curve("openems", 5.90e9),
        _curve("openems", 5.90e9),
    )
    assert decision.openems_convergence_met
    assert decision.verdict == "not_released_out_of_band_high"
    assert not decision.anchor_released


def test_r3_band_valid_agreement_failure_is_distinct() -> None:
    decision = evaluate_semifinal_anchor_r3(
        _curve("nec2", 5.74e9),
        _curve("openems", 5.86e9),
        _curve("openems", 5.86e9),
    )
    assert decision.nec2_validity.valid
    assert decision.openems_32x_validity.valid
    assert decision.openems_convergence_met
    assert decision.cross_solver_decision is not None
    assert decision.cross_solver_decision.verdict == "DIVERGENT"
    assert decision.verdict == "not_released_agreement"


def test_richardson_uses_only_fixed_finest_three() -> None:
    estimate = richardson_estimate(
        _curve("openems", 5.60e9),
        _curve("openems", 5.68e9),
        _curve("openems", 5.72e9),
    )
    assert estimate.refinements == (8.0, 16.0, 32.0)
    assert estimate.status == "computed"
    assert estimate.estimated_order == 1.0
    assert estimate.estimated_limit_frequency_hz == 5.76e9
    assert not estimate.affects_verdict


def test_r2_reproduction_is_raw_and_non_decisional() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source = SemifinalAnchorR2Summary.model_validate_json(
        (
            repo_root
            / "artifacts"
            / "runs"
            / R2_RUN_ID
            / "summary.json"
        ).read_text(encoding="utf-8")
    )
    rows = compare_with_r2(
        source,
        (
            _monitored(1.0, source.openems_1x.curve),
            _monitored(2.0, source.openems_2x.curve),
            _monitored(4.0, source.openems_4x.curve),
            _monitored(8.0, source.openems_8x.curve),
        ),
    )
    assert tuple(row.refinement for row in rows) == (1.0, 2.0, 4.0, 8.0)
    assert all(row.frequency_difference_hz == 0.0 for row in rows)
    assert all(row.s11_difference_db == 0.0 for row in rows)
    assert all(not row.affects_verdict for row in rows)


def test_r1_and_r2_archived_evidence_sha256_are_immutable() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    runs = repo_root / "artifacts" / "runs"
    r1 = runs / "semifinal-wifi58-meander-renderer-anchor-r1-combined"
    r2 = runs / R2_RUN_ID
    assert hashlib.sha256((r1 / "log.jsonl").read_bytes()).hexdigest() == R1_LOG_SHA256
    assert (
        hashlib.sha256((r1 / "summary.json").read_bytes()).hexdigest()
        == R1_SUMMARY_SHA256
    )
    assert hashlib.sha256((r2 / "log.jsonl").read_bytes()).hexdigest() == R2_LOG_SHA256
    assert (
        hashlib.sha256((r2 / "summary.json").read_bytes()).hexdigest()
        == R2_SUMMARY_SHA256_FROZEN
    )
