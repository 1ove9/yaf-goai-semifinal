"""Run the preregistered Day 4 anchor or wire-grid convergence study."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.cross_check_v2 import (
    AnchorRunSummary,
    ConvergenceRunSummary,
    run_anchor,
    run_convergence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    anchor = subparsers.add_parser("anchor")
    anchor.add_argument("--run-id", default="day4-dipole-anchor")
    convergence = subparsers.add_parser("convergence")
    convergence.add_argument("--run-id", default="day4-attribution-wifi24")
    convergence.add_argument("--source-run-id", default="day3-crosscheck-wifi24")
    convergence.add_argument("--anchor-run-id", default="day4-dipole-anchor")
    return parser


def _archive(repo_root: Path, run_id: str, note: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "archive_run.py"),
            run_id,
            "--role",
            "other",
            "--note",
            note,
        ],
        cwd=repo_root,
        check=True,
    )


def _write_text_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((text.rstrip() + "\n").encode("utf-8"))


def _render_attribution(repo_root: Path, summary: ConvergenceRunSummary) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(repo_root / "tmp" / "matplotlib"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output = repo_root / "artifacts" / "analysis" / "day4-attribution"
    output.mkdir(parents=True, exist_ok=True)
    x = [point.grid_intervals for point in summary.points]
    y = [point.nec2_resonance_frequency_hz / 1e9 for point in summary.points]
    reference = summary.source_openems_curve.resonance_frequency_hz / 1e9
    figure, axis = plt.subplots(figsize=(7.2, 4.5))
    axis.plot(x, y, marker="o", label="NEC2 wire grid")
    axis.axhline(reference, color="black", linestyle="--", label="archived openEMS")
    axis.set_xlabel("grid_intervals")
    axis.set_ylabel("sampled resonance (GHz)")
    axis.set_xticks(x)
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output / "convergence.png", dpi=160)
    plt.close(figure)

    rows = []
    for point in summary.points:
        rows.append(
            f"| {point.grid_intervals} | "
            f"{point.nec2_resonance_frequency_hz / 1e9:.6f} | "
            f"{point.resonance_relative_gap:.3%} | "
            f"{point.spacing_to_radius_ratio:.3f} | {point.segment_count} | "
            f"{point.solve_time_seconds:.3f} |"
        )
    estimate = summary.attribution.estimated_grid_intervals_for_five_percent
    estimate_text = "not estimable from a narrowing power law" if estimate is None else str(estimate)
    report = "\n".join(
        [
            "# Day 4 patch divergence attribution",
            "",
            "The openEMS reference curve is reused byte-for-byte from archived run "
            f"`{summary.source_run_id}`; it was not rerun.",
            "",
            "| grid intervals | NEC2 f_res (GHz) | gap | min spacing/radius | segments | solve s |",
            "|---:|---:|---:|---:|---:|---:|",
            *rows,
            "",
            "## Frozen-rule attribution",
            "",
            f"Verdict: `{summary.attribution.verdict}`. Gap(24)/gap(6) is "
            f"{summary.attribution.gap_24_to_gap_6_ratio:.6f}; monotonic narrowing is "
            f"{summary.attribution.monotonic_narrowing}. The preregistered log-log trend "
            f"estimate for reaching 5% is grid_intervals={estimate_text}.",
            "",
            "## Day 3 reclassification appendix",
            "",
            "- `day3-crosscheck-wifi24`: reclassified by the v2 convergence verdict above; "
            "the original v1 DIVERGENT record remains unchanged.",
            "- `day3-crosscheck-wifi58`: `inconclusive_needs_spec_specific_grid_study`; "
            "wifi24 convergence is not silently generalized across frequency and geometry.",
            "- `day3-crosscheck-n78`: `inconclusive_needs_spec_specific_grid_study`; "
            "the archived v1 DIVERGENT result remains valid as a v1 observation.",
            "",
            "S11-depth differences remain descriptive only under protocol v2.",
        ]
    )
    _write_text_lf(output / "report.md", report)
    (output / "summary.json").write_bytes(
        (
            json.dumps(
                summary.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
    )


def _print_anchor(summary: AnchorRunSummary) -> None:
    print(f"run_id={summary.run_id}")
    print(
        f"openems_f_res_hz={summary.openems.resonance_frequency_hz:.6f} "
        f"openems_s11_db={summary.openems.resonance_s11_db:.6f}"
    )
    print(
        f"nec2_f_res_hz={summary.nec2.resonance_frequency_hz:.6f} "
        f"nec2_s11_db={summary.nec2.resonance_s11_db:.6f}"
    )
    print(
        f"delta_f={summary.decision.resonance_relative_difference:.6%} "
        f"pearson={summary.decision.curve_pearson_correlation:.9f}"
    )
    print(f"verdict={summary.decision.verdict}")


async def _main() -> int:
    args = _parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        if args.command == "anchor":
            anchor_summary = await run_anchor(repo_root, args.run_id)
            _archive(
                repo_root,
                anchor_summary.run_id,
                "anchor protocol=day4-native-curves-v2",
            )
            _print_anchor(anchor_summary)
            return 0 if anchor_summary.decision.verdict == "CONFIRMED" else 1
        convergence_summary = await asyncio.to_thread(
            run_convergence,
            repo_root,
            source_run_id=args.source_run_id,
            run_id=args.run_id,
            anchor_run_id=args.anchor_run_id,
        )
        _render_attribution(repo_root, convergence_summary)
        _archive(
            repo_root,
            convergence_summary.run_id,
            f"convergence source={convergence_summary.source_run_id} "
            f"attribution={convergence_summary.attribution.verdict}",
        )
        for point in convergence_summary.points:
            print(
                f"grid={point.grid_intervals} "
                f"nec2_f_res_hz={point.nec2_resonance_frequency_hz:.6f} "
                f"gap={point.resonance_relative_gap:.6%} "
                f"spacing_radius={point.spacing_to_radius_ratio:.6f} "
                f"segments={point.segment_count} "
                f"seconds={point.solve_time_seconds:.3f}"
            )
        print(f"attribution={convergence_summary.attribution.verdict}")
        print(
            "estimated_grid_intervals_for_five_percent="
            f"{convergence_summary.attribution.estimated_grid_intervals_for_five_percent}"
        )
        return 0
    except (CrossCheckError, subprocess.CalledProcessError) as error:
        print(f"cross_check_v2: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
