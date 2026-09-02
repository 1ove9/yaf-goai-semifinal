"""Integration test: PIPELINE — runs the full inverse design pipeline demo."""

import asyncio

import pytest


def test_pipeline_demo():
    """Run the end-to-end inverse design pipeline and verify it completes."""
    from yaf_ai.inverse_design.pipeline import (
        InverseDesignPipeline,
        PipelineConfig,
    )
    from yaf_core.domain.design import (
        BoundingBox,
        DesignSpec,
    )
    config = PipelineConfig(
        n_candidates=4, top_k=2, max_pipeline_loops=1,
        use_surrogate=True, use_diff_fdtd=False, use_topo=False, use_high_fidelity=False,
    )
    spec = DesignSpec(
        name="test_pipeline", frequency_range=(2.4e9, 2.5e9),
        size_constraint=BoundingBox(x_min=-0.1, x_max=0.1, y_min=-0.1, y_max=0.1, z_min=-0.1, z_max=0.1),
        target_gain_dbi=2.0, material_palette=["copper"],
    )
    pipeline = InverseDesignPipeline(config)
    result = asyncio.run(pipeline.run(spec))
    assert result.loop_count >= 1
    assert len(result.all_candidates) > 0


def test_pipeline_real_physics_oracle():
    """Closed loop with the real solver: generation → screening →
    openEMS FDTD verification. The oracle label must say so."""
    from yaf_ai.inverse_design.pipeline import (
        InverseDesignPipeline,
        PipelineConfig,
    )
    from yaf_core.domain.design import BoundingBox, DesignSpec
    from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

    if OpenEMSAdapter()._resolve_executable() is None:
        pytest.skip("openEMS.exe not installed")

    config = PipelineConfig(
        n_candidates=5, top_k=3, max_pipeline_loops=1,
        use_surrogate=True, use_diff_fdtd=False, use_topo=False,
        # top-2: screening may rank a pixel candidate (fractal/spiral)
        # first — verifying two guarantees a patch (with GP design
        # features) also reaches the oracle
        use_high_fidelity=True, generator="parametric", verify_top_n=2,
    )
    spec = DesignSpec(
        name="oracle_test", frequency_range=(2.2e9, 2.7e9),
        size_constraint=BoundingBox(x_min=-0.1, x_max=0.1, y_min=-0.1,
                                    y_max=0.1, z_min=-0.1, z_max=0.1),
        material_palette=["copper", "fr4"],
        target_vswr=2.0,  # no gain target → no NF2FF, keeps runtime down
    )
    result = asyncio.run(InverseDesignPipeline(config).run(spec))

    assert result.simulation_result is not None
    assert result.oracle_mode == "subprocess"  # real physics, not fallback
    assert result.best_geometry is not None
    assert result.best_metrics["vswr"] > 1.0  # a real, finite match figure
    # step 6 (active learning): the real score was fed back to the GP
    assert result.oracle_observations >= 1


def test_solver_nec2_integration():
    """Integration: run NEC2 solver with a dipole and parse results."""
    from yaf_core.domain.geometry import Geometry
    from yaf_core.domain.simulation import SimulationSpec
    from yaf_solvers.nec2_adapter.adapter import NEC2Adapter

    adapter = NEC2Adapter()
    geom = Geometry()
    spec = SimulationSpec(frequency_range=(2.4e9, 2.5e9), frequency_points=21)
    mesh = asyncio.run(adapter.mesh(geom, spec))
    result = asyncio.run(adapter.solve(mesh, spec))
    assert result.status == "success"
    assert result.gain_dbi is not None
    assert result.vswr is not None
    assert result.s_params is not None


def test_solver_openems_integration():
    """Integration: run openEMS solver and verify result structure."""
    from yaf_core.domain.geometry import Geometry
    from yaf_core.domain.simulation import SimulationSpec
    from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

    adapter = OpenEMSAdapter()
    geom = Geometry()
    spec = SimulationSpec(frequency_range=(2.4e9, 2.5e9), frequency_points=21)
    mesh = asyncio.run(adapter.mesh(geom, spec))
    result = asyncio.run(adapter.solve(mesh, spec))
    assert result.status == "success"
    if result.s_params:
        assert len(result.s_params.frequency) == 21
