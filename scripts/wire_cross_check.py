"""Cross-check the top archived Day 4 wire designs with native openEMS geometry."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.wire_cross_check import (
    run_wire_cross_check,
    select_top_gp_designs,
)


def _archived(repo_root: Path) -> set[str]:
    path = repo_root / "artifacts" / "runs" / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["run_id"]) for item in payload}


def _archive(
    repo_root: Path,
    run_id: str,
    source_run_id: str,
    batch_id: str,
) -> None:
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "archive_run.py"),
            run_id,
            "--role",
            "other",
            "--note",
            f"batch={batch_id} native-crosscheck source={source_run_id}",
        ],
        cwd=repo_root,
        check=True,
    )


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", default="day4-wire")
    parser.add_argument("--top", type=int, default=2, choices=(1, 2))
    parser.add_argument("--nec-density", type=int, default=20)
    parser.add_argument("--openems-refinement", type=float, default=1.0)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        selected = select_top_gp_designs(
            repo_root, batch_id=args.batch_id, count=args.top
        )
        archived = _archived(repo_root)
        for design in selected:
            run_id = f"{args.batch_id}-crosscheck-top{design.rank}"
            if run_id in archived:
                print(f"SKIP {run_id} already archived")
                continue
            summary = await run_wire_cross_check(
                repo_root,
                design,
                batch_id=args.batch_id,
                nec2_segments_per_wavelength=args.nec_density,
                openems_mesh_refinement=args.openems_refinement,
            )
            _archive(repo_root, summary.run_id, design.source_run_id, args.batch_id)
            print(
                f"run_id={summary.run_id} source={design.source_run_id} "
                f"improvement={design.oracle_improvement_fraction:.6%}"
            )
            print(
                f"openems_f_res_hz={summary.openems.resonance_frequency_hz:.6f} "
                f"nec2_f_res_hz={summary.nec2.resonance_frequency_hz:.6f} "
                f"delta_f={summary.decision.resonance_relative_difference} "
                f"pearson={summary.decision.curve_pearson_correlation} "
                f"verdict={summary.decision.verdict}"
            )
        return 0
    except (CrossCheckError, subprocess.CalledProcessError) as error:
        print(f"wire_cross_check: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
