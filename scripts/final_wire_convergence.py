"""Run, archive, and report the frozen Day 5-1b instrument sequence."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.final_wire_convergence import (
    FinalConvergenceStageSummary,
    run_final_convergence,
)


def _archive(repo_root: Path, run_id: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "archive_run.py"),
            run_id,
            "--role",
            "other",
            "--note",
            "batch=day5-wire-v6-final candidate=A instrument-convergence",
        ],
        cwd=repo_root,
        check=True,
    )


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    def on_stage(stage: FinalConvergenceStageSummary) -> None:
        _archive(repo_root, stage.run_id)
        print(f"archived={stage.run_id}")
        for timed in stage.curves:
            print(
                f"{timed.solver} {timed.setting_name}={timed.setting_value:g} "
                f"f_res={timed.curve.resonance_frequency_hz:.0f} "
                f"s11={timed.curve.resonance_s11_db:.6f} "
                f"wall_seconds={timed.wall_time_seconds:.6f} "
                f"solver_seconds={timed.curve.simulation_time_seconds:.6f}"
            )
        print(
            "openems_decision="
            f"{stage.openems_decision.model_dump_json() if stage.openems_decision else None}"
        )
    series, _stages = await run_final_convergence(repo_root, on_stage=on_stage)
    output = (
        repo_root
        / "artifacts"
        / "analysis"
        / "day5-wire-v6-final"
        / "convergence-series.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        (
            json.dumps(
                series.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    print(f"selected_openems_refinement={series.selected_openems_refinement}")
    print(f"selected_nec2_density={series.selected_nec2_density}")
    print(f"attribution={series.attribution.model_dump_json()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
