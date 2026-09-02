"""Frozen Day 5-1b candidate selection and convergence decisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yaf_ai.exploration.final_wire_protocol import (
    classify_final_instrument_attribution,
    decide_openems_instrument,
    select_deepest_target_band_record,
)
from yaf_ai.exploration.logger import AuditStepRecord


def _record(
    run_id: str,
    step: int,
    *,
    depth: float,
    score: float,
    frequency_hz: float = 2.45e9,
) -> AuditStepRecord:
    return AuditStepRecord(
        run_id=run_id,
        step_index=step,
        timestamp=datetime.now(UTC),
        geometry_summary={},
        geometry_hash=f"{step + 1:064x}",
        solver_name="nec2",
        solver_mode="subprocess",
        metrics={
            "min_s11_db": depth,
            "resonance_frequency_hz": frequency_hz,
            "resonance_index": 20.0,
            "realized_gain_dbi": 0.5,
        },
        score=score,
        seed=101,
        config_hash="a" * 64,
        proposal_parameters={"x": float(step)},
        proposer="gp",
    )


def _write_log(path: Path, records: tuple[AuditStepRecord, ...]) -> None:
    payload = "".join(
        json.dumps(record.model_dump(mode="json"), default=str) + "\n"
        for record in records
    )
    path.write_text(payload, encoding="utf-8", newline="\n")


def test_candidate_b_uses_deepest_band_s11_then_highest_score(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    _write_log(
        first,
        (
            _record("run-a", 0, depth=-7.0, score=0.4),
            _record("run-a", 1, depth=-8.0, score=0.5),
        ),
    )
    _write_log(
        second,
        (
            _record("run-b", 0, depth=-8.0, score=0.7),
            _record("run-b", 1, depth=-20.0, score=0.9, frequency_hz=2.6e9),
        ),
    )
    selected = select_deepest_target_band_record((first, second))
    assert selected.run_id == "run-b"
    assert selected.step_index == 0
    assert selected.score == pytest.approx(0.7)


@pytest.mark.parametrize(
    ("frequencies", "times", "expected"),
    [
        ((2.678e9, 2.60e9), (4.0, 20.0), "use_current"),
        ((2.68e9, 2.59e9), (4.0, 1800.0), "run_8x"),
        ((2.68e9, 2.59e9), (4.0, 1800.1), "run_3x"),
    ],
)
def test_openems_convergence_decision_boundaries(
    frequencies: tuple[float, float],
    times: tuple[float, float],
    expected: str,
) -> None:
    decision = decide_openems_instrument((2.0, 4.0), frequencies, times)
    assert decision.action == expected


def test_openems_eight_x_nonconvergence_is_infeasible() -> None:
    decision = decide_openems_instrument(
        (4.0, 8.0),
        (2.68e9, 2.55e9),
        (20.0, 100.0),
    )
    assert decision.action == "infeasible_at_current_compute"


@pytest.mark.parametrize(
    ("openems", "nec2", "gaps", "expected"),
    [
        ((2.60e9, 2.53e9), (2.56e9, 2.50e9), (0.08, 0.05), "instrument_boundary"),
        ((2.60e9, 2.53e9), (2.56e9, 2.50e9), (0.08, 0.051), "genuine_anomaly"),
        ((2.68e9, 2.55e9), (2.56e9, 2.50e9), (0.08, 0.04), "infeasible_at_current_compute"),
    ],
)
def test_final_attribution_boundaries(
    openems: tuple[float, float],
    nec2: tuple[float, float],
    gaps: tuple[float, float],
    expected: str,
) -> None:
    result = classify_final_instrument_attribution(
        openems_adjacent_frequencies_hz=openems,
        nec2_adjacent_frequencies_hz=nec2,
        nec2_to_final_openems_gaps=gaps,
    )
    assert result.verdict == expected
