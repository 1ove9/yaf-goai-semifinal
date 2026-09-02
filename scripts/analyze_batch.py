"""Analyze one exploration batch into traceable JSON, Markdown, and PNG artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from yaf_ai.exploration.analysis import analyze_batch
from yaf_ai.exploration.batch import load_batch_config
from yaf_ai.exploration.cross_check import analyze_cross_checks
from yaf_ai.exploration.pixel_analysis import analyze_pixel_batch
from yaf_ai.exploration.wire_analysis import (
    analyze_day5_wire_batch,
    analyze_wire_batch,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True)
    return parser.parse_args()


def main(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    cross_check_state = (
        repo_root / "runs" / f"crosscheck_{args.batch_id}" / "state.json"
    )
    if cross_check_state.is_file():
        cross_summary = analyze_cross_checks(args.batch_id, repo_root=repo_root)
        print(f"batch_id={cross_summary.batch_id}")
        print(f"rows={len(cross_summary.decisions)} failed=0")
        print(f"output=artifacts/analysis/{args.batch_id}")
        return 0
    config_path = repo_root / "runs" / f"batch_{args.batch_id}" / "config.json"
    document = load_batch_config(config_path)
    if document.config.experiment_kind == "wire":
        if args.batch_id.startswith("day5-wire-v6"):
            day5_summary = analyze_day5_wire_batch(
                args.batch_id, repo_root=repo_root
            )
            print(f"batch_id={day5_summary.final_batch.batch_id}")
            print(f"rows={len(day5_summary.final_batch.rows)}")
            print(f"verdict={day5_summary.discovery_verdict}")
            return 0
        wire_summary = analyze_wire_batch(args.batch_id, repo_root=repo_root)
        print(f"batch_id={wire_summary.batch_id}")
        print(f"rows={len(wire_summary.rows)}")
        print(f"verdict={wire_summary.verdict}")
        return 0
    if document.config.experiment_kind == "pixel":
        pixel_summary = analyze_pixel_batch(args.batch_id, repo_root=repo_root)
        print(f"batch_id={pixel_summary.batch_id}")
        print(f"rows={len(pixel_summary.rows)}")
        print(
            f"best_pixel_score={pixel_summary.questions.best_pixel_score:.6f} "
            f"source={pixel_summary.questions.best_pixel_source_run_id}"
        )
        return 0
    else:
        batch_summary = analyze_batch(args.batch_id, repo_root=repo_root)
    print(f"batch_id={batch_summary.batch_id}")
    print(f"rows={len(batch_summary.rows)}")
    for decision in batch_summary.discovery_decisions:
        print(
            f"{decision.spec}: verdict={decision.verdict} "
            f"cross_solver={decision.cross_solver_status}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(parse_args()))
