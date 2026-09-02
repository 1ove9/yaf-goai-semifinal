"""Run and analyze the preregistered A-span support causal probe."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from yaf_ai.analysis.a_span_probe import analyze_probe_events, write_probe_outputs
from yaf_ai.exploration.a_span_probe import (
    LOG_FILENAME,
    RUN_DIRECTORY,
    RUN_ID,
    TERMINAL_FAILURE_FILENAME,
    ASpanProbeError,
    run_a_span_probe,
)

ANALYSIS_DIRECTORY = Path("artifacts") / "analysis" / RUN_ID


def _full_commit(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise argparse.ArgumentTypeError(
            "commit must be a full 40-character lowercase hexadecimal ID"
        )
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--implementation-commit",
        required=True,
        type=_full_commit,
        help="Full Git commit containing the frozen probe implementation.",
    )
    parser.add_argument(
        "--execution-commit",
        type=_full_commit,
        help="Optional full execution HEAD; defaults to the implementation commit.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (defaults to this script''s parent repository).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the fixed 32-call run and independently rebuild its analysis."""

    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    analysis_directory = repo_root / ANALYSIS_DIRECTORY
    try:
        if analysis_directory.exists():
            raise FileExistsError(
                f"analysis output already exists: {analysis_directory}"
            )
        summary = asyncio.run(
            run_a_span_probe(
                repo_root,
                implementation_commit=args.implementation_commit,
                execution_commit=args.execution_commit,
            )
        )
        analysis = analyze_probe_events(
            repo_root / RUN_DIRECTORY / LOG_FILENAME,
            summary,
        )
        write_probe_outputs(analysis, analysis_directory)
    except (
        ASpanProbeError,
        FileExistsError,
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        marker = repo_root / RUN_DIRECTORY / TERMINAL_FAILURE_FILENAME
        marker_note = f"; terminal_marker={marker}" if marker.is_file() else ""
        print(f"A-span support probe failed: {error}{marker_note}", file=sys.stderr)
        return 1
    print(
        f"{summary.run_id}: status={summary.status}; "
        f"calls={summary.solver_calls_completed}; endpoint={analysis.scientific_endpoint}"
    )
    print(f"run={repo_root / RUN_DIRECTORY}")
    print(f"analysis={analysis_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
