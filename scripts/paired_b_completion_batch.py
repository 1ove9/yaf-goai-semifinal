"""Run or exactly resume the preregistered B-parent completion matrix."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from yaf_ai.exploration.paired_b_completion_batch import (
    MATRIX_FAILURE_PATH,
    BCompletionMatrixError,
    run_b_completion_matrix,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--implementation-commit",
        required=True,
        help="Full Git commit containing the byte-frozen matrix implementation.",
    )
    parser.add_argument(
        "--certificate-evidence-commit",
        required=True,
        help="Full Git commit containing the passed support certificate.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute only the matrix; archiving and analysis are later explicit steps."""

    args = _parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        results = asyncio.run(
            run_b_completion_matrix(
                repo_root,
                implementation_commit=args.implementation_commit,
                certificate_evidence_commit=args.certificate_evidence_commit,
            )
        )
    except BCompletionMatrixError as error:
        marker = error.failure
        print(
            f"terminal_marker={MATRIX_FAILURE_PATH.as_posix()} "
            + json.dumps(
                marker.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ),
            file=sys.stderr,
        )
        return 1
    for result in results:
        summary = result.summary
        print(f"{summary.run_id}: status={summary.status}; steps={summary.steps_completed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
