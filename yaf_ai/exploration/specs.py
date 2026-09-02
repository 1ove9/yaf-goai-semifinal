"""Frozen named specifications for repeatable antenna exploration."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from pydantic import ConfigDict

from yaf_core.domain.design import BoundingBox, DesignSpec, Polarization


class ExplorationSpec(DesignSpec):
    """Immutable registered design specification."""

    model_config = ConfigDict(frozen=True)


def _scaled_box(scale: float) -> BoundingBox:
    return BoundingBox(
        x_min=-0.06 * scale,
        x_max=0.06 * scale,
        y_min=-0.06 * scale,
        y_max=0.06 * scale,
        z_min=-0.01 * scale,
        z_max=0.01 * scale,
    )


WIFI24_SPEC = ExplorationSpec(
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

WIFI58_SPEC = ExplorationSpec(
    name="wifi58_exploration",
    frequency_range=(5.725e9, 5.875e9),
    target_gain_dbi=6.0,
    polarization=Polarization.LINEAR,
    bandwidth_target=0.15e9 / 5.80e9,
    efficiency_target=0.70,
    size_constraint=_scaled_box(2.45e9 / 5.80e9),
    material_palette=["copper", "fr4"],
    target_vswr=2.0,
)

N78_SPEC = ExplorationSpec(
    name="n78_exploration",
    frequency_range=(3.30e9, 3.80e9),
    target_gain_dbi=6.0,
    polarization=Polarization.LINEAR,
    bandwidth_target=0.50e9 / 3.55e9,
    efficiency_target=0.70,
    size_constraint=_scaled_box(2.45e9 / 3.55e9),
    material_palette=["copper", "fr4"],
    target_vswr=2.0,
)

SPEC_NAMES: tuple[str, ...] = ("wifi24", "wifi58", "n78")
SPEC_REGISTRY: Mapping[str, ExplorationSpec] = MappingProxyType(
    {
        "wifi24": WIFI24_SPEC,
        "wifi58": WIFI58_SPEC,
        "n78": N78_SPEC,
    }
)


def get_spec(name: str) -> ExplorationSpec:
    """Return an isolated frozen copy of a registered specification."""

    try:
        return SPEC_REGISTRY[name].model_copy(deep=True)
    except KeyError as error:
        choices = ", ".join(SPEC_NAMES)
        raise ValueError(f"unknown exploration spec {name!r}; choose from {choices}") from error
