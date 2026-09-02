"""Mock-only tests for the frozen Day 6.5 v2 optimizer definition."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from yaf_ai.analysis.day65_v2 import (
    DAY65_ABSOLUTE_ANCHOR_RELEASED,
    apply_static_anchor_ceiling,
)
from yaf_ai.exploration.day65_batch import (
    ES_INITIAL_SIGMA,
    ES_MAX_SIGMA,
    ES_RESTART_STAGNATION,
    RestartedEvolutionStrategy,
    day65_batch_config_document,
    reflect_normalized,
)
from yaf_ai.exploration.day65_selection import rank_unique_base_score_records
from yaf_ai.exploration.environment import ExplorationConfig, StepResult
from yaf_ai.exploration.freeform_wire import day6_design_spec, freeform_proposal_space
from yaf_ai.exploration.logger import AuditStepRecord


def _config() -> ExplorationConfig:
    return ExplorationConfig(
        spec=day6_design_spec(),
        evaluation_budget=500,
        seed=101,
        solver="nec2",
        proposal_space_version=freeform_proposal_space(7).version,
        nec2_segments_per_wavelength=20,
    )


def _result(search_score: float) -> StepResult:
    return StepResult(
        step_index=0,
        timestamp=datetime.now(UTC),
        solver_name="nec2",
        solver_mode="subprocess",
        metrics={"search_score": search_score},
        score=min(search_score, 1.0),
        geometry_hash="a" * 64,
        geometry_summary={"antenna_class": "freeform_wire_3d"},
        proposal_parameters={},
        proposer="es",
    )


def _arm_pending(agent: RestartedEvolutionStrategy) -> None:
    agent._pending = np.full(21, 0.5)


def test_reflection_maps_arbitrary_coordinates_to_unit_interval() -> None:
    reflected = reflect_normalized(np.asarray([-2.3, -0.2, 0.4, 1.2, 2.3]))
    assert reflected == pytest.approx([0.3, 0.2, 0.4, 0.8, 0.3])


def test_batch_config_hash_and_frozen_matrix_are_deterministic() -> None:
    first = day65_batch_config_document()
    second = day65_batch_config_document()
    assert first == second
    assert first.config.agents == ("es", "random")
    assert first.config.seeds == (101, 202, 303)
    assert first.config.budget == 500
    assert first.config.validity_bonus == 0.25


def test_es_one_fifth_rule_expands_after_strict_successes() -> None:
    agent = RestartedEvolutionStrategy(_config())
    _arm_pending(agent)
    agent.observe(_result(0.1))
    for index in range(20):
        _arm_pending(agent)
        agent.observe(_result(0.2 + index))
    assert agent.sigma == pytest.approx(min(ES_MAX_SIGMA, ES_INITIAL_SIGMA * 1.5))


def test_es_restart_is_armed_after_75_accepted_non_improvements() -> None:
    agent = RestartedEvolutionStrategy(_config())
    _arm_pending(agent)
    agent.observe(_result(1.0))
    for _ in range(ES_RESTART_STAGNATION):
        _arm_pending(agent)
        agent.observe(_result(1.0))
    assert agent.restart_pending
    _arm_pending(agent)
    agent.observe(_result(0.0))
    assert not agent.restart_pending
    assert agent.sigma == pytest.approx(ES_INITIAL_SIGMA)


def _audit_row(
    step: int, score: float, search_score: float, geometry_hash: str
) -> AuditStepRecord:
    return AuditStepRecord(
        run_id="day65-freeform-v2-dual-es-s101",
        step_index=step,
        timestamp=datetime.now(UTC),
        geometry_summary={"antenna_class": "freeform_wire_3d"},
        geometry_hash=geometry_hash,
        solver_name="nec2",
        solver_mode="subprocess",
        metrics={"search_score": search_score, "valid_both_bands": 1.0},
        score=score,
        seed=101,
        config_hash="c" * 64,
        proposal_parameters={"node_0_x_m": 0.0},
        proposer="es",
    )


def test_top_two_selection_uses_unshaped_base_score_and_deduplicates() -> None:
    rows = (
        _audit_row(0, 0.80, 0.80, "a" * 64),
        _audit_row(1, 0.70, 0.95, "b" * 64),
        _audit_row(2, 0.79, 1.04, "a" * 64),
        _audit_row(3, 0.75, 1.00, "c" * 64),
    )
    selected = rank_unique_base_score_records(rows)
    assert [row.step_index for row in selected] == [0, 3]


def test_static_terminal_ceiling_blocks_confirmation_without_absolute_anchor() -> None:
    assert not DAY65_ABSOLUTE_ANCHOR_RELEASED
    assert apply_static_anchor_ceiling(
        candidate_level_confirmation=True,
        absolute_anchor_released=False,
    ) == "insufficient_evidence"
    assert apply_static_anchor_ceiling(
        candidate_level_confirmation=True,
        absolute_anchor_released=True,
    ) == "confirmed_improvement"
