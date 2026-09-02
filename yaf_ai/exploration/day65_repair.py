"""Frozen-candidate execution under the released Day 6.5 renderer."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve, _curve
from yaf_ai.exploration.day6_cross_check import (
    DAY6_GAP_THRESHOLD,
    DAY6_OPENEMS_CONVERGENCE_THRESHOLD,
    DAY6_PEARSON_THRESHOLD,
    Day6CrossCheckDecision,
    Day6InstrumentRunSummary,
    SelectedDay6Design,
    evaluate_day6_curves,
    high_band_shift,
    load_day6_selection,
    reconstruct_day6_design,
)
from yaf_ai.exploration.freeform_wire import (
    FREEFORM_FREQUENCY_POINTS,
    FREEFORM_SWEEP_HZ,
)
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

DAY65_REPAIR_PROTOCOL = "day65-freeform-repair-v12"
DAY65_RELEASED_REFINEMENT = 6.0
DAY65_OPENEMS_BASE_TIMESTEPS = 40000
DAY65_OPENEMS_TIMEOUT_SECONDS = 21600.0
DAY65_NEC2_SOURCE_RUN_IDS = {
    1: "day6-freeform-final-crosscheck-top1",
    2: "day6-freeform-final-crosscheck-top2",
}

BandVerdict = Literal["CONFIRMED", "DIVERGENT", "NO_RESONANCE_IN_BAND"]


class Day65CandidateRunSummary(BaseModel):
    """One new openEMS curve paired with immutable archived NEC2 evidence."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 1
    evaluation_budget: int = 1
    solver_mode_counts: dict[str, int]
    selected_design: SelectedDay6Design
    nec2_source_run_id: str
    openems_curve_source_run_id: str | None
    nec2_curve_sha256: str
    nec2: SolverCurve
    openems: SolverCurve
    decision: Day6CrossCheckDecision
    whole_sweep_pearson: float
    low_band_verdict: BandVerdict
    high_band_verdict: BandVerdict
    dual_band_verdict: BandVerdict
    discovery_verdict: Literal["confirmed_improvement", "insufficient_evidence"]


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def _write_run(
    run_directory: Path,
    summary: Day6InstrumentRunSummary | Day65CandidateRunSummary,
    records: list[dict[str, object]],
) -> None:
    run_directory.mkdir(parents=True, exist_ok=False)
    payload = "".join(
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
        for record in records
    )
    (run_directory / "log.jsonl").write_bytes(payload.encode("utf-8"))
    _write_json(run_directory / "summary.json", summary.model_dump(mode="json"))


def _whole_sweep_pearson(openems: SolverCurve, nec2: SolverCurve) -> float:
    frequencies = np.asarray(openems.frequency_hz, dtype=float)
    left = np.asarray(openems.s11_db, dtype=float)
    right = np.interp(
        frequencies,
        np.asarray(nec2.frequency_hz, dtype=float),
        np.asarray(nec2.s11_db, dtype=float),
    )
    if float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def _band_verdict(
    decision: Day6CrossCheckDecision,
    band: Literal["low", "high"],
    pearson: float,
) -> BandVerdict:
    value = decision.low_band if band == "low" else decision.high_band
    if not value.openems.valid or not value.nec2.valid:
        return "NO_RESONANCE_IN_BAND"
    if bool(value.resonance_threshold_met) and pearson >= DAY6_PEARSON_THRESHOLD:
        return "CONFIRMED"
    return "DIVERGENT"


def _load_source_nec2(
    repo_root: Path, selected: SelectedDay6Design
) -> tuple[str, SolverCurve, str]:
    source_run_id = DAY65_NEC2_SOURCE_RUN_IDS[selected.rank]
    path = repo_root / "artifacts" / "runs" / source_run_id / "summary.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        stored = SelectedDay6Design.model_validate(payload["selected_design"])
        curve_payload = payload["nec2"]
        curve = SolverCurve.model_validate(curve_payload)
    except (OSError, KeyError, json.JSONDecodeError, ValueError) as error:
        raise CrossCheckError(f"cannot load archived NEC2 source {source_run_id}") from error
    if stored != selected or curve.solver_mode != "subprocess":
        raise CrossCheckError(f"archived NEC2 source changed: {source_run_id}")
    return source_run_id, curve, _canonical_hash(curve_payload)


async def run_repaired_openems_instrument(
    repo_root: Path,
    selected: SelectedDay6Design,
    *,
    refinement: float,
) -> Day6InstrumentRunSummary:
    """Run one full-sweep openEMS convergence level for candidate A."""

    suffix = f"{refinement:g}x"
    run_id = f"day65-repair-openems-convergence-top{selected.rank}-{suffix}"
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        summary = Day6InstrumentRunSummary.model_validate_json(
            (run_directory / "summary.json").read_text(encoding="utf-8")
        )
        if (
            summary.selected_design != selected
            or summary.config.get("openems_mesh_refinement") != refinement
            or summary.config.get("protocol_version") != DAY65_REPAIR_PROTOCOL
        ):
            raise CrossCheckError(f"existing repaired convergence run changed: {run_id}")
        return summary
    geometry, seed = reconstruct_day6_design(repo_root, selected)
    timeout = 7200.0 if refinement <= 2.0 else DAY65_OPENEMS_TIMEOUT_SECONDS
    settings: dict[str, float | int] = {
        "openems_mesh_refinement": refinement,
        "openems_base_timesteps": DAY65_OPENEMS_BASE_TIMESTEPS,
        "openems_timeout_seconds": timeout,
    }
    spec = SimulationSpec(
        name=run_id,
        frequency_range=FREEFORM_SWEEP_HZ,
        frequency_points=FREEFORM_FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings=settings,
    )
    started_at = datetime.now(UTC)
    adapter = OpenEMSAdapter()
    mesh = await adapter.mesh(geometry, spec)
    curve = _curve(await adapter.solve(mesh, spec))
    if curve.solver_mode != "subprocess":
        raise CrossCheckError(f"repaired convergence is not real: {curve.solver_mode}")
    config: dict[str, Any] = {
        "protocol_version": DAY65_REPAIR_PROTOCOL,
        "purpose": "candidate-A high-band self-convergence",
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "source_geometry_hash": selected.source_geometry_hash,
        "solver": "openems",
        "frequency_range_hz": FREEFORM_SWEEP_HZ,
        "frequency_points": FREEFORM_FREQUENCY_POINTS,
        **settings,
    }
    summary = Day6InstrumentRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=seed,
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 1},
        selected_design=selected,
        curve=curve,
    )
    record: dict[str, object] = {
        "schema_version": 1,
        "event_type": "day65_repaired_instrument_result",
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "protocol_version": DAY65_REPAIR_PROTOCOL,
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "instrument": f"openems-{suffix}",
        "curve": curve.model_dump(mode="json"),
    }
    _write_run(run_directory, summary, [record])
    return summary


def _load_reusable_openems_curve(
    repo_root: Path, selected: SelectedDay6Design
) -> tuple[SolverCurve, str] | None:
    run_id = "day65-repair-openems-convergence-top1-6x"
    path = repo_root / "runs" / run_id / "summary.json"
    if selected.rank != 1 or not path.is_file():
        return None
    summary = Day6InstrumentRunSummary.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    expected = {
        "protocol_version": DAY65_REPAIR_PROTOCOL,
        "openems_mesh_refinement": DAY65_RELEASED_REFINEMENT,
        "openems_base_timesteps": DAY65_OPENEMS_BASE_TIMESTEPS,
        "openems_timeout_seconds": DAY65_OPENEMS_TIMEOUT_SECONDS,
    }
    if summary.selected_design != selected or any(
        summary.config.get(key) != value for key, value in expected.items()
    ):
        raise CrossCheckError("candidate A reusable 6x curve changed")
    if summary.curve.solver_mode != "subprocess":
        raise CrossCheckError("candidate A reusable 6x curve is not real")
    return summary.curve, run_id


async def run_repaired_candidate(
    repo_root: Path, selected: SelectedDay6Design
) -> Day65CandidateRunSummary:
    """Run the released openEMS instrument and reapply unchanged Day 6 gates."""

    run_id = f"day65-repair-crosscheck-top{selected.rank}"
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        return Day65CandidateRunSummary.model_validate_json(
            (run_directory / "summary.json").read_text(encoding="utf-8")
        )
    geometry, seed = reconstruct_day6_design(repo_root, selected)
    source_run_id, nec2, nec2_hash = _load_source_nec2(repo_root, selected)
    settings: dict[str, float | int] = {
        "openems_mesh_refinement": DAY65_RELEASED_REFINEMENT,
        "openems_base_timesteps": DAY65_OPENEMS_BASE_TIMESTEPS,
        "openems_timeout_seconds": DAY65_OPENEMS_TIMEOUT_SECONDS,
    }
    spec = SimulationSpec(
        name=run_id,
        frequency_range=FREEFORM_SWEEP_HZ,
        frequency_points=FREEFORM_FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings=settings,
    )
    started_at = datetime.now(UTC)
    reusable = _load_reusable_openems_curve(repo_root, selected)
    if reusable is None:
        adapter = OpenEMSAdapter()
        mesh = await adapter.mesh(geometry, spec)
        openems = _curve(await adapter.solve(mesh, spec))
        if openems.solver_mode != "subprocess":
            raise CrossCheckError(f"repaired candidate is not real: {openems.solver_mode}")
        openems_source = None
    else:
        openems, openems_source = reusable
    decision = evaluate_day6_curves(openems, nec2)
    pearson = _whole_sweep_pearson(openems, nec2)
    low = _band_verdict(decision, "low", pearson)
    high = _band_verdict(decision, "high", pearson)
    dual: BandVerdict
    if low == high == "CONFIRMED":
        dual = "CONFIRMED"
    elif low == "NO_RESONANCE_IN_BAND" or high == "NO_RESONANCE_IN_BAND":
        dual = "NO_RESONANCE_IN_BAND"
    else:
        dual = "DIVERGENT"
    reference_met = selected.source_score >= 1.10 * selected.ocfd_score
    discovery = (
        "confirmed_improvement"
        if dual == "CONFIRMED" and reference_met
        else "insufficient_evidence"
    )
    config: dict[str, Any] = {
        "protocol_version": DAY65_REPAIR_PROTOCOL,
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "source_geometry_hash": selected.source_geometry_hash,
        "frequency_range_hz": FREEFORM_SWEEP_HZ,
        "frequency_points": FREEFORM_FREQUENCY_POINTS,
        "nec2_source_run_id": source_run_id,
        "nec2_curve_sha256": nec2_hash,
        "openems_curve_source_run_id": openems_source,
        "nec2_segments_per_wavelength": 160,
        "resonance_relative_threshold": DAY6_GAP_THRESHOLD,
        "pearson_threshold": DAY6_PEARSON_THRESHOLD,
        **settings,
    }
    summary = Day65CandidateRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=seed,
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 2},
        selected_design=selected,
        nec2_source_run_id=source_run_id,
        openems_curve_source_run_id=openems_source,
        nec2_curve_sha256=nec2_hash,
        nec2=nec2,
        openems=openems,
        decision=decision,
        whole_sweep_pearson=pearson,
        low_band_verdict=low,
        high_band_verdict=high,
        dual_band_verdict=dual,
        discovery_verdict=discovery,
    )
    records = [
        {
            "schema_version": 1,
            "event_type": "day65_repaired_cross_solver_result",
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "protocol_version": DAY65_REPAIR_PROTOCOL,
            "source_run_id": selected.source_run_id,
            "source_step_index": selected.source_step_index,
            "instrument": "nec2-lambda160-archived",
            "instrument_source_run_id": source_run_id,
            "curve_sha256": nec2_hash,
            "curve": nec2.model_dump(mode="json"),
        },
        {
            "schema_version": 1,
            "event_type": "day65_repaired_cross_solver_result",
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "protocol_version": DAY65_REPAIR_PROTOCOL,
            "source_run_id": selected.source_run_id,
            "source_step_index": selected.source_step_index,
            "instrument": "openems-6x-repaired",
            "instrument_source_run_id": openems_source,
            "curve": openems.model_dump(mode="json"),
        },
    ]
    _write_run(run_directory, summary, records)
    return summary


def repaired_convergence_shift(
    first: Day6InstrumentRunSummary, second: Day6InstrumentRunSummary
) -> float | None:
    """Apply the frozen valid-resonance adjacent-level shift."""

    return high_band_shift(first.curve, second.curve)


def repaired_convergence_passed(shift: float | None) -> bool:
    """Missing valid resonances fail rather than masquerading as zero movement."""

    return shift is not None and shift <= DAY6_OPENEMS_CONVERGENCE_THRESHOLD


def frozen_candidates(repo_root: Path) -> tuple[SelectedDay6Design, SelectedDay6Design]:
    """Return and assert the exact two candidates frozen before Day 6 solving."""

    candidates = load_day6_selection(repo_root).candidates
    addresses = tuple(
        (candidate.source_run_id, candidate.source_step_index) for candidate in candidates
    )
    expected = (("day6-freeform-dual-gp-s202", 193), ("day6-freeform-dual-gp-s202", 172))
    if addresses != expected:
        raise CrossCheckError(f"frozen Day 6 candidates changed: {addresses}")
    return candidates
