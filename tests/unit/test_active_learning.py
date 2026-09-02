"""Active-learning feedback (pipeline step 6) — proposer behavior.

No solver needed: the GP is driven with synthetic scores and must steer
its patch-design proposals toward the observed optimum.
"""

import numpy as np

from yaf_ai.inverse_design.pipeline import InverseDesignPipeline, PipelineConfig


def _pipeline() -> InverseDesignPipeline:
    return InverseDesignPipeline(PipelineConfig(generator="parametric"))


class TestPatchProposer:
    def test_proposals_stay_in_bounds(self):
        np.random.seed(7)
        p = _pipeline()
        for _ in range(20):
            f_ratio, feed_ratio = p._next_patch_params()
            assert 0.90 <= f_ratio <= 1.10
            assert 0.10 <= feed_ratio <= 0.30

    def test_gp_steers_toward_observed_optimum(self):
        np.random.seed(7)
        p = _pipeline()
        peak = np.array([1.06, 0.24])
        # synthetic real-solver scores: best design at `peak`
        for f in (0.92, 0.96, 1.00, 1.02, 1.04, 1.06, 1.08, 0.94):
            for feed in (0.12, 0.20, 0.24, 0.28):
                x = np.array([f, feed])
                score = float(np.exp(-40 * np.sum((x - peak) ** 2)))
                p._patch_bo.observe(x, -score)

        proposals = np.array([p._next_patch_params() for _ in range(24)])
        mean_dist = float(np.mean(np.linalg.norm(proposals - peak, axis=1)))
        # uniform sampling over the bounds averages ~0.09 distance to
        # the peak; a working GP/EI proposer concentrates well inside
        assert mean_dist < 0.05

    def test_candidates_carry_design_features(self):
        np.random.seed(7)
        p = _pipeline()
        from yaf_core.domain.design import BoundingBox, DesignSpec

        spec = DesignSpec(
            name="t", frequency_range=(2.2e9, 2.7e9),
            size_constraint=BoundingBox(x_min=-0.1, x_max=0.1, y_min=-0.1,
                                        y_max=0.1, z_min=-0.1, z_max=0.1),
            material_palette=["copper"],
        )
        cands = p._parametric_candidates(spec, 10)
        patches = [g for g in cands if g.name.startswith("patch_")]
        assert patches
        for g in patches:
            feats = g.metadata["design_features"]
            assert 0.90 <= feats["f_ratio"] <= 1.10
            assert 0.10 <= feats["feed_ratio"] <= 0.30
            # feed position actually follows the proposed ratio
            assert g.metadata["feed_x"] < 0

    def test_planar_candidates_are_pixel_patches(self):
        np.random.seed(7)
        p = _pipeline()
        from yaf_core.domain.design import BoundingBox, DesignSpec

        spec = DesignSpec(
            name="t", frequency_range=(2.2e9, 2.7e9),
            size_constraint=BoundingBox(x_min=-0.1, x_max=0.1, y_min=-0.1,
                                        y_max=0.1, z_min=-0.1, z_max=0.1),
            material_palette=["copper"],
        )
        cands = p._parametric_candidates(spec, 10)
        by_kind = {g.name.split("_")[0]: g for g in cands}
        for kind in ("spiral", "fractal"):
            md = by_kind[kind].metadata
            assert md["antenna_class"] == "pixel_patch"
            assert md["eps_r"] > 1
        # horns remain honestly unsupported (need a waveguide port)
        assert "antenna_class" not in by_kind["horn"].metadata
