"""Generate the evidence-gated exact-support Stage-B appendix and report."""

from __future__ import annotations

import argparse
from pathlib import Path

from yaf_ai.analysis.paired_feasible_stage_b import (
    OUTPUT_DIRECTORY,
    load_stage_b_evidence,
    write_stage_b_outputs,
)
from yaf_ai.exploration.paired_feasible_batch import load_stage_b_inputs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage-a-evidence-commit",
        required=True,
        help="Full Git commit containing the validated exact-v2 Stage-A evidence.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root; output remains fixed by the preregistration.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    root = args.repo_root.resolve()
    inputs = load_stage_b_inputs(root, args.stage_a_evidence_commit)
    appendix = load_stage_b_evidence(root, inputs)
    output = root / OUTPUT_DIRECTORY
    write_stage_b_outputs(output, appendix)
    print(
        f"Stage B {appendix.study_status}: rows={len(appendix.rows)}; "
        f"records={sum(row.accepted_count for row in appendix.rows)}; "
        f"appendix={output / 'appendix.json'}; report={output / 'report.md'}"
    )
    return 0 if appendix.study_status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
