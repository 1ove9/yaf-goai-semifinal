"""Boundary and XML parsing tests for the patch mesh-count audit."""

from __future__ import annotations

import asyncio

import pytest

from yaf_ai.exploration.patch_mesh_audit import (
    classify_mesh_ratio,
    parse_mesh_statistics,
)
from yaf_ai.exploration.patch_mesh_recheck import classify_recheck_shift
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_core.geometry.parametric import ParametricGenerator
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter


@pytest.mark.parametrize(
    ("ratio", "interpretation", "requires_part2"),
    [
        (1.199999, "ineffective", True),
        (1.2, "partially_supported", True),
        (2.999999, "partially_supported", True),
        (3.0, "effective", False),
    ],
)
def test_mesh_interpretation_boundaries(
    ratio: float, interpretation: str, requires_part2: bool
) -> None:
    decision = classify_mesh_ratio(ratio)
    assert decision.interpretation == interpretation
    assert decision.requires_part2 is requires_part2


def test_mesh_interpretation_rejects_nonpositive_ratio() -> None:
    with pytest.raises(ValueError, match="positive"):
        classify_mesh_ratio(0.0)


def test_parse_mesh_statistics_counts_cells_and_extrema() -> None:
    xml = b"""<?xml version='1.0' encoding='utf-8'?>
<openEMS><ContinuousStructure><RectilinearGrid>
<XLines Qty="3">0,0.25,1</XLines>
<YLines Qty="4">-1,0,2,5</YLines>
<ZLines Qty="2">0,0.5</ZLines>
</RectilinearGrid></ContinuousStructure></openEMS>"""
    stats = parse_mesh_statistics(xml, 2.0)
    assert stats.x.line_count == 3
    assert stats.x.cell_count == 2
    assert stats.x.minimum_cell_size_m == pytest.approx(0.25)
    assert stats.x.maximum_cell_size_m == pytest.approx(0.75)
    assert stats.y.cell_count == 3
    assert stats.z.cell_count == 1
    assert stats.total_cells == 6


def _fixture_patch() -> Geometry:
    return ParametricGenerator.rectangular_patch(
        width=40e-3,
        length=32e-3,
        substrate_thickness=1.524e-3,
        substrate_width=60e-3,
        substrate_length=60e-3,
        eps_r=3.38,
        loss_tangent=1e-3,
        feed_x=-6e-3,
    )


def test_patch_refinement_changes_only_nondefault_xml() -> None:
    geometry = _fixture_patch()
    default = SimulationSpec(
        name="patch-default",
        frequency_range=(1e9, 3e9),
        frequency_points=101,
    )
    explicit_1x = default.model_copy(
        update={"solver_settings": {"openems_mesh_refinement": 1.0}}
    )
    refined_2x = default.model_copy(
        update={"solver_settings": {"openems_mesh_refinement": 2.0}}
    )
    adapter = OpenEMSAdapter()
    mesh = asyncio.run(adapter.mesh(geometry, default))
    default_xml, _ = adapter._build_sim_xml(mesh, default)
    explicit_1x_xml, _ = adapter._build_sim_xml(mesh, explicit_1x)
    refined_2x_xml, _ = adapter._build_sim_xml(mesh, refined_2x)
    assert explicit_1x_xml == default_xml
    assert refined_2x_xml != default_xml
    assert (
        parse_mesh_statistics(refined_2x_xml, 2.0).total_cells
        > parse_mesh_statistics(default_xml, 1.0).total_cells
    )


def test_patch_refinement_rejects_nonpositive_value() -> None:
    geometry = _fixture_patch()
    spec = SimulationSpec(
        name="patch-invalid-refinement",
        frequency_range=(1e9, 3e9),
        frequency_points=11,
        solver_settings={"openems_mesh_refinement": 0.0},
    )
    adapter = OpenEMSAdapter()
    mesh = asyncio.run(adapter.mesh(geometry, spec))
    with pytest.raises(ValueError, match="positive"):
        adapter._build_sim_xml(mesh, spec)


@pytest.mark.parametrize(
    ("shift", "expected"),
    [
        (0.03, "established_after_refinement_repair"),
        (0.0300001, "self_convergence_not_established"),
    ],
)
def test_recheck_uses_inclusive_three_percent_gate(
    shift: float, expected: str
) -> None:
    assert classify_recheck_shift(shift) == expected
