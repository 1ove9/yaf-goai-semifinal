"""Run the one authorized real 2x patch check after refinement repair."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.patch_mesh_recheck import run_patch_mesh_recheck


def main() -> int:
    try:
        summary = asyncio.run(
            run_patch_mesh_recheck(Path(__file__).resolve().parents[1])
        )
    except CrossCheckError as error:
        print(f"recheck_patch_mesh: {error}", file=sys.stderr)
        return 1
    for mesh in (summary.mesh_1x_after_fix, summary.mesh_2x_after_fix):
        print(
            f"refinement={mesh.refinement:g}x "
            f"lines=({mesh.x.line_count},{mesh.y.line_count},{mesh.z.line_count}) "
            f"cells={mesh.total_cells}"
        )
    print(
        f"ratio={summary.repaired_mesh_decision.total_cell_ratio:.9f} "
        f"predicted={summary.predicted_seconds:.3f}s "
        f"actual={summary.actual_wall_seconds:.3f}s "
        f"f_res={summary.curve.resonance_frequency_hz:.6f}Hz "
        f"shift={summary.resonance_shift:.9%} claim={summary.claim_status}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
