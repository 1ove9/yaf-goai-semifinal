"""Run the preregistered solver-free paired-feasibility Stage A."""

from __future__ import annotations

import argparse
from pathlib import Path

from yaf_ai.analysis.paired_feasible_stage_a import run_stage_a
from yaf_ai.exploration.paired_feasible_gates import validate_stage_a_provenance

DEFAULT_OUTPUT = Path(
    "artifacts/analysis/semifinal-feasibility-stratified-v2-stage-a"
)


def main() -> int:
    """Write the complete Stage-A endpoint and print its classification."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    arguments = parser.parse_args()
    provenance = validate_stage_a_provenance(arguments.repo_root)
    summary = run_stage_a(arguments.repo_root.resolve() / DEFAULT_OUTPUT, provenance)
    print(
        f"Stage A completed: {summary.cell_count} cells, "
        f"endpoint={summary.representation_endpoint}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
