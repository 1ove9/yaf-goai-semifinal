"""Versioned shared parameter spaces for exploration proposers."""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.exploration.pixel import (
    PIXEL_PROPOSAL_SPACES,
    PixelProposalSpace,
)


class ProposalParameter(BaseModel):
    """One named bounded continuous exploration parameter."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    lower: float
    upper: float

    @model_validator(mode="after")
    def validate_interval(self) -> ProposalParameter:
        if not math.isfinite(self.lower) or not math.isfinite(self.upper):
            raise ValueError("proposal parameter bounds must be finite")
        if self.lower >= self.upper:
            raise ValueError("proposal parameter lower bound must be below upper bound")
        return self


class ProposalSpace(BaseModel):
    """Immutable ordered source of parameter names, bounds, and version."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(min_length=1)
    parameters: tuple[ProposalParameter, ...]

    @model_validator(mode="after")
    def validate_names(self) -> ProposalSpace:
        names = [parameter.name for parameter in self.parameters]
        if not names:
            raise ValueError("proposal space must contain at least one parameter")
        if len(names) != len(set(names)):
            raise ValueError("proposal parameter names must be unique")
        return self

    @property
    def bounds(self) -> dict[str, tuple[float, float]]:
        """Return ordered optimizer-compatible parameter bounds."""

        return {
            parameter.name: (parameter.lower, parameter.upper)
            for parameter in self.parameters
        }

    def validate_parameters(self, values: Mapping[str, float]) -> None:
        """Reject missing, extra, non-finite, or out-of-bounds proposals."""

        expected = {parameter.name for parameter in self.parameters}
        received = set(values)
        if received != expected:
            raise ValueError(
                "proposal parameters must match the configured space: "
                f"expected={sorted(expected)}, received={sorted(received)}"
            )
        for parameter in self.parameters:
            value = values[parameter.name]
            if not math.isfinite(value):
                raise ValueError(f"proposal parameter {parameter.name!r} must be finite")
            if value < parameter.lower or value > parameter.upper:
                raise ValueError(
                    f"proposal parameter {parameter.name!r}={value} is outside "
                    f"[{parameter.lower}, {parameter.upper}]"
                )


PATCH_PROPOSAL_SPACE = ProposalSpace(
    version="patch-v2-4d",
    parameters=(
        ProposalParameter(name="f_ratio", lower=0.90, upper=1.10),
        ProposalParameter(name="aspect_ratio", lower=0.85, upper=1.15),
        ProposalParameter(name="feed_ratio", lower=0.10, upper=0.30),
        ProposalParameter(name="substrate_scale", lower=1.25, upper=1.75),
    ),
)

DIPOLE_PROPOSAL_SPACE = ProposalSpace(
    version="dipole-v1-2d",
    parameters=(
        ProposalParameter(name="length_ratio", lower=0.42, upper=0.52),
        ProposalParameter(name="radius_ratio", lower=0.0005, upper=0.0020),
    ),
)

MEANDER_PROPOSAL_SPACE = ProposalSpace(
    version="meander-dipole-v1-5d",
    parameters=(
        ProposalParameter(name="turns", lower=2.0, upper=6.0),
        ProposalParameter(name="span_ratio", lower=0.75, upper=1.0),
        ProposalParameter(name="height_ratio", lower=0.15, upper=0.80),
        ProposalParameter(name="feed_gap_ratio", lower=0.02, upper=0.06),
        ProposalParameter(name="terminal_ratio", lower=0.0, upper=1.0),
    ),
)

MEANDER_PROPOSAL_SPACE_V2 = ProposalSpace(
    version="meander-dipole-v2-5d",
    parameters=(
        ProposalParameter(name="turns", lower=2.0, upper=6.0),
        ProposalParameter(name="span_ratio", lower=0.76, upper=1.0),
        ProposalParameter(name="total_length_m", lower=0.050, upper=0.080),
        ProposalParameter(name="feed_gap_ratio", lower=0.02, upper=0.06),
        ProposalParameter(name="terminal_ratio", lower=0.0, upper=1.0),
    ),
)

MEANDER_PROPOSAL_SPACE_V21 = ProposalSpace(
    version="meander-dipole-v2.1-5d",
    parameters=(
        ProposalParameter(name="turns", lower=2.0, upper=6.0),
        ProposalParameter(name="span_ratio", lower=0.76, upper=1.0),
        ProposalParameter(name="total_length_m", lower=0.050, upper=0.100),
        ProposalParameter(name="feed_gap_ratio", lower=0.02, upper=0.06),
        ProposalParameter(name="terminal_ratio", lower=0.0, upper=1.0),
    ),
)

PROPOSAL_SPACES: Mapping[str, ProposalSpace] = MappingProxyType(
    {
        PATCH_PROPOSAL_SPACE.version: PATCH_PROPOSAL_SPACE,
        DIPOLE_PROPOSAL_SPACE.version: DIPOLE_PROPOSAL_SPACE,
        MEANDER_PROPOSAL_SPACE.version: MEANDER_PROPOSAL_SPACE,
        MEANDER_PROPOSAL_SPACE_V2.version: MEANDER_PROPOSAL_SPACE_V2,
        MEANDER_PROPOSAL_SPACE_V21.version: MEANDER_PROPOSAL_SPACE_V21,
    }
)


def get_proposal_space(version: str) -> ProposalSpace | PixelProposalSpace:
    """Return the registered proposal space for an immutable version identifier."""

    from yaf_ai.exploration.freeform_wire import (  # noqa: PLC0415
        FREEFORM_PROPOSAL_SPACES,
        OCFD_PROPOSAL_SPACE,
    )

    day6_spaces = {
        space.version: space for space in (*FREEFORM_PROPOSAL_SPACES, OCFD_PROPOSAL_SPACE)
    }
    if version in day6_spaces:
        return day6_spaces[version]
    try:
        return PROPOSAL_SPACES[version]
    except KeyError as error:
        try:
            return PIXEL_PROPOSAL_SPACES[version]
        except KeyError:
            raise ValueError(
                f"unknown proposal space version: {version!r}"
            ) from error


def proposal_space_for_solver(solver: str) -> ProposalSpace:
    """Select the supported shared space for a solver family."""

    return DIPOLE_PROPOSAL_SPACE if solver == "nec2" else PATCH_PROPOSAL_SPACE
