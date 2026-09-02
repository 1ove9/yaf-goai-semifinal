"""Solver-free representation ablation for the stratified paired study."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, Self

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from yaf_ai.exploration.paired_agents import (
    FEED_GAP_BOUNDS,
    SPAN_BOUNDS,
    STATE_A_LENGTH_BOUNDS,
    STATE_B_LENGTH_BOUNDS,
    TERMINAL_BOUNDS,
)
from yaf_ai.exploration.paired_feasible_coordinates import (
    MAPPING_VERSION,
    decode_feasible_coordinates,
    exact_nominal_failure_reason,
)
from yaf_ai.exploration.paired_feasible_gates import StageAProvenance
from yaf_ai.exploration.paired_meander import (
    HardwareSpec,
    PairedProposal,
    StateControl,
    audit_trajectory,
)

STUDY_ID = "semifinal-paired-feasibility-stratified-exact-v2"
SPEC_REVISION = "2.0-exact-nominal-support"
STREAM_FORMAT_VERSION = "canonical-json-float-hex-lf-v1"
LEGACY_REPRESENTATION = "legacy-exact-fixed-turn-v2"
CONDITIONAL_REPRESENTATION = "conditional-exact-feasible-turn-v2"
TURNS = (3, 4, 5, 6)
SEEDS = (101, 202, 303, 404, 505)
RAW_DRAWS_PER_CELL = 10_000
_TRUSTED_FROZEN_BUILD_CONTEXT = object()

Status = Literal["valid", "trajectory_infeasible"]
RepresentationEndpoint = Literal[
    "coverage_improved_all_turns",
    "coverage_improved_some_turns",
    "coverage_improvement_not_observed",
]


class StageAInvariantError(RuntimeError):
    """Raised when the conditional representation violates its contract."""


class RepresentationCounts(BaseModel):
    """Exact status counts and digest for one representation in one cell."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    representation: str
    status_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    valid: int = Field(ge=0)
    trajectory_infeasible: int = Field(ge=0)
    feasible_rate: float = Field(ge=0.0, le=1.0)


class StageACell(BaseModel):
    """One paired-representation cell with one shared raw stream."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn: int
    seed: int
    raw_draws: int
    raw_stream_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    legacy: RepresentationCounts
    conditional: RepresentationCounts
    coverage_pass: bool


class TurnCoverage(BaseModel):
    """Five-seed coverage decision for one frozen turn stratum."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn: int
    passing_seeds: tuple[int, ...]
    pass_count: int = Field(ge=0, le=5)
    reproducibly_improved: bool


class BoundaryWitness(BaseModel):
    """One fixed conditional-map boundary witness, recorded without a solver."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    turn: int
    z: tuple[str, ...]
    proposal: PairedProposal
    trajectory_valid: Literal[True] = True

class StageASummary(BaseModel):
    """The sole legal complete Stage-A endpoint document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    study_id: str = STUDY_ID
    spec_revision: str = SPEC_REVISION
    mapping_version: str = MAPPING_VERSION
    status: Literal["completed"] = "completed"
    stream_format_version: str = STREAM_FORMAT_VERSION
    representations: tuple[str, str] = (
        LEGACY_REPRESENTATION,
        CONDITIONAL_REPRESENTATION,
    )
    turns: tuple[int, ...] = TURNS
    seeds: tuple[int, ...] = SEEDS
    raw_draws_per_cell: int = Field(default=RAW_DRAWS_PER_CELL, gt=0)
    cell_count: Literal[20] = 20
    cells: tuple[StageACell, ...]
    boundary_witnesses: tuple[BoundaryWitness, ...]
    turn_coverage: tuple[TurnCoverage, ...]
    reproducibly_improved_turn_count: int = Field(ge=0, le=4)
    representation_endpoint: RepresentationEndpoint
    solver_calls: Literal[0] = 0
    provenance: StageAProvenance | None = None

    @model_validator(mode="after")
    def validate_recomputed_endpoint(self, info: ValidationInfo) -> Self:
        """Reject any summary whose cells or aggregate endpoint do not recompute."""

        if (
            self.study_id != STUDY_ID
            or self.spec_revision != SPEC_REVISION
            or self.mapping_version != MAPPING_VERSION
            or self.representations
            != (LEGACY_REPRESENTATION, CONDITIONAL_REPRESENTATION)
            or self.turns != TURNS
            or self.seeds != SEEDS
        ):
            raise ValueError("Stage-A frozen identity changed")
        expected_order = tuple((turn, seed) for turn in TURNS for seed in SEEDS)
        if tuple((cell.turn, cell.seed) for cell in self.cells) != expected_order:
            raise ValueError("Stage-A cells are not the exact ordered matrix")
        for cell in self.cells:
            if cell.raw_draws != self.raw_draws_per_cell:
                raise ValueError("Stage-A cell draw count changed")
            for counts, representation in (
                (cell.legacy, LEGACY_REPRESENTATION),
                (cell.conditional, CONDITIONAL_REPRESENTATION),
            ):
                if (
                    counts.representation != representation
                    or counts.valid + counts.trajectory_infeasible != cell.raw_draws
                    or counts.feasible_rate != counts.valid / cell.raw_draws
                ):
                    raise ValueError("Stage-A representation counts do not recompute")
            expected_coverage = (
                cell.conditional.feasible_rate == 1.0
                and cell.conditional.feasible_rate - cell.legacy.feasible_rate >= 0.20
            )
            if (
                cell.conditional.valid != cell.raw_draws
                or cell.conditional.trajectory_infeasible != 0
                or cell.coverage_pass != expected_coverage
            ):
                raise ValueError("Stage-A conditional or coverage invariant changed")
            if info.context is not _TRUSTED_FROZEN_BUILD_CONTEXT:
                expected_cell = _run_cell(
                    cell.turn,
                    cell.seed,
                    raw_draws=cell.raw_draws,
                    conditional_decoder=_frozen_conditional_decode,
                )
                if cell != expected_cell:
                    raise ValueError("Stage-A cell stream evidence does not recompute")

        expected_witness_order = tuple(
            (turn, label) for turn in TURNS for label, _values in BOUNDARY_VECTORS
        )
        if tuple(
            (witness.turn, witness.label) for witness in self.boundary_witnesses
        ) != expected_witness_order:
            raise ValueError("Stage-A boundary witnesses are incomplete or reordered")
        for witness, (_label, values) in zip(
            self.boundary_witnesses,
            BOUNDARY_VECTORS * len(TURNS),
            strict=True,
        ):
            expected_z = tuple(float(value).hex() for value in values)
            expected_proposal = _frozen_conditional_decode(witness.turn, values)
            if (
                witness.z != expected_z
                or witness.proposal != expected_proposal
                or witness.proposal.hardware.turn_count != witness.turn
                or witness.proposal.proposer != CONDITIONAL_REPRESENTATION
                or _exact_nominal_rejection(witness.proposal) is not None
                or not audit_trajectory(witness.proposal).valid
            ):
                raise ValueError("Stage-A boundary witness is not v2 legal")

        if tuple(item.turn for item in self.turn_coverage) != TURNS:
            raise ValueError("Stage-A turn coverage is incomplete or reordered")
        recomputed: list[bool] = []
        for coverage in self.turn_coverage:
            passing = tuple(
                cell.seed
                for cell in self.cells
                if cell.turn == coverage.turn and cell.coverage_pass
            )
            reproducible = len(passing) >= 4
            if (
                coverage.passing_seeds != passing
                or coverage.pass_count != len(passing)
                or coverage.reproducibly_improved != reproducible
            ):
                raise ValueError("Stage-A turn coverage does not recompute")
            recomputed.append(reproducible)
        improved = sum(recomputed)
        endpoint: RepresentationEndpoint
        if improved == 4:
            endpoint = "coverage_improved_all_turns"
        elif improved:
            endpoint = "coverage_improved_some_turns"
        else:
            endpoint = "coverage_improvement_not_observed"
        if (
            self.reproducibly_improved_turn_count != improved
            or self.representation_endpoint != endpoint
        ):
            raise ValueError("Stage-A aggregate endpoint does not recompute")
        return self


def _canonical_json_line(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def _legacy_decode(turn: int, values: Sequence[float]) -> PairedProposal:
    if len(values) != 6:
        raise ValueError("Stage-A raw vector must have six coordinates")
    return PairedProposal(
        hardware=HardwareSpec(
            turn_count=turn,
            feed_gap_ratio_ppm=_legacy_half_up_map(float(values[0]), FEED_GAP_BOUNDS),
            terminal_ratio_ppm=_legacy_half_up_map(float(values[1]), TERMINAL_BOUNDS),
        ),
        state_a=StateControl(
            state="A",
            total_wire_length_um=_legacy_half_up_map(
                float(values[2]), STATE_A_LENGTH_BOUNDS
            ),
            span_ratio_ppm=_legacy_half_up_map(float(values[3]), SPAN_BOUNDS),
        ),
        state_b=StateControl(
            state="B",
            total_wire_length_um=_legacy_half_up_map(
                float(values[4]), STATE_B_LENGTH_BOUNDS
            ),
            span_ratio_ppm=_legacy_half_up_map(float(values[5]), SPAN_BOUNDS),
        ),
        proposer=LEGACY_REPRESENTATION,
    )


def _legacy_half_up_map(value: float, bounds: tuple[int, int]) -> int:
    lower, upper = bounds
    mapped = lower + value * (upper - lower)
    return min(upper, max(lower, math.floor(mapped + 0.5)))

def _exact_nominal_rejection(proposal: PairedProposal) -> str | None:
    hardware = proposal.hardware
    return exact_nominal_failure_reason(
        turn_count=hardware.turn_count,
        feed_gap_ratio_ppm=hardware.feed_gap_ratio_ppm,
        terminal_ratio_ppm=hardware.terminal_ratio_ppm,
        state_a_length_um=proposal.state_a.total_wire_length_um,
        state_a_span_ppm=proposal.state_a.span_ratio_ppm,
        state_b_length_um=proposal.state_b.total_wire_length_um,
        state_b_span_ppm=proposal.state_b.span_ratio_ppm,
    )

def _status(
    draw_index: int,
    representation: str,
    proposal: PairedProposal,
) -> tuple[Status, str | None, bytes]:
    exact_rejection = _exact_nominal_rejection(proposal)
    if exact_rejection is not None:
        valid = False
        reason: str | None = exact_rejection
    else:
        audit = audit_trajectory(proposal)
        valid = audit.valid
        reason = None if audit.valid else audit.rejection_reason
    status: Status = "valid" if valid else "trajectory_infeasible"
    if status != "valid" and not reason:
        raise StageAInvariantError("trajectory rejection has no reason")
    line = _canonical_json_line(
        {
            "draw_index": draw_index,
            "rejection_reason": reason,
            "representation": representation,
            "status": status,
        }
    )
    return status, reason, line


Decoder = Callable[[int, Sequence[float]], PairedProposal]


def _frozen_conditional_decode(
    turn: int,
    values: Sequence[float],
) -> PairedProposal:
    return decode_feasible_coordinates(
        values,
        turn_count=turn,
        proposer=CONDITIONAL_REPRESENTATION,
    )


def _run_cell(
    turn: int,
    seed: int,
    *,
    raw_draws: int,
    conditional_decoder: Decoder,
) -> StageACell:
    generator = np.random.Generator(
        np.random.PCG64(np.random.SeedSequence([seed, 0, turn, 1]))
    )
    vectors: NDArray[np.float64] = generator.random((raw_draws, 6))
    raw_hasher = hashlib.sha256()
    legacy_hasher = hashlib.sha256()
    conditional_hasher = hashlib.sha256()
    legacy_valid = 0
    conditional_valid = 0

    for draw_index, vector in enumerate(vectors):
        values = vector.tolist()
        raw_hasher.update(
            _canonical_json_line(
                {
                    "draw_index": draw_index,
                    "z": [float(value).hex() for value in values],
                }
            )
        )

        legacy_status, _reason, legacy_line = _status(
            draw_index,
            LEGACY_REPRESENTATION,
            _legacy_decode(turn, values),
        )
        legacy_hasher.update(legacy_line)
        legacy_valid += int(legacy_status == "valid")

        proposal = conditional_decoder(turn, values)
        conditional_status, reason, conditional_line = _status(
            draw_index,
            CONDITIONAL_REPRESENTATION,
            proposal,
        )
        if conditional_status != "valid":
            raise StageAInvariantError(
                f"conditional invariant failed at turn={turn}, seed={seed}, "
                f"draw={draw_index}: {reason}"
            )
        conditional_hasher.update(conditional_line)
        conditional_valid += 1

    legacy_rate = legacy_valid / raw_draws
    conditional_rate = conditional_valid / raw_draws
    return StageACell(
        turn=turn,
        seed=seed,
        raw_draws=raw_draws,
        raw_stream_sha256=raw_hasher.hexdigest(),
        legacy=RepresentationCounts(
            representation=LEGACY_REPRESENTATION,
            status_sha256=legacy_hasher.hexdigest(),
            valid=legacy_valid,
            trajectory_infeasible=raw_draws - legacy_valid,
            feasible_rate=legacy_rate,
        ),
        conditional=RepresentationCounts(
            representation=CONDITIONAL_REPRESENTATION,
            status_sha256=conditional_hasher.hexdigest(),
            valid=conditional_valid,
            trajectory_infeasible=raw_draws - conditional_valid,
            feasible_rate=conditional_rate,
        ),
        coverage_pass=(
            conditional_rate == 1.0
            and conditional_rate - legacy_rate >= 0.20
        ),
    )


BOUNDARY_VECTORS: tuple[tuple[str, tuple[float, ...]], ...] = (
    ("all-zero", (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
    ("all-one", (1.0, 1.0, 1.0, 1.0, 1.0, 1.0)),
    ("interior-half", (0.5, 0.5, 0.5, 0.5, 0.5, 0.5)),
    (
        "terminal-zero-upper-edge",
        (0.5, math.nextafter(1.0 / 16.0, 0.0), 0.5, 0.5, 0.5, 0.5),
    ),
    ("terminal-positive-lower-edge", (0.5, 1.0 / 16.0, 0.5, 0.5, 0.5, 0.5)),
    ("state-b-narrow-domain", (1.0, 1.0, 0.5, 1.0, 0.0, 0.76)),
)


def _boundary_witnesses(decoder: Decoder) -> tuple[BoundaryWitness, ...]:
    witnesses: list[BoundaryWitness] = []
    for turn in TURNS:
        for label, values in BOUNDARY_VECTORS:
            proposal = decoder(turn, values)
            audit = audit_trajectory(proposal)
            if not audit.valid:
                raise StageAInvariantError(
                    f"conditional boundary invariant failed at turn={turn}, "
                    f"label={label}: {audit.rejection_reason}"
                )
            witnesses.append(
                BoundaryWitness(
                    label=label,
                    turn=turn,
                    z=tuple(value.hex() for value in values),
                    proposal=proposal,
                )
            )
    return tuple(witnesses)

def build_stage_a_summary(
    *,
    raw_draws: int = RAW_DRAWS_PER_CELL,
) -> StageASummary:
    """Build the complete solver-free endpoint without writing partial output."""

    if raw_draws <= 0:
        raise ValueError("raw_draws must be positive")
    decoder = _frozen_conditional_decode
    witnesses = _boundary_witnesses(decoder)
    cells = tuple(
        _run_cell(
            turn,
            seed,
            raw_draws=raw_draws,
            conditional_decoder=decoder,
        )
        for turn in TURNS
        for seed in SEEDS
    )
    coverages = tuple(
        TurnCoverage(
            turn=turn,
            passing_seeds=tuple(
                cell.seed for cell in cells if cell.turn == turn and cell.coverage_pass
            ),
            pass_count=sum(
                cell.turn == turn and cell.coverage_pass for cell in cells
            ),
            reproducibly_improved=(
                sum(cell.turn == turn and cell.coverage_pass for cell in cells) >= 4
            ),
        )
        for turn in TURNS
    )
    improved = sum(item.reproducibly_improved for item in coverages)
    endpoint: RepresentationEndpoint
    if improved == 4:
        endpoint = "coverage_improved_all_turns"
    elif improved:
        endpoint = "coverage_improved_some_turns"
    else:
        endpoint = "coverage_improvement_not_observed"
    return StageASummary.model_validate(
        {
            "raw_draws_per_cell": raw_draws,
            "cells": cells,
            "boundary_witnesses": witnesses,
            "turn_coverage": coverages,
            "reproducibly_improved_turn_count": improved,
            "representation_endpoint": endpoint,
        },
        context=_TRUSTED_FROZEN_BUILD_CONTEXT,
    )


def render_report(summary: StageASummary) -> str:
    """Render a deterministic human-readable Stage-A report."""

    lines = [
        "# Solver-free representation ablation",
        "",
        f"- Study: `{summary.study_id}`",
        f"- Status: `{summary.status}`",
        f"- Endpoint: `{summary.representation_endpoint}`",
        f"- Solver calls: `{summary.solver_calls}`",
        "",
        "| Turn | Seed | Legacy valid | Conditional valid | Coverage pass |",
        "|---:|---:|---:|---:|:---:|",
    ]
    for cell in summary.cells:
        lines.append(
            f"| {cell.turn} | {cell.seed} | {cell.legacy.valid}/{cell.raw_draws} "
            f"| {cell.conditional.valid}/{cell.raw_draws} "
            f"| {'yes' if cell.coverage_pass else 'no'} |"
        )
    lines.extend(("", "## Turn-level endpoint", ""))
    for coverage in summary.turn_coverage:
        seeds = ", ".join(str(seed) for seed in coverage.passing_seeds) or "none"
        lines.append(
            f"- Turn {coverage.turn}: {coverage.pass_count}/5 passing seeds "
            f"({seeds}); reproducibly improved = "
            f"`{str(coverage.reproducibly_improved).lower()}`."
        )
    lines.extend(
        (
            "",
            "This is a solver-free representation endpoint. It contains no antenna score "
            "and does not select or remove a turn from Stage B.",
            "",
        )
    )
    return "\n".join(lines)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _require_persistable(summary: StageASummary) -> None:
    if summary.provenance is None or not summary.provenance.clean_code_tree:
        raise StageAInvariantError("validated Stage-A provenance is required")
    if (
        summary.study_id != summary.provenance.study_id
        or summary.spec_revision != summary.provenance.spec_revision
        or summary.mapping_version != summary.provenance.mapping_version
    ):
        raise StageAInvariantError("Stage-A identity differs from validated provenance")
    expected_order = tuple((turn, seed) for turn in TURNS for seed in SEEDS)
    actual_order = tuple((cell.turn, cell.seed) for cell in summary.cells)
    if summary.raw_draws_per_cell != RAW_DRAWS_PER_CELL or actual_order != expected_order:
        raise StageAInvariantError("only the exact preregistered Stage-A matrix may persist")
    for cell in summary.cells:
        if (
            cell.raw_draws != RAW_DRAWS_PER_CELL
            or cell.legacy.valid + cell.legacy.trajectory_infeasible != RAW_DRAWS_PER_CELL
            or cell.conditional.valid != RAW_DRAWS_PER_CELL
            or cell.conditional.trajectory_infeasible != 0
        ):
            raise StageAInvariantError("Stage-A cell is not the sole legal completed terminal")

def write_stage_a_outputs(output_dir: Path, summary: StageASummary) -> None:
    """Atomically write LF-only summary and report after a complete run."""

    _require_persistable(summary)
    summary_bytes = (
        json.dumps(
            summary.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    report_bytes = render_report(summary).encode("utf-8")
    if b"\r" in summary_bytes or b"\r" in report_bytes:
        raise StageAInvariantError("Stage-A output must be LF-only")
    _atomic_write(output_dir / "summary.json", summary_bytes)
    _atomic_write(output_dir / "report.md", report_bytes)


def run_stage_a(
    output_dir: Path,
    provenance: StageAProvenance,
) -> StageASummary:
    """Execute the exact preregistered 20-cell, 10,000-draw Stage A."""

    summary = build_stage_a_summary().model_copy(update={"provenance": provenance})
    write_stage_a_outputs(output_dir, summary)
    return summary
