"""Mock-only validation of pixel topology, evolution, and budget honesty."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from yaf_ai.exploration.environment import AntennaExplorationEnv, ExplorationConfig
from yaf_ai.exploration.pixel import (
    WIFI24_PIXEL_PROPOSAL_SPACE,
    PixelTopology,
    decode_mask_rle,
    encode_mask_rle,
    is_four_connected,
    is_left_right_symmetric,
    mask_sha256,
    pixel_geometry,
)
from yaf_ai.exploration.pixel_agents import EvolvePixelAgent, RandomPixelBaseline
from yaf_ai.exploration.specs import get_spec
from yaf_core.domain.geometry import Geometry, Mesh
from yaf_core.domain.simulation import SimulationResult, SimulationSpec, SParamResult
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter


def _config(seed: int = 7) -> ExplorationConfig:
    return ExplorationConfig(
        spec=get_spec("wifi24"),
        evaluation_budget=2,
        seed=seed,
        proposal_space_version=WIFI24_PIXEL_PROPOSAL_SPACE.version,
    )


def test_connectivity_handles_connected_disconnected_and_single_bridge() -> None:
    connected = np.zeros((5, 5), dtype=bool)
    connected[2, 1:4] = True
    connected[1:4, 3] = True
    assert is_four_connected(connected, (2, 1))

    disconnected = connected.copy()
    disconnected[0, 0] = True
    assert not is_four_connected(disconnected, (2, 1))

    bridged = disconnected.copy()
    bridged[0, 1] = True
    bridged[1, 1] = True
    assert is_four_connected(bridged, (2, 1))
    bridged[1, 1] = False
    assert not is_four_connected(bridged, (2, 1))


def test_symmetry_and_rle_round_trip_are_exact() -> None:
    space = WIFI24_PIXEL_PROPOSAL_SPACE
    mask = space.classic_mask()
    assert is_left_right_symmetric(mask)
    rle = encode_mask_rle(mask)
    restored = decode_mask_rle(rle, space.rows, space.columns)
    assert np.array_equal(mask, restored)
    assert encode_mask_rle(restored) == rle
    asymmetric = mask.copy()
    asymmetric[0, 0] = not bool(asymmetric[0, 0])
    assert not is_left_right_symmetric(asymmetric)


def test_random_and_evolution_are_seed_deterministic() -> None:
    config_a = _config(seed=303)
    config_b = _config(seed=303)
    random_a = RandomPixelBaseline(config_a)
    random_b = RandomPixelBaseline(config_b)
    random_hashes_a = [random_a.propose().topology.sha256 for _ in range(4)]
    random_hashes_b = [random_b.propose().topology.sha256 for _ in range(4)]
    assert random_hashes_a == random_hashes_b

    evolve_a = EvolvePixelAgent(config_a)
    evolve_b = EvolvePixelAgent(config_b)
    evolution_hashes_a: list[str] = []
    evolution_hashes_b: list[str] = []
    for score in (0.4, 0.3, 0.5, 0.45):
        proposal_a = evolve_a.propose()
        proposal_b = evolve_b.propose()
        assert proposal_a.topology is not None
        assert proposal_b.topology is not None
        evolution_hashes_a.append(proposal_a.topology.sha256)
        evolution_hashes_b.append(proposal_b.topology.sha256)
        evolve_a.observe(score)
        evolve_b.observe(score)
    assert evolution_hashes_a == evolution_hashes_b
    assert evolve_a.mutation_k == evolve_b.mutation_k


def _mock_real_solver(monkeypatch: pytest.MonkeyPatch) -> None:
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
        return SimulationResult(
            job_id="00000000-0000-0000-0000-000000000001",
            solver_name="openems",
            solver_version="test",
            status="success",
            s_params=SParamResult(
                frequency=[2.4e9, 2.45e9, 2.5e9],
                s_matrix=[[[0.2 + 0j]], [[0.1 + 0j]], [[0.3 + 0j]]],
            ),
            gain_dbi=5.0,
            efficiency=0.8,
            vswr=1.5,
            solver_metadata={"solver_mode": "subprocess"},
        )

    monkeypatch.setattr(NEC2Adapter, "health_check", fake_health_check)
    monkeypatch.setattr(OpenEMSAdapter, "mesh", fake_mesh)
    monkeypatch.setattr(OpenEMSAdapter, "solve", fake_solve)


@pytest.mark.asyncio
async def test_disconnected_rejection_is_logged_without_consuming_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _mock_real_solver(monkeypatch)
    space = WIFI24_PIXEL_PROPOSAL_SPACE
    config = _config()
    environment = AntennaExplorationEnv(config, runs_root=tmp_path)
    valid = space.classic_mask()
    geometry, _ = pixel_geometry(space, valid, "invalid_test")
    invalid = valid.copy()
    invalid[0, 0] = True
    invalid[0, -1] = True
    topology = PixelTopology(
        rows=space.rows,
        columns=space.columns,
        rle=encode_mask_rle(invalid),
        sha256=mask_sha256(invalid),
        metal_pixels=int(invalid.sum()),
        connected_to_feed=False,
        left_right_symmetric=True,
        iou_vs_classic_rectangle=0.9,
        novelty_vs_classic_rectangle=0.1,
    )
    proposal = RandomPixelBaseline(config).propose().model_copy(
        update={"geometry": geometry, "topology": topology}
    )

    with pytest.raises(ValueError, match="4-connected"):
        await environment.step(proposal)
    assert environment.budget_remaining == config.evaluation_budget
    assert environment.results == ()
    lines = [
        json.loads(line)
        for line in (tmp_path / environment.run_id / "log.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert len(lines) == 1
    assert lines[0]["event_type"] == "rejected"
    assert lines[0]["budget_remaining"] == config.evaluation_budget
