"""Freeze or verify the three semifinal NEC2 candidates from archived logs."""

from __future__ import annotations

import argparse
from pathlib import Path

from yaf_ai.exploration.paired_candidate_report import (
    write_or_verify_candidate_report,
)
from yaf_ai.exploration.paired_candidates import write_or_verify_candidate_freeze


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    document = write_or_verify_candidate_freeze(
        repo_root,
        verify=args.verify,
    )
    write_or_verify_candidate_report(
        repo_root,
        document,
        verify=args.verify,
    )
    print(f"mode={'verify' if args.verify else 'write'}")
    for candidate in document.candidates:
        print(
            f"category={candidate.category} run_id={candidate.source_run_id} "
            f"step={candidate.source_step_index} pair_hash={candidate.pair_hash} "
            f"base_score={candidate.base_score:.15f} "
            f"valid={candidate.valid_pair_search} "
            f"positive_eligible={candidate.positive_eligible} "
            f"pool={candidate.source_record_count} "
            f"valid_pool={candidate.valid_record_count}"
        )
    effect = document.effect_assessment
    print(f"matrix_budget_complete={document.matrix_budget_complete}")
    print(
        "effect_reduction_percent="
        f"{100.0 * effect.relative_reduction_fraction:.6f} "
        f"effect_gate_passed={effect.passed}"
    )
    print(f"openems_cross_check_authorized={document.openems_cross_check_authorized}")
    print(f"verdict_ceiling={document.verdict_ceiling}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
