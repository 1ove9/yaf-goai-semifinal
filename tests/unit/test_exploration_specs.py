"""Tests for registered specs and the shared proposal space."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from yaf_ai.exploration.baselines import GPExplorationAgent, RandomSearchBaseline
from yaf_ai.exploration.environment import (
    AntennaExplorationEnv,
    ExplorationConfig,
    GeometryProposal,
)
from yaf_ai.exploration.proposal_space import PATCH_PROPOSAL_SPACE
from yaf_ai.exploration.specs import get_spec
from yaf_core.domain.design import BoundingBox, DesignSpec, Polarization


def _day1_wifi24_spec() -> DesignSpec:
    return DesignSpec(
        name="wifi24_exploration",
        frequency_range=(2.40e9, 2.50e9),
        target_gain_dbi=6.0,
        polarization=Polarization.LINEAR,
        bandwidth_target=0.04,
        efficiency_target=0.70,
        size_constraint=BoundingBox(
            x_min=-0.06,
            x_max=0.06,
            y_min=-0.06,
            y_max=0.06,
            z_min=-0.01,
            z_max=0.01,
        ),
        material_palette=["copper", "fr4"],
        target_vswr=2.0,
    )


def _config() -> ExplorationConfig:
    return ExplorationConfig(
        spec=get_spec("wifi24"),
        evaluation_budget=1,
        seed=7,
        solver="openems",
        proposal_space_version=PATCH_PROPOSAL_SPACE.version,
    )


def test_wifi24_registry_entry_matches_day1_field_for_field() -> None:
    registered = get_spec("wifi24")

    assert registered.model_dump(mode="json") == _day1_wifi24_spec().model_dump(
        mode="json"
    )
    with pytest.raises(ValidationError):
        registered.name = "drifted"


def test_high_frequency_specs_have_sensible_scaling() -> None:
    wifi24 = get_spec("wifi24")
    wifi58 = get_spec("wifi58")
    n78 = get_spec("n78")

    assert wifi58.frequency_range == (5.725e9, 5.875e9)
    assert n78.frequency_range == (3.30e9, 3.80e9)
    assert wifi58.size_constraint.dimensions[0] == pytest.approx(
        wifi24.size_constraint.dimensions[0] * 2.45 / 5.80
    )
    assert n78.size_constraint.dimensions[0] == pytest.approx(
        wifi24.size_constraint.dimensions[0] * 2.45 / 3.55
    )
    assert n78.bandwidth_target is not None
    assert wifi24.bandwidth_target is not None
    assert n78.bandwidth_target > wifi24.bandwidth_target


def test_gp_and_random_share_one_proposal_space() -> None:
    config = _config()
    gp = GPExplorationAgent(config)
    random = RandomSearchBaseline(config)

    assert gp.proposal_space is PATCH_PROPOSAL_SPACE
    assert random.proposal_space is PATCH_PROPOSAL_SPACE
    assert gp.proposal_space.bounds == random.proposal_space.bounds
    assert tuple(gp.proposal_space.bounds) == (
        "f_ratio",
        "aspect_ratio",
        "feed_ratio",
        "substrate_scale",
    )


@pytest.mark.asyncio
async def test_environment_rejects_out_of_bounds_action(tmp_path: Path) -> None:
    config = _config()
    proposal = RandomSearchBaseline(config).propose()
    invalid_parameters = dict(proposal.parameters)
    invalid_parameters["feed_ratio"] = 0.31
    invalid = GeometryProposal(
        geometry=proposal.geometry,
        parameters=invalid_parameters,
        proposer=proposal.proposer,
    )
    environment = AntennaExplorationEnv(config, runs_root=tmp_path)

    with pytest.raises(ValueError, match="outside"):
        await environment.step(invalid)
