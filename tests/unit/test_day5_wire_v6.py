"""Regression tests for the preregistered Day 5 meander space and attribution."""

from __future__ import annotations

import asyncio
from itertools import product
from pathlib import Path

import pytest

from yaf_ai.exploration.baselines import GPExplorationAgent, RandomSearchBaseline
from yaf_ai.exploration.batch import (
    BatchRunRecord,
    RunExecution,
    load_batch_config,
    run_wire_batch,
)
from yaf_ai.exploration.environment import ExplorationConfig
from yaf_ai.exploration.proposal_space import (
    MEANDER_PROPOSAL_SPACE_V2,
    MEANDER_PROPOSAL_SPACE_V21,
)
from yaf_ai.exploration.specs import get_spec
from yaf_ai.exploration.wire import (
    MINIMUM_PITCH_M,
    build_meander_dipole,
    validate_meander_geometry,
    wire_spec_updates,
)
from yaf_ai.exploration.wire_convergence import (
    classify_segmentation_convergence,
)
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter


def _config_v2() -> ExplorationConfig:
    return ExplorationConfig(
        spec=get_spec("wifi24").model_copy(update=wire_spec_updates()),
        evaluation_budget=1,
        seed=101,
        solver="nec2",
        proposal_space_version=MEANDER_PROPOSAL_SPACE_V2.version,
    )


def _v2_parameters(total_length_m: float = 0.061182134285714284) -> dict[str, float]:
    return {
        "turns": 5.0,
        "span_ratio": 0.88,
        "total_length_m": total_length_m,
        "feed_gap_ratio": 0.04,
        "terminal_ratio": 0.5,
    }


def test_v2_space_directly_covers_target_electrical_length() -> None:
    target = 299_792_458.0 / (2.0 * 2.45e9)
    geometry = build_meander_dipole(_v2_parameters(target), "test")
    validate_meander_geometry(geometry)
    assert float(geometry.metadata["total_wire_length_m"]) == pytest.approx(
        target, abs=1e-12
    )
    low, high = MEANDER_PROPOSAL_SPACE_V2.bounds["total_length_m"]
    assert low < target < high


def test_v2_all_boundary_combinations_are_valid_and_cover_50_to_80_mm() -> None:
    names = tuple(MEANDER_PROPOSAL_SPACE_V2.bounds)
    values: list[tuple[float, ...]] = []
    for name, (lower, upper) in MEANDER_PROPOSAL_SPACE_V2.bounds.items():
        values.append(
            tuple(float(item) for item in range(2, 7))
            if name == "turns"
            else (lower, upper)
        )
    lengths: list[float] = []
    pitches: list[float] = []
    for combination in product(*values):
        parameters = dict(zip(names, combination, strict=True))
        geometry = build_meander_dipole(parameters, "boundary")
        validate_meander_geometry(geometry)
        lengths.append(float(geometry.metadata["total_wire_length_m"]))
        pitches.append(float(geometry.metadata["minimum_pitch_m"]))
    assert len(lengths) == 80
    assert min(lengths) == pytest.approx(0.050, abs=1e-12)
    assert max(lengths) == pytest.approx(0.080, abs=1e-12)
    assert min(pitches) >= MINIMUM_PITCH_M - 1e-12


def test_v2_gp_and_random_share_the_registered_space() -> None:
    gp = GPExplorationAgent(_config_v2())
    random = RandomSearchBaseline(_config_v2())
    assert gp.proposal_space is MEANDER_PROPOSAL_SPACE_V2
    assert random.proposal_space is MEANDER_PROPOSAL_SPACE_V2
    assert gp.proposal_space.bounds == random.proposal_space.bounds


def test_v21_retry_space_covers_diagnosed_length_without_invalid_corners() -> None:
    names = tuple(MEANDER_PROPOSAL_SPACE_V21.bounds)
    values: list[tuple[float, ...]] = []
    for name, (lower, upper) in MEANDER_PROPOSAL_SPACE_V21.bounds.items():
        values.append(
            tuple(float(item) for item in range(2, 7))
            if name == "turns"
            else (lower, upper)
        )
    lengths: list[float] = []
    for combination in product(*values):
        parameters = dict(zip(names, combination, strict=True))
        geometry = build_meander_dipole(parameters, "retry-boundary")
        validate_meander_geometry(geometry)
        lengths.append(float(geometry.metadata["total_wire_length_m"]))
    assert len(lengths) == 80
    assert min(lengths) == pytest.approx(0.050, abs=1e-12)
    assert max(lengths) == pytest.approx(0.100, abs=1e-12)


@pytest.mark.asyncio
async def test_v6r2_batch_uses_v21_space_and_frozen_400_by_5_matrix(
    tmp_path: Path,
) -> None:
    async def executor(
        record: BatchRunRecord, _runs_root: Path
    ) -> RunExecution:
        return RunExecution(duration_seconds=0.1, steps_completed=record.budget)

    await run_wire_batch(
        "day5-wire-v6r2",
        repo_root=tmp_path,
        executor=executor,
    )
    document = load_batch_config(
        tmp_path / "runs" / "batch_day5-wire-v6r2" / "config.json"
    )
    assert document.config.proposal_space == MEANDER_PROPOSAL_SPACE_V21
    assert document.config.budget == 400
    assert document.config.seeds == (101, 202, 303, 404, 505)


@pytest.mark.parametrize(
    ("gaps", "expected"),
    [
        ((0.12, 0.08, 0.059), "instrument_boundary"),
        ((0.12, 0.08, 0.060), "inconclusive_needs_finer_segmentation"),
        ((0.12, 0.11, 0.096), "genuine_anomaly"),
        ((0.12, 0.13, 0.05), "inconclusive_needs_finer_segmentation"),
    ],
)
def test_segmentation_attribution_boundaries(
    gaps: tuple[float, float, float], expected: str
) -> None:
    result = classify_segmentation_convergence(gaps)
    assert result.verdict == expected


def test_solver_refinement_settings_change_native_discretization() -> None:
    geometry = build_meander_dipole(_v2_parameters(), "test")
    coarse = SimulationSpec(
        frequency_range=(1.5e9, 3.5e9),
        frequency_points=11,
        far_field_request=None,
        solver_settings={"nec2_segments_per_wavelength": 20},
    )
    fine = coarse.model_copy(
        update={"solver_settings": {"nec2_segments_per_wavelength": 80}}
    )
    adapter = NEC2Adapter()
    mesh = asyncio.run(adapter.mesh(geometry, coarse))
    coarse_deck = adapter._build_nec_deck(mesh, coarse).to_bytes().decode("ascii")
    fine_deck = adapter._build_nec_deck(mesh, fine).to_bytes().decode("ascii")
    coarse_segments = sum(
        int(line.split()[2])
        for line in coarse_deck.splitlines()
        if line.startswith("GW")
    )
    fine_segments = sum(
        int(line.split()[2])
        for line in fine_deck.splitlines()
        if line.startswith("GW")
    )
    assert fine_segments > coarse_segments

    openems = OpenEMSAdapter()
    openems_mesh = asyncio.run(openems.mesh(geometry, coarse))
    default_xml, _ = openems._build_sim_xml(openems_mesh, coarse)
    refined_spec = coarse.model_copy(
        update={"solver_settings": {"openems_mesh_refinement": 2.0}}
    )
    refined_xml, _ = openems._build_sim_xml(openems_mesh, refined_spec)
    assert default_xml != refined_xml
