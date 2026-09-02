"""Apply protocol v2.1 once to the frozen final patch curves and archive it."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.patch_final_cross_check import (
    run_patch_final_cross_check,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        summary = run_patch_final_cross_check(repo_root)
        subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts" / "archive_run.py"),
                summary.run_id,
                "--role",
                "other",
                "--note",
                (
                    "patch-final unique-candidate protocol-v2.1 "
                    f"source={summary.source_run_id}"
                ),
            ],
            cwd=repo_root,
            check=True,
        )
    except (CrossCheckError, subprocess.CalledProcessError) as error:
        print(f"patch_final_cross_check: {error}", file=sys.stderr)
        return 1
    decision = summary.decision
    print(
        f"run_id={summary.run_id} verdict={decision.verdict} "
        f"openems_valid={decision.openems_validity.valid} "
        f"nec2_valid={decision.nec2_validity.valid}"
    )
    print(
        f"openems_f_res={summary.openems.resonance_frequency_hz:.6f} "
        f"openems_s11={summary.openems.resonance_s11_db:.9f} "
        f"openems_index={decision.openems_validity.minimum_index}"
    )
    print(
        f"nec2_f_res={summary.nec2.resonance_frequency_hz:.6f} "
        f"nec2_s11={summary.nec2.resonance_s11_db:.9f} "
        f"nec2_index={decision.nec2_validity.minimum_index}"
    )
    print(
        f"gap={decision.resonance_relative_difference} "
        f"pearson={decision.curve_pearson_correlation} "
        f"depth_difference_db={decision.s11_depth_difference_db}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
