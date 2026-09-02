"""Build and count the two preregistered patch meshes without solving them."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.patch_mesh_audit import run_patch_mesh_audit


def main() -> int:
    try:
        summary = asyncio.run(
            run_patch_mesh_audit(Path(__file__).resolve().parents[1])
        )
    except CrossCheckError as error:
        print(f"audit_patch_mesh: {error}", file=sys.stderr)
        return 1
    for mesh in (summary.mesh_1x, summary.mesh_2x):
        print(
            f"refinement={mesh.refinement:g}x "
            f"lines=({mesh.x.line_count},{mesh.y.line_count},{mesh.z.line_count}) "
            f"cells={mesh.total_cells} sha256={mesh.xml_sha256}"
        )
    print(
        f"ratio={summary.decision.total_cell_ratio:.9f} "
        f"interpretation={summary.decision.interpretation} "
        f"claim={summary.decision.claim_status}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
