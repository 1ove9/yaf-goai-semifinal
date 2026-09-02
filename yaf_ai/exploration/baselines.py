"""Comparable classic, random, and GP agents for antenna exploration."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from yaf_ai.exploration.environment import (
    AntennaExplorationEnv,
    ExplorationConfig,
    GeometryProposal,
    StepResult,
)
from yaf_ai.exploration.freeform_wire import (
    FREEFORM_SPACE_BASE_VERSION,
    build_freeform_wire,
)
from yaf_ai.exploration.proposal_space import (
    MEANDER_PROPOSAL_SPACE,
    MEANDER_PROPOSAL_SPACE_V2,
    MEANDER_PROPOSAL_SPACE_V21,
    ProposalSpace,
    get_proposal_space,
)
from yaf_ai.exploration.wire import (
    build_box_straight_dipole,
    build_meander_dipole,
)
from yaf_ai.optimization.bayesian import BayesianOptimizer
from yaf_core.domain.geometry import Geometry
from yaf_core.geometry.parametric import ParametricGenerator

C0 = 299_792_458.0


class ExplorationAgent(Protocol):
    """Common runner contract for CLI-selectable exploration agents."""

    async def run(self, environment: AntennaExplorationEnv) -> list[StepResult]:
        """Consume the intended environment budget and return ordered results."""
        ...


def _proposal_from_parameters(
    config: ExplorationConfig,
    parameters: dict[str, float],
    proposer: str,
) -> GeometryProposal:
    get_proposal_space(config.proposal_space_version).validate_parameters(parameters)
    f_center = sum(config.spec.frequency_range) / 2.0
    wavelength = C0 / f_center
    if config.proposal_space_version.startswith(FREEFORM_SPACE_BASE_VERSION):
        node_count = len(parameters) // 3
        return GeometryProposal(
            geometry=build_freeform_wire(parameters, node_count, proposer),
            parameters=parameters,
            proposer=proposer,
        )
    if config.proposal_space_version in {
        MEANDER_PROPOSAL_SPACE.version,
        MEANDER_PROPOSAL_SPACE_V2.version,
        MEANDER_PROPOSAL_SPACE_V21.version,
    }:
        geometry = (
            build_box_straight_dipole(proposer)
            if proposer == "classic"
            else build_meander_dipole(parameters, proposer)
        )
        return GeometryProposal(
            geometry=geometry,
            parameters=parameters,
            proposer=proposer,
        )
    if config.solver == "nec2":
        length = wavelength * parameters["length_ratio"]
        radius = wavelength * parameters["radius_ratio"]
        geometry = Geometry(
            name=f"{proposer}_dipole",
            vertices=[[0.0, 0.0, -length / 2.0], [0.0, 0.0, length / 2.0]],
            faces=[[0, 1]],
            metadata={
                "antenna_class": "wire_dipole",
                "length": length,
                "radius": radius,
                "design_features": parameters,
            },
        )
        return GeometryProposal(
            geometry=geometry,
            parameters=parameters,
            proposer=proposer,
        )

    f_design = f_center * parameters["f_ratio"]
    aspect_scale = float(np.sqrt(parameters["aspect_ratio"]))
    feed_ratio = parameters["feed_ratio"]
    substrate_scale = parameters["substrate_scale"]
    eps_r = 4.4
    substrate_thickness = 1.6e-3
    width = C0 / (2.0 * f_design) * float(np.sqrt(2.0 / (eps_r + 1.0)))
    eps_eff = (eps_r + 1.0) / 2.0 + (eps_r - 1.0) / (
        2.0 * float(np.sqrt(1.0 + 12.0 * substrate_thickness / width))
    )
    delta_length = (
        0.412
        * substrate_thickness
        * (eps_eff + 0.3)
        * (width / substrate_thickness + 0.264)
        / ((eps_eff - 0.258) * (width / substrate_thickness + 0.8))
    )
    length = C0 / (2.0 * f_design * float(np.sqrt(eps_eff))) - 2.0 * delta_length
    width *= aspect_scale
    length /= aspect_scale
    geometry = ParametricGenerator().rectangular_patch(
        width=width,
        length=length,
        substrate_thickness=substrate_thickness,
        substrate_width=substrate_scale * width,
        substrate_length=substrate_scale * length,
        eps_r=eps_r,
        loss_tangent=0.02,
        feed_x=-length * feed_ratio,
    )
    geometry.name = f"{proposer}_patch"
    geometry.metadata["design_features"] = parameters
    return GeometryProposal(
        geometry=geometry,
        parameters=parameters,
        proposer=proposer,
    )


class RandomSearchBaseline:
    """Uniform random sampling over the same bounds used by the GP agent."""

    def __init__(self, config: ExplorationConfig) -> None:
        self.config = config
        self._rng = np.random.default_rng(config.seed)
        proposal_space = get_proposal_space(config.proposal_space_version)
        if not isinstance(proposal_space, ProposalSpace):
            raise ValueError("random continuous baseline requires a continuous space")
        self.proposal_space = proposal_space
        self._bounds = self.proposal_space.bounds

    def propose(self) -> GeometryProposal:
        parameters = {
            name: float(self._rng.uniform(low, high))
            for name, (low, high) in self._bounds.items()
        }
        return _proposal_from_parameters(self.config, parameters, "random")

    async def run(self, environment: AntennaExplorationEnv) -> list[StepResult]:
        results: list[StepResult] = []
        while environment.budget_remaining > 0:
            try:
                results.append(await environment.step(self.propose()))
            except ValueError:
                continue
        return results


class ClassicTemplateBaseline:
    """One deterministic textbook patch or half-wave dipole proposal."""

    def __init__(self, config: ExplorationConfig) -> None:
        self.config = config

    def propose(self) -> GeometryProposal:
        if self.config.solver == "nec2":
            if self.config.proposal_space_version in {
                MEANDER_PROPOSAL_SPACE.version,
                MEANDER_PROPOSAL_SPACE_V2.version,
                MEANDER_PROPOSAL_SPACE_V21.version,
            }:
                parameters = (
                    {
                        "turns": 2.0,
                        "span_ratio": 1.0,
                        "total_length_m": 0.050,
                        "feed_gap_ratio": 0.02,
                        "terminal_ratio": 1.0,
                    }
                    if self.config.proposal_space_version
                    in {
                        MEANDER_PROPOSAL_SPACE_V2.version,
                        MEANDER_PROPOSAL_SPACE_V21.version,
                    }
                    else {
                        "turns": 2.0,
                        "span_ratio": 1.0,
                        "height_ratio": 0.15,
                        "feed_gap_ratio": 0.02,
                        "terminal_ratio": 1.0,
                    }
                )
            else:
                parameters = {"length_ratio": 0.475, "radius_ratio": 0.001}
        else:
            parameters = {
                "f_ratio": 1.0,
                "aspect_ratio": 1.0,
                "feed_ratio": 3.0 / 16.0,
                "substrate_scale": 1.5,
            }
        return _proposal_from_parameters(self.config, parameters, "classic")

    async def run(self, environment: AntennaExplorationEnv) -> list[StepResult]:
        if environment.budget_remaining <= 0:
            return []
        return [await environment.step(self.propose())]


class GPExplorationAgent:
    """Gaussian-process expected-improvement search on the baseline bounds."""

    def __init__(self, config: ExplorationConfig) -> None:
        self.config = config
        proposal_space = get_proposal_space(config.proposal_space_version)
        if not isinstance(proposal_space, ProposalSpace):
            raise ValueError("GP exploration requires a continuous proposal space")
        self.proposal_space = proposal_space
        self._bounds = self.proposal_space.bounds
        self._optimizer = BayesianOptimizer(
            parameter_bounds=self._bounds,
            objective=lambda _parameters: 0.0,
            acquisition="ei",
            n_initial=3,
        )
        self._suggestion_index = 0

    def propose(self) -> GeometryProposal:
        state = np.random.get_state()
        np.random.seed(self.config.seed + self._suggestion_index)
        try:
            point = self._optimizer.suggest()
        finally:
            np.random.set_state(state)
        self._suggestion_index += 1
        parameters = {
            name: float(value)
            for name, value in zip(self._bounds, point, strict=True)
        }
        return _proposal_from_parameters(self.config, parameters, "gp")

    async def run(self, environment: AntennaExplorationEnv) -> list[StepResult]:
        results: list[StepResult] = []
        while environment.budget_remaining > 0:
            try:
                proposal = self.propose()
                result = await environment.step(proposal)
            except ValueError:
                continue
            point = np.array(
                [proposal.parameters[name] for name in self._bounds],
                dtype=float,
            )
            self._optimizer.observe(point, -result.score)
            if (
                self.config.optimizer_window is not None
                and len(self._optimizer.X_observed) > self.config.optimizer_window
            ):
                self._optimizer.X_observed = self._optimizer.X_observed[
                    -self.config.optimizer_window :
                ]
                self._optimizer.y_observed = self._optimizer.y_observed[
                    -self.config.optimizer_window :
                ]
            results.append(result)
        return results
