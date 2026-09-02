"""Strict deterministic analysis for the frozen A-span support probe."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.exploration.paired_meander import SearchCurve, score_state_curve

STUDY_ID = "semifinal-a-span-support-causal-probe-v1"
RUN_ID = STUDY_ID
DOSES_PPM = (0, 50_000, 100_000)
PARENTS = ("p01", "p02")
SEEDS = (101, 202, 303, 404, 505)
PLANNED_CALLS = 32
L_REQUIRED = 0.19394054289730642
PLOT_FILENAME = "dose-response.png"
_ENDPOINTS = {
    "span_support_sufficient_in_frozen_counterfactuals",
    "span_support_contributor_not_sufficient",
    "span_support_association_not_supported",
    "span_support_inconclusive",
}
ParentId = Literal["p01", "p02"]
ScientificEndpoint = Literal[
    "span_support_sufficient_in_frozen_counterfactuals",
    "span_support_contributor_not_sufficient",
    "span_support_association_not_supported",
    "span_support_inconclusive",
]
_B_SHA = {
    "p01": "399b85ea2b8d63faa60743e8534450949bbc9846908c8cdbe995a81794c42181",
    "p02": "f4be9ba23a08b745a1e5f48a0a7bf075eb656a43df0a625a046933886b23b949",
}
_B_LOSS = {"p01": 0.025679054646815754, "p02": 0.019354919667848212}
_WIDTHS = {
    0: (29.945750, 30.486440),
    50_000: (31.445750, 31.986440),
    100_000: (32.945750, 33.486440),
}


def _sha(value: str | None) -> bool:
    return value is not None and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _same(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-13, abs_tol=1e-15)


def _runtime() -> ModuleType:
    return importlib.import_module("yaf_ai.exploration.a_span_probe")


def _payload(value: object) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("probe payload keys must be strings")
        return {cast(str, key): item for key, item in value.items()}
    raise TypeError("probe evidence must be a Pydantic model or mapping")


def _pick(data: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in data:
            return data[name]
    raise KeyError(f"probe evidence lacks {names!r}")


def _curve_sha(curve: SearchCurve) -> str:
    data = json.dumps(
        curve.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class FrozenProbeUnit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(ge=0, le=9)
    parent_id: ParentId
    seed: int
    source_run_id: str
    source_step_index: int
    source_proposal_index: int
    source_pair_hash: str
    source_length_um: int
    source_span_ppm: int
    source_loss: float
    source_curve_sha256: str
    frozen_b_loss: float

    @model_validator(mode="after")
    def frozen_identity(self) -> Self:
        expected = ("p01" if self.index < 5 else "p02", SEEDS[self.index % 5])
        if (self.parent_id, self.seed) != expected:
            raise ValueError("source-unit order changed")
        if not _sha(self.source_pair_hash) or not _sha(self.source_curve_sha256):
            raise ValueError("source hashes are invalid")
        if not _same(self.frozen_b_loss, _B_LOSS[self.parent_id]):
            raise ValueError("source B loss changed")
        return self


_SOURCE_ROWS: tuple[tuple[ParentId, int, str, int, str, int, int, float], ...] = (
    ("p01", 101, "semifinal-paired-b-completion-p01-es-s101", 286, "fb98e3539cb47e05d15fd42c16ddbb8a9f6ecf55c51f4b3ea942bbd295835bf3", 71_001, 981_858, 0.24551036781205307),
    ("p01", 202, "semifinal-paired-b-completion-p01-es-s202", 24, "cc678757386ca5cbe25c34b818a151e4556b40a12e4a7ff1f7a4ff02638b40b9", 70_973, 992_531, 0.23755180106137028),
    ("p01", 303, "semifinal-paired-b-completion-p01-es-s303", 265, "59a7e7df8fe7b8c3e6a07333e84ef12099886c5971a9815891ef63e1d041f259", 70_775, 999_881, 0.23010531242953516),
    ("p01", 404, "semifinal-paired-b-completion-p01-es-s404", 209, "d9aa2b8bad62c71b6da2cc988c131de1415333ddbcf2085d53f65c004d551e96", 70_816, 999_368, 0.23092841432431088),
    ("p01", 505, "semifinal-paired-b-completion-p01-es-s505", 109, "6ace3129ef9005e3d3d2ea804e4799f41145a7bda2719f470dcf9f7fe5b1009b", 70_856, 999_628, 0.23120053766167860),
    ("p02", 101, "semifinal-paired-b-completion-p02-es-s101", 164, "754e66368ce1de867994b541a21aa5cbb07d6ef65b13536c2a00cd345d64a8c8", 70_860, 999_705, 0.23269669380050187),
    ("p02", 202, "semifinal-paired-b-completion-p02-es-s202", 283, "efa222ede3e10524564cf438b57c4a45e2def304836db7476aefde8d2f03aece", 70_825, 999_581, 0.23237516833229716),
    ("p02", 303, "semifinal-paired-b-completion-p02-es-s303", 204, "5f68b76c738956d271dc194022591a1a157a552416d9fde997a6f3273f72e239", 70_788, 999_102, 0.23229511875494777),
    ("p02", 404, "semifinal-paired-b-completion-p02-es-s404", 268, "9666760505ce32f0aa3ce7138f449931895ece5ac252bd089d5a9c2e47131733", 70_824, 999_816, 0.23219805776354677),
    ("p02", 505, "semifinal-paired-b-completion-p02-es-s505", 293, "0216ff4394e6ec4f42e26189aa50b86985c681cde410b4b4b499276a289995fc", 70_833, 999_921, 0.23223486715570588),
)


class _BEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_type: Literal["a_span_probe_b_replay"]
    call_index: int
    solver_mode: Literal["subprocess"]
    parent_id: ParentId
    canonical_curve_sha256: str
    state_b_curve: SearchCurve
    timestamp: str | None = None


class _AEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_type: Literal["a_span_probe_a_evaluation"]
    call_index: int
    solver_mode: Literal["subprocess"]
    parent_id: ParentId
    seed: int
    source_pair_hash: str
    source_run_id: str
    source_step_index: int
    source_proposal_index: int
    dose_ppm: int
    effective_a_span_ratio_ppm: int
    state_a_curve: SearchCurve
    canonical_curve_sha256: str
    frozen_b_loss: float
    trajectory_valid: bool
    actual_full_width_mm: float
    minimum_clearance_mm: float
    state_a_selected_index: int
    state_a_selected_frequency_hz: float
    state_a_selected_s11_db: float
    state_a_loss: float
    state_a_valid: bool
    hybrid_loss: float
    diagnostic_pair_valid: bool
    diagnostic_reference_crossing: bool
    source_box_size_um: int
    counterfactual_only: bool
    outside_original_span_support: bool
    physical_40mm_trajectory_valid: bool
    eligible_for_original_candidate_pool: bool
    eligible_for_original_h1_h2: bool
    eligible_for_original_agent_comparison: bool
    timestamp: str | None = None


class _RunSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    study_id: str
    run_id: str
    status: Literal["completed"]
    seed: int
    config_hash: str
    steps_completed: int
    solver_calls_completed: int
    solver_mode_counts: dict[str, int]
    b_replay_calls: int
    a_solver_calls: int
    endpoint: ScientificEndpoint
    high_dose_improvements: int
    monotonic_responses: int
    p01_crossings: int
    p02_crossings: int
    verdict_ceiling: Literal["insufficient_evidence"]
    openems_calls: int
    log_sha256: str


class ProbeBReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    parent_id: ParentId
    call_index: int
    canonical_curve_sha256: str
    selected_index: int
    selected_frequency_hz: float
    selected_s11_db: float
    reflected_power_loss: float
    valid_search: bool

    @model_validator(mode="after")
    def valid_replay(self) -> Self:
        if self.call_index != PARENTS.index(self.parent_id):
            raise ValueError("B replay order changed")
        if self.canonical_curve_sha256 != _B_SHA[self.parent_id]:
            raise ValueError("B replay hash changed")
        if not self.valid_search or not _same(self.reflected_power_loss, _B_LOSS[self.parent_id]):
            raise ValueError("B replay metrics changed")
        return self


class ProbeDoseResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_unit_index: int
    parent_id: ParentId
    seed: int
    source_run_id: str
    source_step_index: int
    source_proposal_index: int
    source_pair_hash: str
    source_span_ppm: int
    effective_span_ppm: int
    dose_ppm: int
    call_index: int
    source_curve_sha256: str
    curve_sha256: str
    selected_index: int
    selected_frequency_hz: float
    selected_s11_db: float
    state_a_loss: float
    source_a_loss: float
    delta_a_loss: float
    state_a_valid: bool
    frozen_b_loss: float
    hybrid_loss: float
    trajectory_valid: bool
    actual_full_width_mm: float
    minimum_clearance_mm: float
    diagnostic_pair_valid: bool
    diagnostic_reference_crossing: bool
    counterfactual_only: bool
    outside_original_span_support: bool
    physical_40mm_trajectory_valid: bool
    eligible_for_original_candidate_pool: bool
    eligible_for_original_h1_h2: bool
    eligible_for_original_agent_comparison: bool

    @model_validator(mode="after")
    def valid_dose(self) -> Self:
        if self.dose_ppm not in DOSES_PPM or self.effective_span_ppm != self.source_span_ppm + self.dose_ppm:
            raise ValueError("additive dose changed")
        if not all(_sha(value) for value in (self.source_pair_hash, self.source_curve_sha256, self.curve_sha256)):
            raise ValueError("dose-row hash is invalid")
        if not _same(self.delta_a_loss, self.state_a_loss - self.source_a_loss):
            raise ValueError("loss delta does not recompute")
        if not _same(self.hybrid_loss, max(self.state_a_loss, self.frozen_b_loss)):
            raise ValueError("hybrid loss does not recompute")
        valid = self.trajectory_valid and self.state_a_valid
        if self.diagnostic_pair_valid != valid:
            raise ValueError("pair validity does not recompute")
        if self.diagnostic_reference_crossing != (valid and self.hybrid_loss <= L_REQUIRED):
            raise ValueError("reference crossing does not recompute")
        if not self.trajectory_valid or not self.physical_40mm_trajectory_valid:
            raise ValueError("trajectory gate was not passed")
        if self.minimum_clearance_mm < 0.2 - 1e-12:
            raise ValueError("clearance fell below 0.2 mm")
        low, high = _WIDTHS[self.dose_ppm]
        if not low - 1e-9 <= self.actual_full_width_mm <= high + 1e-9:
            raise ValueError("width lies outside the frozen dose range")
        positive = self.dose_ppm > 0
        if self.counterfactual_only != positive or self.outside_original_span_support != positive:
            raise ValueError("counterfactual flags disagree with dose")
        if positive and self.effective_span_ppm <= 1_000_000:
            raise ValueError("positive dose remained in old support")
        if any((self.eligible_for_original_candidate_pool, self.eligible_for_original_h1_h2, self.eligible_for_original_agent_comparison)):
            raise ValueError("diagnostic row leaked into an old eligibility pool")
        if self.dose_ppm == 0 and (self.curve_sha256 != self.source_curve_sha256 or not _same(self.state_a_loss, self.source_a_loss)):
            raise ValueError("zero-dose control did not reproduce")
        return self


class ProbeBlockResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_unit_index: int
    parent_id: ParentId
    seed: int
    source_pair_hash: str
    doses: tuple[ProbeDoseResult, ProbeDoseResult, ProbeDoseResult]
    high_dose_improvement: bool
    monotonic_response: bool
    positive_dose_reference_crossing: bool
    crossing_doses_ppm: tuple[int, ...]

    @model_validator(mode="after")
    def valid_block(self) -> Self:
        if tuple(row.dose_ppm for row in self.doses) != DOSES_PPM:
            raise ValueError("block dose order changed")
        if any((row.source_unit_index, row.parent_id, row.seed, row.source_pair_hash) != (self.source_unit_index, self.parent_id, self.seed, self.source_pair_hash) for row in self.doses):
            raise ValueError("block mixes source units")
        low, middle, high = self.doses
        crossings = tuple(row.dose_ppm for row in self.doses[1:] if row.diagnostic_reference_crossing)
        expected = (high.state_a_loss < low.state_a_loss, low.state_a_loss >= middle.state_a_loss >= high.state_a_loss, bool(crossings), crossings)
        if (self.high_dose_improvement, self.monotonic_response, self.positive_dose_reference_crossing, self.crossing_doses_ppm) != expected:
            raise ValueError("block diagnostics do not recompute")
        return self


class ProbeParentResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    parent_id: ParentId
    block_count: Literal[5] = 5
    high_dose_improvements: int
    monotonic_responses: int
    reference_crossings: int


class ProbeAnalysisSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    study_id: Literal["semifinal-a-span-support-causal-probe-v1"] = (
        "semifinal-a-span-support-causal-probe-v1"
    )
    run_id: Literal["semifinal-a-span-support-causal-probe-v1"] = (
        "semifinal-a-span-support-causal-probe-v1"
    )
    study_status: Literal["complete"] = "complete"
    verdict_ceiling: Literal["insufficient_evidence"] = "insufficient_evidence"
    source_log_sha256: str
    source_run_summary_sha256: str
    config_hash: str
    solver_calls_completed: Literal[32] = 32
    solver_mode_counts: dict[str, int]
    b_replays: tuple[ProbeBReplayResult, ProbeBReplayResult]
    blocks: tuple[ProbeBlockResult, ...]
    parent_results: tuple[ProbeParentResult, ProbeParentResult]
    high_dose_improvements: int
    monotonic_responses: int
    p01_crossings: int
    p02_crossings: int
    scientific_endpoint: ScientificEndpoint

    @model_validator(mode="after")
    def valid_analysis(self) -> Self:
        if not all(_sha(value) for value in (self.source_log_sha256, self.source_run_summary_sha256, self.config_hash)):
            raise ValueError("analysis provenance hash is invalid")
        if self.solver_mode_counts != {"subprocess": 32} or len(self.blocks) != 10:
            raise ValueError("analysis does not contain the frozen complete run")
        order = tuple(("p01" if i < 5 else "p02", SEEDS[i % 5], i) for i in range(10))
        if tuple((b.parent_id, b.seed, b.source_unit_index) for b in self.blocks) != order:
            raise ValueError("analysis block order changed")
        high = sum(block.high_dose_improvement for block in self.blocks)
        monotonic = sum(block.monotonic_response for block in self.blocks)
        p01 = sum(block.parent_id == "p01" and block.positive_dose_reference_crossing for block in self.blocks)
        p02 = sum(block.parent_id == "p02" and block.positive_dose_reference_crossing for block in self.blocks)
        if (self.high_dose_improvements, self.monotonic_responses, self.p01_crossings, self.p02_crossings) != (high, monotonic, p01, p02):
            raise ValueError("analysis counts do not recompute")
        if self.parent_results != _parent_results(self.blocks):
            raise ValueError("parent strata do not recompute")
        if self.scientific_endpoint != _classify(high, monotonic, p01, p02):
            raise ValueError("endpoint does not recompute")
        return self


def _source_units(runtime: ModuleType) -> tuple[FrozenProbeUnit, ...]:
    raw = tuple(cast(Sequence[object], runtime.FROZEN_SOURCE_UNITS))
    if len(raw) != 10:
        raise ValueError("runtime must expose ten frozen source units")
    output: list[FrozenProbeUnit] = []
    for index, (item, row) in enumerate(zip(raw, _SOURCE_ROWS, strict=True)):
        parent, seed, run_id, step, pair, length, span, loss = row
        data = _payload(item)
        unit = FrozenProbeUnit(
            index=index,
            parent_id=parent,
            seed=seed,
            source_run_id=run_id,
            source_step_index=step,
            source_proposal_index=step,
            source_pair_hash=pair,
            source_length_um=length,
            source_span_ppm=span,
            source_loss=loss,
            source_curve_sha256=str(_pick(data, "source_a_curve_sha256", "state_a_curve_sha256", "canonical_state_a_curve_sha256")),
            frozen_b_loss=float(_pick(data, "frozen_b_loss", "state_b_loss", "source_b_loss")),
        )
        checks = (
            _pick(data, "parent_id") == parent,
            _pick(data, "seed") == seed,
            _pick(data, "source_run_id") == run_id,
            _pick(data, "source_step_index", "step_index") == step,
            _pick(data, "source_proposal_index", "proposal_index") == step,
            _pick(data, "source_pair_hash", "pair_hash") == pair,
            _pick(data, "state_a_total_wire_length_um", "source_a_total_wire_length_um") == length,
            _pick(data, "source_a_span_ratio_ppm", "state_a_span_ratio_ppm") == span,
            _same(float(_pick(data, "source_a_loss", "state_a_loss")), loss),
        )
        if not all(checks):
            raise ValueError("runtime source-unit table differs from preregistration")
        output.append(unit)
    return tuple(output)


def _parent_results(blocks: Sequence[ProbeBlockResult]) -> tuple[ProbeParentResult, ProbeParentResult]:
    output: list[ProbeParentResult] = []
    for parent in PARENTS:
        typed = cast(ParentId, parent)
        selected = tuple(block for block in blocks if block.parent_id == typed)
        if len(selected) != 5:
            raise ValueError("parent stratum lacks five blocks")
        output.append(ProbeParentResult(
            parent_id=typed,
            high_dose_improvements=sum(block.high_dose_improvement for block in selected),
            monotonic_responses=sum(block.monotonic_response for block in selected),
            reference_crossings=sum(block.positive_dose_reference_crossing for block in selected),
        ))
    return cast(tuple[ProbeParentResult, ProbeParentResult], tuple(output))


def _classify(high: int, monotonic: int, p01: int, p02: int) -> ScientificEndpoint:
    classifier = getattr(_runtime(), "classify_endpoint", None)
    if callable(classifier):
        result = classifier(high, monotonic, p01, p02)
        value = str(getattr(result, "value", result))
    elif high >= 9 and monotonic >= 8 and p01 + p02 >= 5 and p01 >= 2 and p02 >= 2:
        value = "span_support_sufficient_in_frozen_counterfactuals"
    elif high >= 9 and monotonic >= 8:
        value = "span_support_contributor_not_sufficient"
    elif high <= 5 and p01 + p02 == 0:
        value = "span_support_association_not_supported"
    else:
        value = "span_support_inconclusive"
    if value not in _ENDPOINTS:
        raise ValueError("runtime endpoint classifier returned an unknown branch")
    return cast(ScientificEndpoint, value)


def _subset(model: type[BaseModel], data: Mapping[str, Any]) -> dict[str, Any]:
    return {name: data[name] for name in model.model_fields if name in data}


def _events(runtime: ModuleType, path: Path) -> tuple[_BEvent | _AEvent, ...]:
    loader = getattr(runtime, "load_probe_events", None)
    if not callable(loader):
        raise TypeError("runtime lacks load_probe_events(path)")
    output: list[_BEvent | _AEvent] = []
    for raw in cast(Sequence[object], loader(path)):
        data = _payload(raw)
        if data.get("event_type") == "a_span_probe_b_replay":
            output.append(_BEvent.model_validate(_subset(_BEvent, data)))
        elif data.get("event_type") == "a_span_probe_a_evaluation":
            output.append(_AEvent.model_validate(_subset(_AEvent, data)))
        else:
            raise ValueError(f"unknown probe event: {data.get('event_type')!r}")
    return tuple(output)


def _summary(value: object) -> _RunSummary:
    data = _payload(value)
    selected = {
        name: _pick(data, name, "scientific_endpoint" if name == "endpoint" else name)
        for name in _RunSummary.model_fields
    }
    return _RunSummary.model_validate(selected)


def _b_result(event: _BEvent) -> ProbeBReplayResult:
    curve = event.state_b_curve
    if curve.solver_name.lower() != "nec2" or curve.solver_mode != "subprocess" or curve.realized_gain_dbi is not None:
        raise ValueError("B replay is not the frozen NEC2 no-gain call")
    digest = _curve_sha(curve)
    if digest != event.canonical_curve_sha256:
        raise ValueError("B curve hash does not recompute")
    metric = score_state_curve(curve, "B")
    return ProbeBReplayResult(
        parent_id=event.parent_id,
        call_index=event.call_index,
        canonical_curve_sha256=digest,
        selected_index=metric.selected_index,
        selected_frequency_hz=metric.selected_frequency_hz,
        selected_s11_db=metric.selected_s11_db,
        reflected_power_loss=metric.reflected_power_fraction,
        valid_search=metric.valid_search,
    )


def _dose_result(event: _AEvent, unit: FrozenProbeUnit) -> ProbeDoseResult:
    curve = event.state_a_curve
    if curve.solver_name.lower() != "nec2" or curve.solver_mode != "subprocess" or curve.realized_gain_dbi is not None:
        raise ValueError("A row is not the frozen NEC2 no-gain call")
    identity = (event.parent_id, event.seed, event.source_run_id, event.source_step_index, event.source_proposal_index, event.source_pair_hash)
    frozen = (unit.parent_id, unit.seed, unit.source_run_id, unit.source_step_index, unit.source_proposal_index, unit.source_pair_hash)
    if identity != frozen:
        raise ValueError("A row differs from its frozen source unit")
    digest = _curve_sha(curve)
    if digest != event.canonical_curve_sha256:
        raise ValueError("A curve hash does not recompute")
    metric = score_state_curve(curve, "A")
    hybrid = max(metric.reflected_power_fraction, unit.frozen_b_loss)
    valid = event.trajectory_valid and metric.valid_search
    logged = (
        event.state_a_selected_index == metric.selected_index,
        _same(event.state_a_selected_frequency_hz, metric.selected_frequency_hz),
        _same(event.state_a_selected_s11_db, metric.selected_s11_db),
        _same(event.state_a_loss, metric.reflected_power_fraction),
        event.state_a_valid == metric.valid_search,
        _same(event.frozen_b_loss, unit.frozen_b_loss),
        _same(event.hybrid_loss, hybrid),
        event.diagnostic_pair_valid == valid,
        event.diagnostic_reference_crossing == (valid and hybrid <= L_REQUIRED),
        event.source_box_size_um == 40_000,
    )
    if not all(logged):
        raise ValueError("logged A metrics do not independently recompute")
    return ProbeDoseResult(
        source_unit_index=unit.index,
        parent_id=unit.parent_id,
        seed=unit.seed,
        source_run_id=unit.source_run_id,
        source_step_index=unit.source_step_index,
        source_proposal_index=unit.source_proposal_index,
        source_pair_hash=unit.source_pair_hash,
        source_span_ppm=unit.source_span_ppm,
        effective_span_ppm=event.effective_a_span_ratio_ppm,
        dose_ppm=event.dose_ppm,
        call_index=event.call_index,
        source_curve_sha256=unit.source_curve_sha256,
        curve_sha256=digest,
        selected_index=metric.selected_index,
        selected_frequency_hz=metric.selected_frequency_hz,
        selected_s11_db=metric.selected_s11_db,
        state_a_loss=metric.reflected_power_fraction,
        source_a_loss=unit.source_loss,
        delta_a_loss=metric.reflected_power_fraction - unit.source_loss,
        state_a_valid=metric.valid_search,
        frozen_b_loss=unit.frozen_b_loss,
        hybrid_loss=hybrid,
        trajectory_valid=event.trajectory_valid,
        actual_full_width_mm=event.actual_full_width_mm,
        minimum_clearance_mm=event.minimum_clearance_mm,
        diagnostic_pair_valid=valid,
        diagnostic_reference_crossing=valid and hybrid <= L_REQUIRED,
        counterfactual_only=event.counterfactual_only,
        outside_original_span_support=event.outside_original_span_support,
        physical_40mm_trajectory_valid=event.physical_40mm_trajectory_valid,
        eligible_for_original_candidate_pool=event.eligible_for_original_candidate_pool,
        eligible_for_original_h1_h2=event.eligible_for_original_h1_h2,
        eligible_for_original_agent_comparison=event.eligible_for_original_agent_comparison,
    )


def _build_block(
    unit: FrozenProbeUnit,
    rows: Sequence[ProbeDoseResult],
) -> ProbeBlockResult:
    if len(rows) != 3:
        raise ValueError("source unit does not contain exactly three doses")
    doses = cast(
        tuple[ProbeDoseResult, ProbeDoseResult, ProbeDoseResult],
        tuple(rows),
    )
    low, middle, high = doses
    crossing_doses = tuple(
        row.dose_ppm for row in doses[1:] if row.diagnostic_reference_crossing
    )
    return ProbeBlockResult(
        source_unit_index=unit.index,
        parent_id=unit.parent_id,
        seed=unit.seed,
        source_pair_hash=unit.source_pair_hash,
        doses=doses,
        high_dose_improvement=high.state_a_loss < low.state_a_loss,
        monotonic_response=(
            low.state_a_loss >= middle.state_a_loss >= high.state_a_loss
        ),
        positive_dose_reference_crossing=bool(crossing_doses),
        crossing_doses_ppm=crossing_doses,
    )


def _canonical_json_bytes(value: object) -> bytes:
    payload: object = (
        value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    )
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise TypeError("run summary is not canonical JSON evidence") from error


def analyze_probe_events(
    log_path: Path,
    run_summary: object,
) -> ProbeAnalysisSummary:
    """Recompute the complete preregistered endpoint from one log and summary."""

    log_bytes = log_path.read_bytes()
    if not log_bytes or not log_bytes.endswith(b"\n") or b"\r" in log_bytes:
        raise ValueError("probe log must be non-empty, newline-terminated LF-only JSONL")
    log_sha256 = hashlib.sha256(log_bytes).hexdigest()
    runtime = _runtime()
    events = _events(runtime, log_path)
    summary = _summary(run_summary)
    raw_summary = _payload(run_summary)
    if "config" in raw_summary:
        recomputed_config_hash = hashlib.sha256(
            _canonical_json_bytes(raw_summary["config"])
        ).hexdigest()
        if recomputed_config_hash != summary.config_hash:
            raise ValueError("run-summary config hash does not recompute")
    expected_summary = (
        summary.study_id == STUDY_ID,
        summary.run_id == RUN_ID,
        summary.seed == 0,
        summary.steps_completed == PLANNED_CALLS,
        summary.solver_calls_completed == PLANNED_CALLS,
        summary.solver_mode_counts == {"subprocess": PLANNED_CALLS},
        summary.b_replay_calls == 2,
        summary.a_solver_calls == 30,
        summary.verdict_ceiling == "insufficient_evidence",
        summary.openems_calls == 0,
        summary.log_sha256 == log_sha256,
        _sha(summary.config_hash),
    )
    if not all(expected_summary):
        raise ValueError("run summary differs from the frozen complete-run contract")
    if len(events) != PLANNED_CALLS:
        raise ValueError("probe log does not contain exactly 32 scientific events")
    if tuple(event.call_index for event in events) != tuple(range(PLANNED_CALLS)):
        raise ValueError("probe call indices are not the frozen 0..31 sequence")
    if any(event.solver_mode != "subprocess" for event in events):
        raise ValueError("probe log contains a non-subprocess solver call")
    if not all(isinstance(event, _BEvent) for event in events[:2]):
        raise ValueError("first two calls are not frozen B replays")
    if not all(isinstance(event, _AEvent) for event in events[2:]):
        raise ValueError("last thirty calls are not A-dose evaluations")

    b_events = cast(tuple[_BEvent, _BEvent], events[:2])
    if tuple(event.parent_id for event in b_events) != PARENTS:
        raise ValueError("B replay parent order changed")
    b_replays = cast(
        tuple[ProbeBReplayResult, ProbeBReplayResult],
        tuple(_b_result(event) for event in b_events),
    )
    units = _source_units(runtime)
    a_events = cast(tuple[_AEvent, ...], events[2:])
    dose_rows: list[list[ProbeDoseResult]] = [[] for _ in units]
    for offset, event in enumerate(a_events):
        dose_index, unit_index = divmod(offset, len(units))
        unit = units[unit_index]
        expected_dose = DOSES_PPM[dose_index]
        if event.dose_ppm != expected_dose:
            raise ValueError("A-dose execution order changed")
        dose_rows[unit_index].append(_dose_result(event, unit))
    blocks = tuple(
        _build_block(unit, dose_rows[unit.index]) for unit in units
    )
    high = sum(block.high_dose_improvement for block in blocks)
    monotonic = sum(block.monotonic_response for block in blocks)
    p01 = sum(
        block.parent_id == "p01" and block.positive_dose_reference_crossing
        for block in blocks
    )
    p02 = sum(
        block.parent_id == "p02" and block.positive_dose_reference_crossing
        for block in blocks
    )
    endpoint = _classify(high, monotonic, p01, p02)
    logged_endpoint = (
        summary.high_dose_improvements,
        summary.monotonic_responses,
        summary.p01_crossings,
        summary.p02_crossings,
        summary.endpoint,
    )
    recomputed_endpoint = (high, monotonic, p01, p02, endpoint)
    if logged_endpoint != recomputed_endpoint:
        raise ValueError("run-summary endpoint does not match independent recomputation")
    return ProbeAnalysisSummary(
        source_log_sha256=log_sha256,
        source_run_summary_sha256=hashlib.sha256(
            _canonical_json_bytes(run_summary)
        ).hexdigest(),
        config_hash=summary.config_hash,
        solver_mode_counts={"subprocess": PLANNED_CALLS},
        b_replays=b_replays,
        blocks=blocks,
        parent_results=_parent_results(blocks),
        high_dose_improvements=high,
        monotonic_responses=monotonic,
        p01_crossings=p01,
        p02_crossings=p02,
        scientific_endpoint=endpoint,
    )


def render_probe_report(analysis: ProbeAnalysisSummary) -> str:
    """Render the complete finite-set result with frozen claims boundaries."""

    checked = ProbeAnalysisSummary.model_validate(analysis.model_dump())
    lines = [
        "# A-span support causal probe v1",
        "",
        "## Frozen endpoint",
        "",
        f"- Scientific endpoint: `{checked.scientific_endpoint}`",
        f"- Verdict ceiling: `{checked.verdict_ceiling}`",
        f"- High-dose improvements: {checked.high_dose_improvements}/10",
        f"- Monotonic responses: {checked.monotonic_responses}/10",
        f"- Positive-dose reference crossings: p01 {checked.p01_crossings}/5; "
        f"p02 {checked.p02_crossings}/5",
        f"- Solver evidence: {checked.solver_calls_completed} subprocess NEC2 calls; "
        "0 openEMS calls; no realized-gain endpoint",
        "",
        "## Ten frozen source-selected blocks",
        "",
        "| Parent | Seed | A loss +0 | A loss +50k | A loss +100k | High-dose "
        "improvement | Monotonic | Positive-dose crossing |",
        "|---|---:|---:|---:|---:|---|---|---|",
    ]
    for block in checked.blocks:
        low, middle, high = block.doses
        crossing = (
            ", ".join(f"+{dose}" for dose in block.crossing_doses_ppm)
            if block.crossing_doses_ppm
            else "none"
        )
        lines.append(
            f"| {block.parent_id} | {block.seed} | {low.state_a_loss:.12g} | "
            f"{middle.state_a_loss:.12g} | {high.state_a_loss:.12g} | "
            f"{'yes' if block.high_dose_improvement else 'no'} | "
            f"{'yes' if block.monotonic_response else 'no'} | {crossing} |"
        )
    lines.extend(
        (
            "",
            "## Geometry and provenance gates",
            "",
            "| Parent | Seed | Dose (ppm) | Effective span (ppm) | Width (mm) | "
            "Minimum clearance (mm) | Selected frequency (GHz) | S11 (dB) | "
            "Hybrid loss | Valid |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        )
    )
    for block in checked.blocks:
        for row in block.doses:
            lines.append(
                f"| {row.parent_id} | {row.seed} | {row.dose_ppm} | "
                f"{row.effective_span_ppm} | {row.actual_full_width_mm:.6f} | "
                f"{row.minimum_clearance_mm:.6f} | "
                f"{row.selected_frequency_hz / 1e9:.6f} | "
                f"{row.selected_s11_db:.6f} | {row.hybrid_loss:.12g} | "
                f"{'yes' if row.diagnostic_pair_valid else 'no'} |"
            )
    lines.extend(
        (
            "",
            "## Claims boundary",
            "",
            "This is a source-selected, finite-set, model-internal NEC2 "
            "counterfactual probe. It holds the 40 mm box, feed, state-A wire "
            "length, topology, state B, solver, frequency table, and score fixed; "
            "only state-A span-control support changes.",
            "",
            "Positive-dose rows are outside the original A-span support. They are "
            "diagnostic-only: they are not candidates from the original search, H1/H2 "
            "records, candidate-pool entries, or agent-comparison evidence.",
            "",
            "The selected blocks are not an unbiased sample from antenna space. "
            "The result cannot establish a real-world causal effect, a physical "
            "limit, manufacturing feasibility, independent-solver confirmation, "
            "or a new antenna. The verdict ceiling remains `insufficient_evidence`.",
            "",
            f"Source log SHA-256: `{checked.source_log_sha256}`  ",
            f"Source run-summary SHA-256: `{checked.source_run_summary_sha256}`",
            "",
        )
    )
    return "\n".join(lines)


def _render_probe_png(analysis: ProbeAnalysisSummary) -> bytes:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(8.0, 4.8), dpi=150, facecolor="white")
    canvas = FigureCanvasAgg(figure)
    axes = figure.add_subplot(1, 1, 1)
    x_values = (0, 50_000, 100_000)
    colors = {"p01": "#1f77b4", "p02": "#d62728"}
    for index, block in enumerate(analysis.blocks):
        axes.plot(
            x_values,
            [row.state_a_loss for row in block.doses],
            color=colors[block.parent_id],
            marker="o",
            markersize=3.5,
            linewidth=1.25,
            alpha=0.82,
            label=(block.parent_id if index in (0, 5) else None),
        )
    axes.axhline(
        L_REQUIRED,
        color="#222222",
        linestyle="--",
        linewidth=1.2,
        label="old numerical reference",
    )
    axes.set_title("Frozen A-span support dose response", fontfamily="DejaVu Sans")
    axes.set_xlabel("Additive A-span dose (ppm)", fontfamily="DejaVu Sans")
    axes.set_ylabel("State-A reflected-power loss", fontfamily="DejaVu Sans")
    axes.set_xticks(x_values, ("0", "+50,000", "+100,000"))
    axes.grid(True, color="#d9d9d9", linewidth=0.6, alpha=0.8)
    axes.legend(loc="best", frameon=False, prop={"family": "DejaVu Sans", "size": 8})
    figure.tight_layout(pad=1.0)
    buffer = io.BytesIO()
    canvas.print_png(  # type: ignore[no-untyped-call]
        buffer,
        metadata={"Software": "YAF A-span support causal probe v1"},
        pil_kwargs={"compress_level": 9},
    )
    payload = buffer.getvalue()
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("matplotlib did not emit a PNG")
    return payload


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def write_probe_outputs(
    analysis: ProbeAnalysisSummary,
    output_dir: Path,
) -> None:
    """Write strict JSON, LF-only Markdown, and a deterministic PNG atomically."""

    checked = ProbeAnalysisSummary.model_validate(analysis.model_dump())
    summary_bytes = (
        json.dumps(
            checked.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    report_bytes = render_probe_report(checked).encode("utf-8")
    if b"\r" in summary_bytes or b"\r" in report_bytes:
        raise ValueError("probe JSON and Markdown outputs must be LF-only")
    png_bytes = _render_probe_png(checked)
    _atomic_write(output_dir / "summary.json", summary_bytes)
    _atomic_write(output_dir / "report.md", report_bytes)
    _atomic_write(output_dir / PLOT_FILENAME, png_bytes)


__all__ = [
    "ProbeAnalysisSummary",
    "ProbeBlockResult",
    "ProbeDoseResult",
    "analyze_probe_events",
    "render_probe_report",
    "write_probe_outputs",
]
