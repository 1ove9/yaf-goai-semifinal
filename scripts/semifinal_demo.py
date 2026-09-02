"""Build or verify the solver-free GOAI semifinal evidence package."""

from __future__ import annotations

import argparse
from pathlib import Path

from yaf_ai.analysis.semifinal_submission import (
    SemifinalSubmissionError,
    verify_submission_package,
    write_submission_package,
)


def main() -> int:
    """Run the reviewer's no-solver semifinal evidence walkthrough."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Regenerate deterministic outputs.")
    mode.add_argument("--verify", action="store_true", help="Verify committed outputs (default).")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    try:
        summary = (
            write_submission_package(repo_root)
            if args.write
            else verify_submission_package(repo_root)
        )
    except SemifinalSubmissionError as error:
        print(f"semifinal_demo: FAIL: {error}")
        return 1

    candidate = summary.candidate
    effect = summary.effect_gate
    print("solver_calls=0")
    print(
        f"archive_verify={summary.archive.verified_ok_count}/"
        f"{summary.archive.manifest_entry_count} OK"
    )
    print(
        f"candidate={candidate.label} run_id={candidate.source_run_id} "
        f"step={candidate.source_step_index} pair_hash={candidate.pair_hash}"
    )
    print(
        "state_A="
        f"{candidate.state_a.selected_frequency_ghz:.4f}GHz/"
        f"{candidate.state_a.selected_s11_db:.3f}dB "
        "state_B="
        f"{candidate.state_b.selected_frequency_ghz:.4f}GHz/"
        f"{candidate.state_b.selected_s11_db:.3f}dB"
    )
    print(
        f"effect_reduction={100.0 * effect.observed_reduction_fraction:.6f}% "
        f"required={100.0 * effect.required_reduction_fraction:.1f}% "
        f"passed={str(effect.passed).lower()}"
    )
    print(
        f"openems_candidate_authorized="
        f"{str(summary.instrument.candidate_openems_authorized).lower()} "
        f"rod_gate={summary.instrument.rod_r2_result_status}"
    )
    print(f"final_verdict={summary.final_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
