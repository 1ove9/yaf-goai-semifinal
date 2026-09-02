"""Tests for B-parent conditional-completion analysis."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from yaf_ai.analysis.paired_b_completion import (
    AGENTS,
    L_REQUIRED,
    PARENTS,
    SEEDS,
    Agent,
    BCompletionAppendix,
    BCompletionCellRow,
    BCompletionRecordRef,
    ParentId,
    build_b_completion_appendix,
    expected_run_id,
    render_b_completion_report,
    write_b_completion_outputs,
)
from yaf_ai.exploration.paired_meander import (
    HardwareSpec,
    PairedProposal,
    StateControl,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _proposal(agent: Agent) -> PairedProposal:
    return PairedProposal(
        hardware=HardwareSpec(
            turn_count=3,
            feed_gap_ratio_ppm=49_001,
            terminal_ratio_ppm=0,
        ),
        state_a=StateControl(
            state="A",
            total_wire_length_um=78_000,
            span_ratio_ppm=880_000,
        ),
        state_b=StateControl(
            state="B",
            total_wire_length_um=26_090,
            span_ratio_ppm=785_552,
        ),
        proposer=agent,
    )


def _record(
    parent_id: ParentId,
    agent: Agent,
    seed: int,
    step_index: int,
) -> BCompletionRecordRef:
    token = f"{parent_id}-{agent}-{seed}-{step_index}"
    return BCompletionRecordRef(
        parent_id=parent_id,
        agent=agent,
        seed=seed,
        run_id=expected_run_id(parent_id, agent, seed),
        step_index=step_index,
        proposal_index=step_index,
        proposer=agent,
        proposal=_proposal(agent),
        hardware_hash=_digest(f"hardware-{parent_id}"),
        state_a_geometry_hash=_digest(f"state-a-{token}"),
        state_b_geometry_hash=_digest(f"state-b-{parent_id}"),
        pair_hash=_digest(f"pair-{token}"),
        valid_pair_search=False,
        base_score=0.5,
        search_score=0.5,
        worst_reflected_power_fraction=0.4,
    )


@pytest.fixture(scope="module")
def base_records() -> tuple[BCompletionRecordRef, ...]:
    parent_ids: tuple[ParentId, ...] = ("p01", "p02")
    agents: tuple[Agent, ...] = ("random-b-completion", "es-b-completion")
    return tuple(
        _record(parent_id, agent, seed, step_index)
        for parent_id in parent_ids
        for agent in agents
        for seed in SEEDS
        for step_index in range(300)
    )


def _rows(
    records: tuple[BCompletionRecordRef, ...],
) -> tuple[BCompletionCellRow, ...]:
    parent_ids: tuple[ParentId, ...] = ("p01", "p02")
    agents: tuple[Agent, ...] = ("random-b-completion", "es-b-completion")
    grouped: dict[tuple[ParentId, Agent, int], list[BCompletionRecordRef]] = {}
    for record in records:
        grouped.setdefault(
            (record.parent_id, record.agent, record.seed),
            [],
        ).append(record)
    return tuple(
        BCompletionCellRow(
            parent_id=parent_id,
            agent=agent,
            seed=seed,
            run_id=expected_run_id(parent_id, agent, seed),
            execution_status="completed",
            source_status="completed",
            accepted_count=300,
            rejected_count=0,
            proposal_attempts=300,
            solver_mode_counts={"subprocess": 600},
            h1_count=sum(
                record.h1 for record in grouped[(parent_id, agent, seed)]
            ),
            h2_count=sum(
                record.h2 for record in grouped[(parent_id, agent, seed)]
            ),
            log_sha256=_digest(f"log-{parent_id}-{agent}-{seed}"),
            summary_sha256=_digest(f"summary-{parent_id}-{agent}-{seed}"),
        )
        for parent_id in parent_ids
        for agent in agents
        for seed in SEEDS
    )


def _replace(
    records: tuple[BCompletionRecordRef, ...],
    index: int,
    *,
    valid: bool,
    reflected: float,
    pair_token: str | None = None,
) -> tuple[BCompletionRecordRef, ...]:
    replacement = records[index].model_copy(
        update={
            "valid_pair_search": valid,
            "worst_reflected_power_fraction": reflected,
            "pair_hash": (
                records[index].pair_hash
                if pair_token is None
                else _digest(pair_token)
            ),
        }
    )
    return records[:index] + (replacement,) + records[index + 1 :]


def test_three_scientific_endpoints_require_complete_matrix(
    base_records: tuple[BCompletionRecordRef, ...],
) -> None:
    no_h1 = build_b_completion_appendix(_rows(base_records), base_records)
    assert no_h1.scientific_endpoint == "no_b_completion_pair_observed"
    assert no_h1.h1_count == 0
    assert no_h1.h2_count == 0
    assert no_h1.selected_hypothesis is None

    h1_records = _replace(base_records, 0, valid=True, reflected=0.25)
    h1_only = build_b_completion_appendix(_rows(h1_records), h1_records)
    assert h1_only.scientific_endpoint == (
        "b_completion_pair_validity_without_effect_crossing"
    )
    assert h1_only.h1_count == 1
    assert h1_only.h2_count == 0
    assert h1_only.selected_hypothesis == h1_records[0]

    h2_records = _replace(base_records, 0, valid=True, reflected=L_REQUIRED)
    effect = build_b_completion_appendix(_rows(h2_records), h2_records)
    assert effect.scientific_endpoint == "b_completion_effect_crossing_observed"
    assert effect.h1_count == 1
    assert effect.h2_count == 1
    assert effect.selected_hypothesis == h2_records[0]


def test_seed_support_and_global_descriptive_selection_use_frozen_key(
    base_records: tuple[BCompletionRecordRef, ...],
) -> None:
    first = _replace(
        base_records,
        0,
        valid=True,
        reflected=0.19,
        pair_token="z-pair",
    )
    second = _replace(
        first,
        300,
        valid=True,
        reflected=0.19,
        pair_token="a-pair",
    )
    third = _replace(
        second,
        3_300,
        valid=True,
        reflected=0.25,
        pair_token="h1-only",
    )
    appendix = build_b_completion_appendix(_rows(third), third)
    assert appendix.selected_hypothesis == min(
        (third[0], third[300]),
        key=lambda record: record.pair_hash,
    )
    support = {
        (item.parent_id, item.agent): item
        for item in appendix.seed_support or ()
    }
    p01_random = support[("p01", "random-b-completion")]
    assert p01_random.h1_seeds == (101, 202)
    assert p01_random.h2_seeds == (101, 202)
    assert p01_random.h1_seed_count == 2
    assert p01_random.h2_seed_count == 2
    p02_random = support[("p02", "random-b-completion")]
    assert p02_random.h1_seeds == (202,)
    assert p02_random.h2_seeds == ()


def _not_run_rows() -> tuple[BCompletionCellRow, ...]:
    parent_ids: tuple[ParentId, ...] = ("p01", "p02")
    agents: tuple[Agent, ...] = ("random-b-completion", "es-b-completion")
    return tuple(
        BCompletionCellRow(
            parent_id=parent_id,
            agent=agent,
            seed=seed,
            run_id=expected_run_id(parent_id, agent, seed),
            execution_status="not_run_after_matrix_abort",
            accepted_count=0,
            rejected_count=0,
            proposal_attempts=0,
            solver_mode_counts={},
            h1_count=0,
            h2_count=0,
        )
        for parent_id in parent_ids
        for agent in agents
        for seed in SEEDS
    )


def test_certificate_failure_has_null_scientific_fields() -> None:
    appendix = build_b_completion_appendix(
        _not_run_rows(),
        (),
        study_status="support_certificate_failed",
        matrix_exception_type="SupportCertificateFailure",
        matrix_exception_message="one exact support witness failed",
    )
    assert appendix.study_status == "support_certificate_failed"
    assert appendix.completed_prefix == ()
    assert appendix.failed_run_id is None
    assert appendix.scientific_endpoint is None
    assert appendix.h1_count is None
    assert appendix.h2_count is None
    assert appendix.seed_support is None
    assert appendix.selected_hypothesis is None

    rows = list(_not_run_rows())
    first = rows[0]
    rows[0] = BCompletionCellRow(
        parent_id=first.parent_id,
        agent=first.agent,
        seed=first.seed,
        run_id=first.run_id,
        execution_status="execution_failed",
        source_status="solver_timeout",
        accepted_count=0,
        rejected_count=0,
        proposal_attempts=1,
        solver_mode_counts={},
        h1_count=0,
        h2_count=0,
        log_sha256=_digest("empty-partial-log"),
        partial_log_bytes=0,
        partial_log_lines=0,
        exception_type="TimeoutError",
        exception_message="solver exceeded the frozen timeout",
    )
    with pytest.raises(ValueError, match="certificate failure cannot carry"):
        BCompletionAppendix(
            study_status="support_certificate_failed",
            rows=tuple(rows),
            completed_prefix=(),
            matrix_exception_type="SupportCertificateFailure",
            matrix_exception_message="one exact support witness failed",
        )


def test_matrix_failure_preserves_terminal_evidence_and_null_endpoint() -> None:
    rows = list(_not_run_rows())
    first = rows[0]
    rows[0] = BCompletionCellRow(
        parent_id=first.parent_id,
        agent=first.agent,
        seed=first.seed,
        run_id=first.run_id,
        execution_status="execution_failed",
        source_status="solver_timeout",
        accepted_count=0,
        rejected_count=0,
        proposal_attempts=1,
        solver_mode_counts={},
        h1_count=0,
        h2_count=0,
        log_sha256=_digest("empty-partial-log"),
        partial_log_bytes=0,
        partial_log_lines=0,
        exception_type="TimeoutError",
        exception_message="solver exceeded the frozen timeout",
    )
    appendix = build_b_completion_appendix(
        tuple(rows),
        (),
        study_status="solver_timeout",
        matrix_exception_type="TimeoutError",
        matrix_exception_message="the first matrix cell failed",
    )
    assert appendix.failed_run_id == first.run_id
    assert appendix.completed_prefix == ()
    assert appendix.scientific_endpoint is None
    assert appendix.selected_hypothesis is None


def test_selection_key_collision_is_rejected(
    base_records: tuple[BCompletionRecordRef, ...],
) -> None:
    records = _replace(
        base_records,
        0,
        valid=True,
        reflected=0.19,
        pair_token="same-key",
    )
    duplicate = records[1].model_copy(
        update={
            "valid_pair_search": True,
            "worst_reflected_power_fraction": 0.19,
            "pair_hash": _digest("same-key"),
            "run_id": records[0].run_id,
            "step_index": records[0].step_index,
        }
    )
    records = records[:1] + (duplicate,) + records[2:]
    with pytest.raises(ValueError, match="selection key is ambiguous"):
        build_b_completion_appendix(_rows(records), records)


def test_report_and_appendix_are_lf_only_and_disclose_one_seed(
    tmp_path: Path,
    base_records: tuple[BCompletionRecordRef, ...],
) -> None:
    records = _replace(base_records, 0, valid=True, reflected=L_REQUIRED)
    appendix = build_b_completion_appendix(_rows(records), records)
    report = render_b_completion_report(appendix)
    assert "one-seed fact; not a stability claim" in report
    completed_cell_marker = "| " + chr(96) + "completed" + chr(96) + " |"
    assert report.count(completed_cell_marker) == 20

    write_b_completion_outputs(tmp_path, appendix)
    for name in ("appendix.json", "report.md"):
        payload = (tmp_path / name).read_bytes()
        assert b"\r" not in payload
        assert payload.endswith(b"\n")


def test_frozen_matrix_order_and_names_are_exact() -> None:
    assert PARENTS == ("p01", "p02")
    assert AGENTS == ("random-b-completion", "es-b-completion")
    assert expected_run_id("p02", "es-b-completion", 505) == (
        "semifinal-paired-b-completion-p02-es-s505"
    )
    with pytest.raises(ValueError, match="frozen matrix order"):
        BCompletionAppendix(
            study_status="support_certificate_failed",
            rows=tuple(reversed(_not_run_rows())),
            completed_prefix=(),
            matrix_exception_type="SupportCertificateFailure",
            matrix_exception_message="certificate failed",
        )
