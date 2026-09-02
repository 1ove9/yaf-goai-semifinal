"""Unit tests for the auditable exploration environment."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from yaf_ai.exploration.baselines import ClassicTemplateBaseline, RandomSearchBaseline
from yaf_ai.exploration.environment import (
    AntennaExplorationEnv,
    DiscoveryPolicy,
    DiscoverySignal,
    EvaluationBudgetExhaustedError,
    ExplorationConfig,
    assess_discovery,
    geometry_hash,
)
from yaf_ai.exploration.logger import ExplorationLogger
from yaf_core.domain.design import BoundingBox, DesignSpec
from yaf_core.domain.geometry import Geometry, Mesh
from yaf_core.domain.simulation import SimulationResult, SimulationSpec, SParamResult
from yaf_solvers.base import SolverUnavailableError
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter


def _config(*, budget: int = 2, seed: int = 42) -> ExplorationConfig:
    return ExplorationConfig(
        spec=DesignSpec(
            name="test_wifi24",
            frequency_range=(2.4e9, 2.5e9),
            target_gain_dbi=6.0,
            efficiency_target=0.7,
            target_vswr=2.0,
            size_constraint=BoundingBox(
                x_min=-0.06,
                x_max=0.06,
                y_min=-0.06,
                y_max=0.06,
                z_min=-0.01,
                z_max=0.01,
            ),
        ),
        evaluation_budget=budget,
        seed=seed,
        solver="openems",
    )


def _patch_fake_solver(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str = "subprocess",
    error: Exception | None = None,
) -> None:
    async def fake_health_check(_self: NEC2Adapter) -> bool:
        return False

    async def fake_mesh(
        _self: OpenEMSAdapter,
        geometry: Geometry,
        _spec: SimulationSpec,
    ) -> Mesh:
        return Mesh(
            geometry_id=geometry.id,
            solver_name="openems",
            nodes=geometry.vertices,
            elements=geometry.faces,
        )

    async def fake_solve(
        _self: OpenEMSAdapter,
        _mesh: Mesh,
        _spec: SimulationSpec,
        progress_callback: Callable[[float], Any] | None = None,
    ) -> SimulationResult:
        if error is not None:
            raise error
        if progress_callback is not None:
            progress_callback(1.0)
        return SimulationResult(
            job_id="00000000-0000-0000-0000-000000000001",
            solver_name="openems",
            solver_version="test",
            status="success",
            s_params=SParamResult(
                frequency=[2.4e9, 2.45e9, 2.5e9],
                s_matrix=[[[0.2 + 0j]], [[0.1 + 0j]], [[0.3 + 0j]]],
            ),
            gain_dbi=5.5,
            efficiency=0.8,
            vswr=1.5,
            solver_metadata={"solver_mode": mode},
        )

    monkeypatch.setattr(NEC2Adapter, "health_check", fake_health_check)
    monkeypatch.setattr(OpenEMSAdapter, "mesh", fake_mesh)
    monkeypatch.setattr(OpenEMSAdapter, "solve", fake_solve)


@pytest.mark.asyncio
async def test_budget_logging_and_solver_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_fake_solver(monkeypatch)
    config = _config(budget=2)
    environment = AntennaExplorationEnv(config, runs_root=tmp_path)
    initial = environment.reset()
    proposal = ClassicTemplateBaseline(config).propose()

    assert initial.budget_remaining == 2
    first = await environment.step(proposal)
    second = await environment.step(proposal)
    assert environment.observation().budget_remaining == 0
    assert first.solver_mode == "subprocess"
    assert first.metrics["min_s11_db"] == pytest.approx(-20.0)
    assert second.step_index == 1
    with pytest.raises(EvaluationBudgetExhaustedError):
        await environment.step(proposal)

    summary_path = environment.finish()
    records = ExplorationLogger.load_steps(summary_path.parent / "log.jsonl")
    assert len(records) == 2
    record = records[0]
    assert record.step_index == 0
    assert record.seed == config.seed
    assert record.config_hash
    assert record.geometry_hash == first.geometry_hash
    assert record.geometry_summary["num_vertices"] > 0
    assert record.metrics == first.metrics
    assert record.score == first.score
    assert record.solver_mode == "subprocess"
    assert summary_path.exists()
    assert b"\r" not in (summary_path.parent / "log.jsonl").read_bytes()
    assert b"\r" not in summary_path.read_bytes()


def test_random_search_seed_is_reproducible() -> None:
    config_a = _config(budget=3, seed=7)
    config_b = _config(budget=3, seed=7)
    baseline_a = RandomSearchBaseline(config_a)
    baseline_b = RandomSearchBaseline(config_b)

    hashes_a = [geometry_hash(baseline_a.propose().geometry) for _ in range(3)]
    hashes_b = [geometry_hash(baseline_b.propose().geometry) for _ in range(3)]
    assert hashes_a == hashes_b
    assert len(set(hashes_a)) == 3


@pytest.mark.asyncio
async def test_solver_unavailable_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    unavailable = SolverUnavailableError("openems", "fake", "test solver missing")
    _patch_fake_solver(monkeypatch, error=unavailable)
    config = _config(budget=1)
    environment = AntennaExplorationEnv(config, runs_root=tmp_path)

    with pytest.raises(SolverUnavailableError, match="test solver missing"):
        await environment.step(ClassicTemplateBaseline(config).propose())
    assert environment.budget_remaining == 1
    assert environment.results == ()


@pytest.mark.asyncio
async def test_fallback_mode_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_fake_solver(monkeypatch, mode="fallback_analytical")
    config = _config(budget=1)
    environment = AntennaExplorationEnv(config, runs_root=tmp_path)

    with pytest.raises(SolverUnavailableError, match="requires real physics"):
        await environment.step(ClassicTemplateBaseline(config).propose())


def test_discovery_signals_are_predeclared() -> None:
    policy = DiscoveryPolicy()
    disagreement = assess_discovery(
        candidate_scores=[0.9],
        random_scores=[0.5],
        classic_score=0.7,
        nec2_min_s11_db=-18.0,
        openems_min_s11_db=-12.0,
        policy=policy,
    )
    assert disagreement.signal is DiscoverySignal.SOLVER_DISAGREEMENT

    positive = assess_discovery(
        candidate_scores=[0.9],
        random_scores=[0.5],
        classic_score=0.8,
        nec2_min_s11_db=-16.0,
        openems_min_s11_db=-14.0,
        policy=policy,
    )
    assert positive.signal is DiscoverySignal.POSITIVE
    assert positive.classic_improvement_fraction == pytest.approx(0.125)

    negative = assess_discovery(
        candidate_scores=[0.3, 0.4, 0.5],
        random_scores=[0.6, 0.7, 0.8],
        classic_score=0.8,
        nec2_min_s11_db=None,
        openems_min_s11_db=None,
        policy=policy,
    )
    assert negative.signal is DiscoverySignal.NEGATIVE
    assert math.isclose(negative.candidate_mean_score or 0.0, 0.4)
