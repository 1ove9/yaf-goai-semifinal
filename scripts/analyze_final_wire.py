"""Build the final Day 5-1b report from archived evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.final_wire_analysis import write_final_wire_analysis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        summary = write_final_wire_analysis(Path(__file__).resolve().parents[1])
    except CrossCheckError as error:
        print(f"analyze_final_wire: {error}", file=sys.stderr)
        return 1
    print(f"environment_verdict={summary.environment_verdict}")
    for result in summary.candidates:
        decision = result.cross_check.decision
        print(
            f"candidate={result.candidate.label} verdict={decision.verdict} "
            f"gap={decision.resonance_relative_difference} "
            f"pearson={decision.curve_pearson_correlation}"
        )
    if summary.confirmation_statement is not None:
        print(summary.confirmation_statement)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
