"""Frozen candidate selection and instrument-convergence rules for Day 5-1b."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yaf_ai.exploration.batch import load_batch_state
from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.logger import AuditStepRecord, RunSummary
from yaf_ai.exploration.wire_cross_check import (
    SelectedWireDesign,
    select_top_gp_designs,
)

FINAL_SOURCE_BATCH_ID = "day5-wire-v6r2"
TARGET_BAND_HZ = (2.40e9, 2.50e9)
EXPECTED_EVALUATION_ROWS = 4001
OPENEMS_SELF_CONVERGENCE_THRESHOLD = 0.03
MAX_OPENEMS_REFINEMENT_SECONDS = 30.0 * 60.0
NEC2_FINAL_DENSITY = 160

CANDIDATE_A_ADDRESS = (
    "day5-wire-v6r2-wifi24-gp-s202",
    255,
    "e3bcb25f8878021a281d458e2d94821c8a7bf79da8116b2618d4623a5dc66ca8",
)
CANDIDATE_B_ADDRESS = (
    "day5-wire-v6r2-wifi24-gp-s202",
    253,
    "e580526705b059e0064bc3b4d0d432927bcb6ec67f788607ca2086ded2391ebe",
)

InstrumentAction = Literal[
    "use_current",
    "run_8x",
    "run_3x",
    "infeasible_at_current_compute",
]
FinalAttributionVerdict = Literal[
    "instrument_boundary",
    "genuine_anomaly",
    "infeasible_at_current_compute",
]


class FrozenFinalCandidate(BaseModel):
    """One source-addressed candidate frozen before any final simulation."""

    model_config = ConfigDict(frozen=True)

    label: Literal["A", "B"]
    selection_rule: str
    design: SelectedWireDesign
    target_band_min_s11_db: float
    target_band_resonance_frequency_hz: float = Field(gt=0.0)
    target_band_resonance_index: int = Field(ge=0)
    target_band_realized_gain_dbi: float


class OpenEMSInstrumentDecision(BaseModel):
    """Next action after one adjacent openEMS mesh comparison."""

    model_config = ConfigDict(frozen=True)

    adjacent_relative_shift: float = Field(ge=0.0)
    threshold: float = OPENEMS_SELF_CONVERGENCE_THRESHOLD
    converged: bool
    action: InstrumentAction
    selected_refinement: float | None = Field(default=None, gt=0.0)


class FinalInstrumentAttribution(BaseModel):
    """Mechanical attribution after the final feasible solver settings."""

    model_config = ConfigDict(frozen=True)

    openems_adjacent_shift: float = Field(ge=0.0)
    openems_converged: bool
    nec2_adjacent_shift: float = Field(ge=0.0)
    nec2_converged: bool
    gaps_monotonically_narrowing: bool
    final_resonance_gap: float = Field(ge=0.0)
    verdict: FinalAttributionVerdict


def _load_evaluation_records(log_paths: Sequence[Path]) -> tuple[AuditStepRecord, ...]:
    records: list[AuditStepRecord] = []
    try:
        for path in log_paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                raw = json.loads(line)
                if raw.get("event_type") == "evaluation":
                    records.append(AuditStepRecord.model_validate(raw))
    except (OSError, ValidationError, json.JSONDecodeError) as error:
        raise CrossCheckError(f"cannot load candidate evidence logs: {error}") from error
    return tuple(records)


def select_deepest_target_band_record(
    log_paths: Sequence[Path],
    *,
    target_band_hz: tuple[float, float] = TARGET_BAND_HZ,
) -> AuditStepRecord:
    """Select deepest logged target-band S11, then score/run/step deterministically."""

    eligible: list[AuditStepRecord] = []
    for record in _load_evaluation_records(log_paths):
        frequency = float(record.metrics["resonance_frequency_hz"])
        depth = float(record.metrics["min_s11_db"])
        if not math.isfinite(frequency) or not math.isfinite(depth):
            raise CrossCheckError("candidate evidence contains non-finite RF metrics")
        if target_band_hz[0] <= frequency <= target_band_hz[1]:
            eligible.append(record)
    if not eligible:
        raise CrossCheckError("no evaluation has a target-band S11 minimum")
    return min(
        eligible,
        key=lambda item: (
            float(item.metrics["min_s11_db"]),
            -item.score,
            item.run_id,
            item.step_index,
        ),
    )


def _load_run_summary(artifacts_root: Path, run_id: str) -> RunSummary:
    try:
        return RunSummary.model_validate_json(
            (artifacts_root / run_id / "summary.json").read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load archived run {run_id}: {error}") from error


def _record_at_address(
    records: Sequence[AuditStepRecord], address: tuple[str, int, str]
) -> AuditStepRecord:
    run_id, step_index, geometry_hash = address
    record = next(
        (
            item
            for item in records
            if item.run_id == run_id and item.step_index == step_index
        ),
        None,
    )
    if record is None or record.geometry_hash != geometry_hash:
        raise CrossCheckError(f"frozen candidate address is missing or changed: {address}")
    return record


def load_frozen_final_candidates(
    repo_root: Path,
    *,
    batch_id: str = FINAL_SOURCE_BATCH_ID,
) -> tuple[FrozenFinalCandidate, FrozenFinalCandidate]:
    """Recompute both frozen selections and reject any evidence drift."""

    if batch_id != FINAL_SOURCE_BATCH_ID:
        raise CrossCheckError(f"final candidates are frozen to {FINAL_SOURCE_BATCH_ID}")
    state = load_batch_state(
        repo_root / "runs" / f"batch_{batch_id}" / "state.json"
    )
    if any(record.status != "completed" for record in state.runs):
        raise CrossCheckError("source batch is not entirely completed")
    artifacts_root = repo_root / "artifacts" / "runs"
    log_paths = tuple(
        artifacts_root / record.run_id / "log.jsonl" for record in state.runs
    )
    records = _load_evaluation_records(log_paths)
    if len(records) != EXPECTED_EVALUATION_ROWS:
        raise CrossCheckError(
            f"expected {EXPECTED_EVALUATION_ROWS} evaluations, found {len(records)}"
        )
    candidate_a_design = select_top_gp_designs(repo_root, batch_id=batch_id, count=1)[0]
    candidate_a_record = _record_at_address(records, CANDIDATE_A_ADDRESS)
    if (
        candidate_a_design.source_run_id,
        candidate_a_design.source_step_index,
        candidate_a_design.source_geometry_hash,
    ) != CANDIDATE_A_ADDRESS:
        raise CrossCheckError("score-ranked candidate A no longer matches preregistration")
    candidate_b_record = select_deepest_target_band_record(log_paths)
    if (
        candidate_b_record.run_id,
        candidate_b_record.step_index,
        candidate_b_record.geometry_hash,
    ) != CANDIDATE_B_ADDRESS:
        raise CrossCheckError("deepest-S11 candidate B no longer matches preregistration")
    classic = _load_run_summary(
        artifacts_root, f"{batch_id}-wifi24-classic-s0"
    )
    source = _load_run_summary(artifacts_root, candidate_b_record.run_id)
    if not classic.top_designs or classic.top_designs[0].score == 0.0:
        raise CrossCheckError("classic source is absent or has zero score")
    classic_score = classic.top_designs[0].score
    candidate_b_design = SelectedWireDesign(
        rank=2,
        source_run_id=source.run_id,
        source_config_hash=source.config_hash,
        source_geometry_hash=candidate_b_record.geometry_hash,
        source_score=candidate_b_record.score,
        source_step_index=candidate_b_record.step_index,
        target_band_resonance_valid=False,
        classic_source_run_id=classic.run_id,
        classic_score=classic_score,
        oracle_improvement_fraction=candidate_b_record.score / classic_score - 1.0,
        proposal_parameters=candidate_b_record.proposal_parameters,
        proposer=candidate_b_record.proposer,
    )
    if candidate_a_design.source_geometry_hash == candidate_b_design.source_geometry_hash:
        raise CrossCheckError("frozen candidates A and B must be distinct geometries")
    return (
        FrozenFinalCandidate(
            label="A",
            selection_rule=(
                "preregistered v6r2 target-band-valid candidates first, then score "
                "descending, run_id ascending, step ascending"
            ),
            design=candidate_a_design,
            target_band_min_s11_db=float(candidate_a_record.metrics["min_s11_db"]),
            target_band_resonance_frequency_hz=float(
                candidate_a_record.metrics["resonance_frequency_hz"]
            ),
            target_band_resonance_index=int(
                candidate_a_record.metrics["resonance_index"]
            ),
            target_band_realized_gain_dbi=float(
                candidate_a_record.metrics["realized_gain_dbi"]
            ),
        ),
        FrozenFinalCandidate(
            label="B",
            selection_rule=(
                "minimum target-band min_s11_db across all 4001 archived "
                "evaluations; ties by score descending, run_id ascending, step ascending"
            ),
            design=candidate_b_design,
            target_band_min_s11_db=float(candidate_b_record.metrics["min_s11_db"]),
            target_band_resonance_frequency_hz=float(
                candidate_b_record.metrics["resonance_frequency_hz"]
            ),
            target_band_resonance_index=int(
                candidate_b_record.metrics["resonance_index"]
            ),
            target_band_realized_gain_dbi=float(
                candidate_b_record.metrics["realized_gain_dbi"]
            ),
        ),
    )


def relative_frequency_shift(reference_hz: float, comparison_hz: float) -> float:
    """Return an absolute frequency shift relative to the finer comparison."""

    if reference_hz <= 0.0 or comparison_hz <= 0.0:
        raise ValueError("resonance frequencies must be positive")
    return abs(reference_hz - comparison_hz) / comparison_hz


def decide_openems_instrument(
    refinements: Sequence[float],
    frequencies_hz: Sequence[float],
    elapsed_seconds: Sequence[float],
) -> OpenEMSInstrumentDecision:
    """Apply the frozen 3%, 30-minute, 4x/8x/3x execution decision tree."""

    if not (len(refinements) == len(frequencies_hz) == len(elapsed_seconds)):
        raise ValueError("openEMS convergence series must align")
    if len(refinements) < 2:
        raise ValueError("openEMS convergence requires two adjacent levels")
    if any(value <= 0.0 for value in refinements) or any(
        value < 0.0 for value in elapsed_seconds
    ):
        raise ValueError("openEMS refinements/times are outside their valid range")
    shift = relative_frequency_shift(frequencies_hz[-2], frequencies_hz[-1])
    converged = shift <= OPENEMS_SELF_CONVERGENCE_THRESHOLD
    if converged:
        action: InstrumentAction = "use_current"
        selected = refinements[-1]
    elif refinements[-1] == 4.0 and elapsed_seconds[-1] > MAX_OPENEMS_REFINEMENT_SECONDS:
        action = "run_3x"
        selected = None
    elif refinements[-1] == 4.0:
        action = "run_8x"
        selected = None
    else:
        action = "infeasible_at_current_compute"
        selected = None
    return OpenEMSInstrumentDecision(
        adjacent_relative_shift=shift,
        converged=converged,
        action=action,
        selected_refinement=selected,
    )


def classify_final_instrument_attribution(
    *,
    openems_adjacent_frequencies_hz: tuple[float, float],
    nec2_adjacent_frequencies_hz: tuple[float, float],
    nec2_to_final_openems_gaps: Sequence[float],
) -> FinalInstrumentAttribution:
    """Classify the final feasible sequences without changing v2.1 thresholds."""

    if len(nec2_to_final_openems_gaps) < 2 or any(
        gap < 0.0 for gap in nec2_to_final_openems_gaps
    ):
        raise ValueError("attribution needs at least two non-negative NEC2 gaps")
    open_shift = relative_frequency_shift(*openems_adjacent_frequencies_hz)
    nec_shift = relative_frequency_shift(*nec2_adjacent_frequencies_hz)
    open_converged = open_shift <= OPENEMS_SELF_CONVERGENCE_THRESHOLD
    nec_converged = nec_shift <= OPENEMS_SELF_CONVERGENCE_THRESHOLD
    monotonic = all(
        earlier >= later
        for earlier, later in zip(
            nec2_to_final_openems_gaps,
            nec2_to_final_openems_gaps[1:],
            strict=False,
        )
    )
    final_gap = nec2_to_final_openems_gaps[-1]
    if open_converged and nec_converged and monotonic and final_gap <= 0.05:
        verdict: FinalAttributionVerdict = "instrument_boundary"
    elif open_converged and nec_converged and final_gap > 0.05:
        verdict = "genuine_anomaly"
    else:
        verdict = "infeasible_at_current_compute"
    return FinalInstrumentAttribution(
        openems_adjacent_shift=open_shift,
        openems_converged=open_converged,
        nec2_adjacent_shift=nec_shift,
        nec2_converged=nec_converged,
        gaps_monotonically_narrowing=monotonic,
        final_resonance_gap=final_gap,
        verdict=verdict,
    )
