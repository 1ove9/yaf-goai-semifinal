"""Write the patch mesh-count addendum from its two archived source runs."""

from __future__ import annotations

import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.patch_mesh_addendum import write_patch_mesh_addendum


def main() -> int:
    try:
        addendum = write_patch_mesh_addendum(
            Path(__file__).resolve().parents[1]
        )
    except CrossCheckError as error:
        print(f"analyze_patch_mesh_addendum: {error}", file=sys.stderr)
        return 1
    print(
        f"pre_fix={addendum.pre_fix_audit.decision.interpretation} "
        f"post_fix={addendum.repaired_recheck.repaired_mesh_decision.interpretation} "
        f"claim={addendum.final_self_convergence_claim} "
        f"verdict={addendum.final_cross_solver_verdict}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
