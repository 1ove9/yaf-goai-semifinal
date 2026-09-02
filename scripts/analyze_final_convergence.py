"""Render the archived Day 5-1b instrument convergence series."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "yaf-matplotlib")
)

import matplotlib

from yaf_ai.exploration.final_wire_convergence import FinalConvergenceSeries

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


def _report(series: FinalConvergenceSeries) -> str:
    lines = [
        "# Day 5-1b instrument convergence",
        "",
        (
            "Candidate A is frozen to `day5-wire-v6r2-wifi24-gp-s202` step "
            "255. The protocol-v2.1 scientific thresholds and 1.5--3.5 GHz / "
            "201-point sweep are unchanged."
        ),
        "",
        "## Complete sequence",
        "",
        "| Solver | Setting | f_res | S11 | wall/recorded time | Solver time | Source |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in series.openems_curves:
        source = (
            series.prior_run_id
            if item.setting_value in {1.0, 2.0}
            else next(
                run_id
                for run_id in series.new_run_ids
                if (
                    "stage1" in run_id and item.setting_value == 4.0
                )
                or (
                    "stage2" in run_id and item.setting_value in {3.0, 8.0}
                )
            )
        )
        lines.append(
            f"| openEMS | {item.setting_value:g}x | "
            f"{item.curve.resonance_frequency_hz / 1e9:.3f} GHz | "
            f"{item.curve.resonance_s11_db:.6f} dB | "
            f"{item.wall_time_seconds:.6f} s | "
            f"{item.curve.simulation_time_seconds:.6f} s | `{source}` |"
        )
    final_openems = next(
        item
        for item in series.openems_curves
        if item.setting_value == series.selected_openems_refinement
    )
    for item in series.nec2_curves:
        source = (
            series.prior_run_id
            if item.setting_value in {20.0, 40.0, 80.0}
            else series.new_run_ids[0]
        )
        gap = abs(
            item.curve.resonance_frequency_hz
            - final_openems.curve.resonance_frequency_hz
        ) / final_openems.curve.resonance_frequency_hz
        lines.append(
            f"| NEC2 | lambda/{item.setting_value:g} | "
            f"{item.curve.resonance_frequency_hz / 1e9:.3f} GHz | "
            f"{item.curve.resonance_s11_db:.6f} dB | "
            f"{item.wall_time_seconds:.6f} s | "
            f"{item.curve.simulation_time_seconds:.6f} s | `{source}`; "
            f"gap to final openEMS {gap:.6%} |"
        )
    openems_shifts = [
        abs(
            previous.curve.resonance_frequency_hz
            - current.curve.resonance_frequency_hz
        )
        / current.curve.resonance_frequency_hz
        for previous, current in zip(
            series.openems_curves, series.openems_curves[1:], strict=False
        )
    ]
    nec2_shift = series.attribution.nec2_adjacent_shift
    lines.extend(
        [
            "",
            "## Frozen decisions",
            "",
            (
                "openEMS adjacent shifts were "
                + ", ".join(f"{value:.6%}" for value in openems_shifts)
                + ". The 2x->4x shift missed 3%, mechanically triggering the "
                "single feasible 8x run; 4x->8x passed."
            ),
            (
                f"NEC2 lambda/80->lambda/160 shifted {nec2_shift:.6%}, "
                "passing the unchanged 3% instrument-convergence check."
            ),
            (
                "Against final openEMS 8x, the NEC2 lambda/20, /40, /80, /160 "
                "gaps are 0.787402%, 0.787402%, 0.787402%, and 1.181102%. "
                "The last increase violates the preregistered monotonic-narrowing "
                "condition even though both instruments individually converge and "
                "the final gap is below 5%."
            ),
            (
                f"Attribution verdict: `{series.attribution.verdict}`. This label "
                "is applied before the final candidate verdicts and is not changed "
                "based on their outcome."
            ),
            "",
            "![Instrument convergence](instrument-convergence.png)",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    output = repo_root / "artifacts" / "analysis" / "day5-wire-v6-final"
    series = FinalConvergenceSeries.model_validate_json(
        (output / "convergence-series.json").read_text(encoding="utf-8")
    )
    (output / "convergence.md").write_bytes(_report(series).encode("utf-8"))
    figure, axes = plt.subplots(1, 2, figsize=(11.0, 4.5))
    axes[0].plot(
        [item.setting_value for item in series.openems_curves],
        [item.curve.resonance_frequency_hz / 1e9 for item in series.openems_curves],
        marker="o",
        color="#ef6c00",
    )
    axes[0].set_xlabel("openEMS mesh refinement")
    axes[0].set_ylabel("f_res (GHz)")
    axes[0].set_xticks([item.setting_value for item in series.openems_curves])
    axes[0].grid(alpha=0.25)
    axes[1].plot(
        [item.setting_value for item in series.nec2_curves],
        [item.curve.resonance_frequency_hz / 1e9 for item in series.nec2_curves],
        marker="o",
        color="#1565c0",
        label="NEC2",
    )
    final_openems = next(
        item
        for item in series.openems_curves
        if item.setting_value == series.selected_openems_refinement
    )
    axes[1].axhline(
        final_openems.curve.resonance_frequency_hz / 1e9,
        color="#ef6c00",
        label=f"openEMS {series.selected_openems_refinement:g}x",
    )
    axes[1].set_xlabel("NEC2 segments per wavelength")
    axes[1].set_ylabel("f_res (GHz)")
    axes[1].set_xticks([item.setting_value for item in series.nec2_curves])
    axes[1].grid(alpha=0.25)
    axes[1].legend()
    figure.tight_layout()
    figure.savefig(output / "instrument-convergence.png", dpi=180)
    plt.close(figure)
    print(json.dumps(series.attribution.model_dump(mode="json"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
