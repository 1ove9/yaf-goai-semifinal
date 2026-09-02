"""Tests for the requirement-driven antenna discovery engine."""

import asyncio

import pytest

from yaf_ai.inverse_design.discovery import AntennaDiscoveryEngine
from yaf_core.domain.discovery import (
    AntennaTopology,
    DiscoveryRequirements,
    EvaluationMode,
)


def _requirements(**overrides) -> DiscoveryRequirements:
    values = {
        "name": "wifi_candidate",
        "frequency_range_hz": (2.35e9, 2.45e9),
        "target_gain_dbi": 4.0,
        "target_vswr": 2.0,
        "minimum_efficiency": 0.65,
        "max_dimensions_m": (0.10, 0.10, 0.03),
        "candidate_budget": 12,
        "generations": 2,
        "verify_top_k": 0,
        "seed": 7,
    }
    values.update(overrides)
    return DiscoveryRequirements(**values)


def test_discovery_explores_and_ranks_diverse_geometries():
    candidates, warnings = asyncio.run(AntennaDiscoveryEngine(_requirements()).run())

    assert len(candidates) == 12
    assert candidates == sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    assert len({candidate.topology for candidate in candidates}) >= 5
    assert all(candidate.geometry.vertices for candidate in candidates)
    assert all(candidate.geometry.faces for candidate in candidates)
    assert all(0 <= candidate.score <= 1 for candidate in candidates)
    assert all(candidate.evaluation_mode is EvaluationMode.ANALYTICAL_SCREENING for candidate in candidates)
    assert any(candidate.generation == 1 and candidate.parent_id for candidate in candidates)
    assert "disabled" in warnings[0].lower()


def test_discovery_is_reproducible_for_a_seed():
    first, _ = asyncio.run(AntennaDiscoveryEngine(_requirements()).run())
    second, _ = asyncio.run(AntennaDiscoveryEngine(_requirements()).run())

    first_signature = [(candidate.topology, candidate.parameters, candidate.score) for candidate in first]
    second_signature = [(candidate.topology, candidate.parameters, candidate.score) for candidate in second]
    assert first_signature == second_signature


def test_high_gain_requirement_prioritizes_directional_topologies():
    requirements = _requirements(
        target_gain_dbi=9.0,
        allowed_topologies=[
            AntennaTopology.DIPOLE,
            AntennaTopology.PATCH,
            AntennaTopology.HORN,
        ],
        candidate_budget=6,
        generations=1,
    )
    candidates, _ = asyncio.run(AntennaDiscoveryEngine(requirements).run())

    assert len(candidates) == requirements.candidate_budget
    assert candidates[0].topology in {AntennaTopology.PATCH, AntennaTopology.HORN}
    assert any(check.key == "gain" for check in candidates[0].checks)


def test_dipole_preview_respects_width_height_depth_contract():
    requirements = _requirements(
        allowed_topologies=[AntennaTopology.DIPOLE],
        max_dimensions_m=(0.01, 0.06, 0.003),
        candidate_budget=4,
        generations=1,
    )
    candidates, _ = asyncio.run(AntennaDiscoveryEngine(requirements).run())

    assert len(candidates) == 4
    for candidate in candidates:
        assert all(check.passed for check in candidate.checks if check.key in {"width", "height", "depth"})


def test_invalid_physical_requirements_are_rejected():
    with pytest.raises(ValueError):
        _requirements(frequency_range_hz=(2.5e9, 2.4e9))
