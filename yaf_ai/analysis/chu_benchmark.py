"""Archive-only Chu benchmark assembly, reporting, and visualization."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import matplotlib
from pydantic import BaseModel, ConfigDict, Field, ValidationError

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from yaf_ai.analysis.chu import (
    QFitResult,
    electrical_size,
    fit_rlc_q,
    mclean_q_min,
    minimum_enclosing_sphere,
)
from yaf_ai.exploration.cross_check import (
    CrossCheckError,
    CrossCheckRunSummary,
    SolverCurve,
)
from yaf_ai.exploration.cross_check_v2 import AnchorRunSummary
from yaf_ai.exploration.patch_final_convergence import NEC2GridRunSummary
from yaf_ai.exploration.patch_mesh_recheck import PatchMeshRecheckSummary
from yaf_ai.exploration.wire import WIRE_BOX_SIZE_M
from yaf_ai.exploration.wire_cross_check import (
    WireCrossCheckRunSummary,
    reconstruct_selected_design,
)

ANALYSIS_ID = "chu-benchmark"
METHOD_DOCUMENT = "docs/chu-benchmark-method.md"
WIRE_RUNS = (
    ("candidate-a", "Confirmed meander A", "day5-wire-v6-final-crosscheck-top1"),
    ("candidate-b", "Confirmed meander B", "day5-wire-v6-final-crosscheck-top2"),
)
ANCHOR_RUN_ID = "day4-dipole-anchor"
PATCH_SOURCE_RUN_ID = "day3-crosscheck-wifi24"
PATCH_OPENEMS_RUN_ID = "day5-patch-final-openems-2x-mesh-recheck"
PATCH_NEC2_RUN_ID = "day5-patch-final-nec2-grid44"
ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class CurveSpecification:
    """One frozen curve and its primary/alternate sphere conventions."""

    design_id: str
    design_label: str
    source_run_id: str
    source_curve_field: str
    source_geometry_hash: str | None
    curve: SolverCurve
    radius_convention: str
    radius_m: float
    alternate_radius_convention: str | None = None
    alternate_radius_m: float | None = None
    total_wire_length_m: float | None = None


class ChuBenchmarkRow(BaseModel):
    """Source-addressed Q/Chu result or an explicit fit failure."""

    model_config = ConfigDict(frozen=True)

    design_id: str
    design_label: str
    solver: str
    source_run_id: str
    source_curve_field: str
    source_geometry_hash: str | None = None
    radius_convention: str
    radius_m: float = Field(gt=0.0)
    alternate_radius_convention: str | None = None
    alternate_radius_m: float | None = Field(default=None, gt=0.0)
    total_wire_length_m: float | None = Field(default=None, gt=0.0)
    fit: QFitResult | None = None
    fit_error: str | None = None
    ka: float | None = Field(default=None, gt=0.0)
    q_min: float | None = Field(default=None, gt=0.0)
    q_over_q_min: float | None = Field(default=None, gt=0.0)
    alternate_ka: float | None = Field(default=None, gt=0.0)
    alternate_q_min: float | None = Field(default=None, gt=0.0)
    alternate_q_over_q_min: float | None = Field(default=None, gt=0.0)
    anchor_improvement_fraction: float | None = None
    flags: tuple[str, ...] = ()
    included_in_main_table: bool = False


class ChuBenchmarkSummary(BaseModel):
    """Complete benchmark with main/appendix membership frozen per row."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    analysis_id: str = ANALYSIS_ID
    method_document: str = METHOD_DOCUMENT
    solver_calls: int = 0
    new_run_count: int = 0
    primary_source_run_ids: tuple[str, ...]
    rows: tuple[ChuBenchmarkRow, ...]
    anchor_reference_ratio: float | None = Field(default=None, gt=0.0)
    main_row_count: int = Field(ge=0)
    appendix_row_count: int = Field(ge=0)


def _load(path: Path, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load Chu source {path}: {error}") from error


def _wire_specifications(repo_root: Path) -> list[CurveSpecification]:
    specifications: list[CurveSpecification] = []
    runs = repo_root / "artifacts" / "runs"
    box_radius = WIRE_BOX_SIZE_M * math.sqrt(2.0) / 2.0
    for design_id, label, run_id in WIRE_RUNS:
        summary = _load(runs / run_id / "summary.json", WireCrossCheckRunSummary)
        if summary.decision.verdict != "CONFIRMED":
            raise CrossCheckError(f"frozen {design_id} source is not CONFIRMED")
        _config, geometry, _seed = reconstruct_selected_design(
            repo_root, summary.selected_design
        )
        sphere = minimum_enclosing_sphere(geometry.vertices)
        total_length = float(geometry.metadata["total_wire_length_m"])
        for field, curve in (("nec2", summary.nec2), ("openems", summary.openems)):
            specifications.append(
                CurveSpecification(
                    design_id=design_id,
                    design_label=label,
                    source_run_id=run_id,
                    source_curve_field=field,
                    source_geometry_hash=summary.selected_design.source_geometry_hash,
                    curve=curve,
                    radius_convention="actual_centerline_minimum_sphere",
                    radius_m=sphere.radius_m,
                    alternate_radius_convention="30mm_box_half_diagonal",
                    alternate_radius_m=box_radius,
                    total_wire_length_m=total_length,
                )
            )
    return specifications


def _anchor_specifications(repo_root: Path) -> list[CurveSpecification]:
    runs = repo_root / "artifacts" / "runs"
    summary = _load(runs / ANCHOR_RUN_ID / "summary.json", AnchorRunSummary)
    length_m = float(summary.geometry["length_m"])
    return [
        CurveSpecification(
            design_id="dipole-anchor",
            design_label="Textbook half-wave dipole",
            source_run_id=ANCHOR_RUN_ID,
            source_curve_field=field,
            source_geometry_hash=None,
            curve=curve,
            radius_convention="dipole_half_length",
            radius_m=length_m / 2.0,
            total_wire_length_m=length_m,
        )
        for field, curve in (("nec2", summary.nec2), ("openems", summary.openems))
    ]


def _rectangle_corners(
    length_m: float, width_m: float, z_m: float
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        (x_sign * length_m / 2.0, y_sign * width_m / 2.0, z_m)
        for x_sign in (-1.0, 1.0)
        for y_sign in (-1.0, 1.0)
    )


def _patch_specifications(repo_root: Path) -> list[CurveSpecification]:
    runs = repo_root / "artifacts" / "runs"
    source = _load(
        runs / PATCH_SOURCE_RUN_ID / "summary.json", CrossCheckRunSummary
    )
    repaired = _load(
        runs / PATCH_OPENEMS_RUN_ID / "summary.json", PatchMeshRecheckSummary
    )
    nec2 = _load(runs / PATCH_NEC2_RUN_ID / "summary.json", NEC2GridRunSummary)
    definition = source.air_variant
    patch_vertices = _rectangle_corners(
        definition.patch_length_m,
        definition.patch_width_m,
        definition.air_gap_m,
    )
    ground_vertices = _rectangle_corners(
        definition.ground_length_m,
        definition.ground_width_m,
        0.0,
    )
    patch_sphere = minimum_enclosing_sphere(patch_vertices)
    combined_sphere = minimum_enclosing_sphere((*patch_vertices, *ground_vertices))
    return [
        CurveSpecification(
            design_id="patch-air-variant",
            design_label="Patch air variant (descriptive)",
            source_run_id=PATCH_OPENEMS_RUN_ID,
            source_curve_field="curve",
            source_geometry_hash=repaired.source_geometry_hash,
            curve=repaired.curve,
            radius_convention="patch_metal_only",
            radius_m=patch_sphere.radius_m,
            alternate_radius_convention="patch_plus_finite_ground",
            alternate_radius_m=combined_sphere.radius_m,
        ),
        CurveSpecification(
            design_id="patch-air-variant",
            design_label="Patch air variant (descriptive)",
            source_run_id=PATCH_NEC2_RUN_ID,
            source_curve_field="point.curve",
            source_geometry_hash=repaired.source_geometry_hash,
            curve=nec2.point.curve,
            radius_convention="patch_metal_only",
            radius_m=patch_sphere.radius_m,
            alternate_radius_convention="patch_plus_finite_ground",
            alternate_radius_m=combined_sphere.radius_m,
        ),
    ]


def _analyze(specification: CurveSpecification) -> ChuBenchmarkRow:
    solver = specification.curve.solver_name.lower()
    try:
        fit = fit_rlc_q(
            specification.curve.frequency_hz,
            specification.curve.s11_db,
        )
    except ValueError as error:
        return ChuBenchmarkRow(
            design_id=specification.design_id,
            design_label=specification.design_label,
            solver=solver,
            source_run_id=specification.source_run_id,
            source_curve_field=specification.source_curve_field,
            source_geometry_hash=specification.source_geometry_hash,
            radius_convention=specification.radius_convention,
            radius_m=specification.radius_m,
            alternate_radius_convention=specification.alternate_radius_convention,
            alternate_radius_m=specification.alternate_radius_m,
            total_wire_length_m=specification.total_wire_length_m,
            fit_error=str(error),
            flags=("fit_ineligible",),
        )
    ka = electrical_size(fit.fitted_resonance_hz, specification.radius_m)
    q_min = mclean_q_min(ka)
    ratio = fit.q_loaded / q_min
    alternate_ka: float | None = None
    alternate_q_min: float | None = None
    alternate_ratio: float | None = None
    if specification.alternate_radius_m is not None:
        alternate_ka = electrical_size(
            fit.fitted_resonance_hz, specification.alternate_radius_m
        )
        alternate_q_min = mclean_q_min(alternate_ka)
        alternate_ratio = fit.q_loaded / alternate_q_min
    flags: list[str] = []
    if fit.confidence == "low_confidence":
        flags.append("low_confidence")
    if ratio < 1.0:
        flags.append("physics_inconsistent_proxy")
    if fit.bandwidth_disagreement_over_30pct:
        flags.append("bandwidth_disagreement_over_30pct")
    included = fit.confidence == "high_confidence" and ratio >= 1.0
    return ChuBenchmarkRow(
        design_id=specification.design_id,
        design_label=specification.design_label,
        solver=solver,
        source_run_id=specification.source_run_id,
        source_curve_field=specification.source_curve_field,
        source_geometry_hash=specification.source_geometry_hash,
        radius_convention=specification.radius_convention,
        radius_m=specification.radius_m,
        alternate_radius_convention=specification.alternate_radius_convention,
        alternate_radius_m=specification.alternate_radius_m,
        total_wire_length_m=specification.total_wire_length_m,
        fit=fit,
        ka=ka,
        q_min=q_min,
        q_over_q_min=ratio,
        alternate_ka=alternate_ka,
        alternate_q_min=alternate_q_min,
        alternate_q_over_q_min=alternate_ratio,
        flags=tuple(flags),
        included_in_main_table=included,
    )


def build_chu_benchmark(repo_root: Path) -> ChuBenchmarkSummary:
    """Compute every frozen primary row from archived bytes only."""

    specifications = [
        *_wire_specifications(repo_root),
        *_anchor_specifications(repo_root),
        *_patch_specifications(repo_root),
    ]
    rows = [_analyze(specification) for specification in specifications]
    anchor_by_solver = {
        row.solver: row.q_over_q_min
        for row in rows
        if row.design_id == "dipole-anchor"
        and row.included_in_main_table
        and row.q_over_q_min is not None
    }
    updated: list[ChuBenchmarkRow] = []
    for row in rows:
        anchor_ratio = anchor_by_solver.get(row.solver)
        if (
            row.design_id in {"candidate-a", "candidate-b"}
            and row.q_over_q_min is not None
            and anchor_ratio is not None
        ):
            updated.append(
                row.model_copy(
                    update={
                        "anchor_improvement_fraction": (
                            anchor_ratio - row.q_over_q_min
                        )
                        / anchor_ratio
                    }
                )
            )
        else:
            updated.append(row)
    anchor_reference = (
        math.prod(anchor_by_solver.values()) ** (1.0 / len(anchor_by_solver))
        if anchor_by_solver
        else None
    )
    main_count = sum(row.included_in_main_table for row in updated)
    source_ids = tuple(
        dict.fromkeys(specification.source_run_id for specification in specifications)
    )
    return ChuBenchmarkSummary(
        primary_source_run_ids=source_ids,
        rows=tuple(updated),
        anchor_reference_ratio=anchor_reference,
        main_row_count=main_count,
        appendix_row_count=len(updated) - main_count,
    )


def _optional(value: float | None, format_specification: str) -> str:
    return "n/a" if value is None else format(value, format_specification)


def _main_table(summary: ChuBenchmarkSummary) -> list[str]:
    lines = [
        "| design | solver | source | a mm | alternate a mm | f0 GHz | ka | Q RLC | Q FBW | R2 | Qmin | Q/Qmin | vs anchor | fit pts | bin % | combined uncertainty | flags |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary.rows:
        if not row.included_in_main_table or row.fit is None:
            continue
        fit = row.fit
        lines.append(
            f"| {row.design_label} | {row.solver} | `{row.source_run_id}` "
            f"(`{row.source_curve_field}`) | {row.radius_m * 1e3:.6f} | "
            f"{_optional(None if row.alternate_radius_m is None else row.alternate_radius_m * 1e3, '.6f')} | "
            f"{fit.fitted_resonance_hz / 1e9:.9f} | {row.ka:.6f} | "
            f"{fit.q_loaded:.6f} | {fit.q_fractional_bandwidth:.6f} | "
            f"{fit.r_squared:.6f} | {row.q_min:.6f} | {row.q_over_q_min:.6f} | "
            f"{_optional(row.anchor_improvement_fraction, '+.2%')} | "
            f"{fit.window.fit_point_count} | {fit.relative_bin_width:.3%} | "
            f"{fit.combined_relative_uncertainty:.2%} | "
            f"{', '.join(row.flags) if row.flags else 'none'} |"
        )
    return lines


def _appendix_table(summary: ChuBenchmarkSummary) -> list[str]:
    lines = [
        "| design | solver | source | status/error | R2 | fit points | Q RLC | Q FBW | flags |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in summary.rows:
        if row.included_in_main_table:
            continue
        fit = row.fit
        lines.append(
            f"| {row.design_label} | {row.solver} | `{row.source_run_id}` | "
            f"{row.fit_error or (fit.confidence if fit is not None else 'unavailable')} | "
            f"{_optional(None if fit is None else fit.r_squared, '.6f')} | "
            f"{_optional(None if fit is None else float(fit.window.fit_point_count), '.0f')} | "
            f"{_optional(None if fit is None else fit.q_loaded, '.6f')} | "
            f"{_optional(None if fit is None else fit.q_fractional_bandwidth, '.6f')} | "
            f"{', '.join(row.flags)} |"
        )
    return lines


def _diagnostic_table(summary: ChuBenchmarkSummary) -> list[str]:
    lines = [
        "| design | solver | method | samples | fit window | crossings GHz | bin MHz | BW MHz | Q SE | QFBW interval | alternate ka / Qmin / ratio |",
        "|---|---|---|---:|---:|---|---:|---:|---:|---|---|",
    ]
    for row in summary.rows:
        fit = row.fit
        if fit is None:
            continue
        window = fit.window
        bandwidth = window.right_crossing_hz - window.left_crossing_hz
        alternate = (
            "n/a"
            if row.alternate_ka is None
            else f"{row.alternate_ka:.6f} / {row.alternate_q_min:.6f} / "
            f"{row.alternate_q_over_q_min:.6f}"
        )
        lines.append(
            f"| {row.design_label} | {row.solver} | `{fit.method}` | "
            f"{fit.sample_count} | {window.start_index}--{window.stop_index} "
            f"({window.fit_point_count}) | {window.left_crossing_hz / 1e9:.9f} / "
            f"{window.right_crossing_hz / 1e9:.9f} | "
            f"{fit.median_bin_width_hz / 1e6:.6f} | {bandwidth / 1e6:.6f} | "
            f"{_optional(fit.q_standard_error, '.6f')} | "
            f"{fit.q_bandwidth_lower:.6f}--{_optional(fit.q_bandwidth_upper, '.6f')} | "
            f"{alternate} |"
        )
    return lines


def _conclusions(summary: ChuBenchmarkSummary) -> list[str]:
    lines: list[str] = []
    anchor_rows = [
        row
        for row in summary.rows
        if row.design_id == "dipole-anchor" and row.included_in_main_table
    ]
    if anchor_rows:
        details = ", ".join(
            f"{row.solver}={row.q_over_q_min:.3f}" for row in anchor_rows
        )
        lines.append(
            f"The textbook dipole anchor ratios are {details}; the plot reference is "
            f"their geometric mean, {summary.anchor_reference_ratio:.3f}."
        )
    for design_id, label, _run_id in WIRE_RUNS:
        rows = [
            row
            for row in summary.rows
            if row.design_id == design_id and row.included_in_main_table
        ]
        if not rows:
            lines.append(
                f"{label} has no high-confidence, physically consistent Q row; no "
                "Chu-distance claim is made."
            )
            continue
        descriptions = ", ".join(
            f"{row.solver}: ka={row.ka:.3f}, Q/Qmin={row.q_over_q_min:.3f}, "
            f"anchor delta={row.anchor_improvement_fraction:+.1%}"
            for row in rows
        )
        lines.append(f"{label}: {descriptions}.")
        if all(
            row.q_over_q_min is not None and row.q_over_q_min >= 1.5
            for row in rows
        ):
            lines.append(
                f"{label} remains well above the preregistered 1.5 proximity threshold. "
                "The finite search budget and score, which did not optimize bandwidth "
                "or Q, are relevant scope limits rather than excuses to relabel it."
            )
    lines.append(
        "Patch rows are descriptive only: assigning the finite ground to the Chu sphere "
        "materially changes ka and the bound, so no strong patch-limit conclusion is made."
    )
    return lines


def _report(summary: ChuBenchmarkSummary) -> str:
    return "\n".join(
        [
            "# Chu--Harrington benchmark over archived designs",
            "",
            "This is a zero-simulation analysis. Every Q value is a magnitude-only "
            "loaded-Q proxy and carries its source run, method, fit window, R2, bandwidth "
            "cross-check, and bin diagnostic. Definitions are frozen in "
            "`docs/chu-benchmark-method.md`.",
            "",
            "## Main table (high-confidence and physically consistent only)",
            "",
            *_main_table(summary),
            "",
            "## Interpretation",
            "",
            *[f"- {line}" for line in _conclusions(summary)],
            "",
            "## Appendix-only rows",
            "",
            *_appendix_table(summary),
            "",
            "## Complete fit and sampling diagnostics",
            "",
            *_diagnostic_table(summary),
            "",
            "## Method limitations",
            "",
            "S11 bandwidth mixes radiator Q, mismatch, and feed behavior. The curves are "
            "near-lossless, which aligns better with the Chu efficiency assumption, but "
            "the result remains a loaded-Q proxy. The patch-plus-ground sphere is "
            "especially interpretation-sensitive. No row below Q/Qmin=1 is promoted; "
            "such a value diagnoses proxy/model/sampling inconsistency.",
            "",
            "![Chu-normalized Q benchmark](chu-plot.png)",
        ]
    )


def _plot(output: Path, summary: ChuBenchmarkSummary) -> None:
    figure, axis = plt.subplots(figsize=(10.8, 6.6))
    colors = {
        "candidate-a": "#d62728",
        "candidate-b": "#ff7f0e",
        "dipole-anchor": "#2ca02c",
        "patch-air-variant": "#7f7f7f",
    }
    markers = {"nec2": "o", "openems": "s"}
    annotation_offsets = {
        ("candidate-a", "nec2"): (20, 30),
        ("candidate-a", "openems"): (20, 55),
        ("candidate-b", "nec2"): (20, -22),
        ("candidate-b", "openems"): (20, 5),
        ("dipole-anchor", "nec2"): (8, -24),
        ("dipole-anchor", "openems"): (8, 10),
        ("patch-air-variant", "nec2"): (8, -22),
        ("patch-air-variant", "openems"): (8, 8),
    }
    annotation_labels = {
        "candidate-a": "A",
        "candidate-b": "B",
        "dipole-anchor": "anchor",
        "patch-air-variant": "patch",
    }
    for design_id in colors:
        coordinates = [
            (row, row.ka, row.q_over_q_min)
            for row in summary.rows
            if row.design_id == design_id and row.included_in_main_table
            and row.ka is not None
            and row.q_over_q_min is not None
        ]
        if len(coordinates) == 2:
            axis.plot(
                [ka for _row, ka, _ratio in coordinates],
                [ratio for _row, _ka, ratio in coordinates],
                color=colors[design_id],
                alpha=0.45,
                linewidth=1.5,
            )
        for row, ka, ratio in coordinates:
            highlighted = design_id in {"candidate-a", "candidate-b"}
            axis.scatter(
                [ka],
                [ratio],
                color=colors[design_id],
                marker=markers.get(row.solver, "o"),
                s=115 if highlighted else 75,
                edgecolor="black" if highlighted else "white",
                linewidth=1.2,
                zorder=4,
                label=f"{row.design_label} / {row.solver}",
            )
            axis.annotate(
                f"{annotation_labels[row.design_id]} / {row.solver}",
                (ka, ratio),
                xytext=annotation_offsets[(row.design_id, row.solver)],
                textcoords="offset points",
                fontsize=8,
                annotation_clip=False,
            )
    axis.axhline(1.0, color="black", linewidth=1.4, label="Chu lower bound")
    if summary.anchor_reference_ratio is not None:
        axis.axhline(
            summary.anchor_reference_ratio,
            color="#2ca02c",
            linestyle="--",
            linewidth=1.4,
            label=f"dipole anchor reference ({summary.anchor_reference_ratio:.3f})",
        )
    axis.set_yscale("log")
    axis.set_xlabel("Electrical size ka at fitted resonance")
    axis.set_ylabel("Loaded-Q proxy / McLean Qmin")
    axis.set_title("Archive-only Chu-normalized Q benchmark")
    axis.grid(alpha=0.25, which="both")
    axis.legend(fontsize=8, loc="best")
    figure.tight_layout()
    figure.savefig(output / "chu-plot.png", dpi=180)
    plt.close(figure)


def write_chu_benchmark(repo_root: Path) -> ChuBenchmarkSummary:
    """Write the three requested LF-only benchmark artifacts and no run evidence."""

    summary = build_chu_benchmark(repo_root)
    output = repo_root / "artifacts" / "analysis" / ANALYSIS_ID
    output.mkdir(parents=True, exist_ok=True)
    summary_temporary = output / "summary.json.tmp"
    summary_temporary.write_bytes(
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
    os.replace(summary_temporary, output / "summary.json")
    report_temporary = output / "report.md.tmp"
    report_temporary.write_bytes((_report(summary) + "\n").encode("utf-8"))
    os.replace(report_temporary, output / "report.md")
    _plot(output, summary)
    return summary
