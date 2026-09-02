"""Write the final scoped Day 5-2 patch resolution from archived evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.patch_final_report import write_patch_final_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        summary = write_patch_final_report(Path(__file__).resolve().parents[1])
    except CrossCheckError as error:
        print(f"analyze_patch_final: {error}", file=sys.stderr)
        return 1
    decision = summary.cross_check.decision
    print(
        f"verdict={decision.verdict} day2={summary.day2_resolved_verdict} "
        f"gap={decision.resonance_relative_difference} "
        f"pearson={decision.curve_pearson_correlation}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
