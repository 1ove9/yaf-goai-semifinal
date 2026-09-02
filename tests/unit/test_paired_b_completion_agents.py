"""Tests for isolated B-parent A-only random and restarted-ES agents."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pytest

from yaf_ai.exploration.day65_batch import (
    ES_ADAPTATION_BLOCK,
    ES_INITIAL_SIGMA,
    ES_RESTART_STAGNATION,
    reflect_normalized,
)
from yaf_ai.exploration.paired_b_completion_agents import (
    ES_AGENT,
    FROZEN_SEEDS,
    RANDOM_AGENT,
    BCompletionAgentError,
    BCompletionFatalRejectionError,
    BCompletionRandomProposer,
    BCompletionRestartedES,
    BOnlyParentCodeKey,
    RawVector,
    assign_parent_codes,
    build_stream_rng,
)
from yaf_ai.exploration.paired_meander import (
    HardwareSpec,
    PairedEvaluation,
    PairedMetrics,
    PairedProposal,
    SearchCurve,
    StateControl,
    StateSearchMetrics,
    TrajectoryAudit,
    pair_hash,
)

SOURCE_RUN_ID = "semifinal-paired-stratified-v2-es-s404"
P01 = BOnlyParentCodeKey(
    parent_id="p01",
    state_b_geometry_hash=(
        "c9b3f991597ee1bb7082b5f2fe5ffb41f78bf0b8723bac8d6d57bb1eff9a4ee1"
    ),
    hardware_hash=(
        "52cc0dfe93a241643f2089bbd67f4d674edede0dfd38617983d9841a530a302b"
    ),
    run_id=SOURCE_RUN_ID,
    step_index=52,
    proposal_index=52,
)
P02 = BOnlyParentCodeKey(
    parent_id="p02",
    state_b_geometry_hash=(
        "dea79fb9a94126ec2406840ff973973c66bec9c1230badf438c3db8f781c4d7d"
    ),
    hardware_hash=(
        "2c2283aa418160650b84e8849574531cb7816f8845874952b1a0ba2c4a1b65f1"
    ),
    run_id=SOURCE_RUN_ID,
    step_index=136,
    proposal_index=136,
)
PARENTS = (P02, P01)

FIRST_DRAW_HEX: dict[tuple[str, str, int], tuple[str, str]] = {
    (ES_AGENT, "p01", 101): ("0x1.198cfb0086528p-4", "0x1.97a72526ed140p-5"),
    (ES_AGENT, "p01", 202): ("0x1.e179498bc51e0p-3", "0x1.cd5d2a4e730ebp-1"),
    (ES_AGENT, "p01", 303): ("0x1.912402547e1d0p-4", "0x1.01d5ada3c6298p-4"),
    (ES_AGENT, "p01", 404): ("0x1.6c8576da75c5cp-3", "0x1.13b4f2074a4acp-3"),
    (ES_AGENT, "p01", 505): ("0x1.2913fa82eb799p-1", "0x1.b978fd346b036p-2"),
    (ES_AGENT, "p02", 101): ("0x1.e86be9b0e1dc1p-1", "0x1.31081da45ad08p-2"),
    (ES_AGENT, "p02", 202): ("0x1.069c9158a47bcp-2", "0x1.0a33dfa7e90c2p-1"),
    (ES_AGENT, "p02", 303): ("0x1.67402c607f17cp-2", "0x1.75ec74cf664dep-2"),
    (ES_AGENT, "p02", 404): ("0x1.f061ac9a4d4e4p-1", "0x1.8460cfd29ec69p-1"),
    (ES_AGENT, "p02", 505): ("0x1.2c240bc2e3cedp-1", "0x1.08cd70f7ba844p-3"),
    (RANDOM_AGENT, "p01", 101): (
        "0x1.12ee90319f165p-1",
        "0x1.fd8c0aa7ec6c6p-1",
    ),
    (RANDOM_AGENT, "p01", 202): (
        "0x1.f946090c97668p-1",
        "0x1.60a9007ab72e8p-3",
    ),
    (RANDOM_AGENT, "p01", 303): (
        "0x1.f510d5715cf20p-5",
        "0x1.1a22657080017p-1",
    ),
    (RANDOM_AGENT, "p01", 404): (
        "0x1.fb70da175bd6ap-2",
        "0x1.63ea5baf65a57p-1",
    ),
    (RANDOM_AGENT, "p01", 505): (
        "0x1.a66ede8078186p-2",
        "0x1.e2832b407b127p-1",
    ),
    (RANDOM_AGENT, "p02", 101): (
        "0x1.fe55e53cce1fap-1",
        "0x1.6f1cba41d0cc0p-5",
    ),
    (RANDOM_AGENT, "p02", 202): (
        "0x1.71ff433024564p-3",
        "0x1.098051c22e5e6p-1",
    ),
    (RANDOM_AGENT, "p02", 303): (
        "0x1.d1a93cdb16cb8p-2",
        "0x1.cfc812c5e44ddp-1",
    ),
    (RANDOM_AGENT, "p02", 404): (
        "0x1.5c371ff9d15f4p-1",
        "0x1.2642cc22ffba9p-1",
    ),
    (RANDOM_AGENT, "p02", 505): (
        "0x1.7028410ad1326p-2",
        "0x1.bd782dfd99920p-5",
    ),
}


@dataclass
class _RecordingDecoder:
    calls: list[tuple[RawVector, str]] = field(default_factory=list)

    def __call__(self, raw: RawVector, proposer: str) -> PairedProposal:
        self.calls.append((raw, proposer))
        return PairedProposal(
            hardware=HardwareSpec(
                turn_count=3,
                feed_gap_ratio_ppm=49_001,
                terminal_ratio_ppm=0,
            ),
            state_a=StateControl(
                state="A",
                total_wire_length_um=78_679,
                span_ratio_ppm=879_296,
            ),
            state_b=StateControl(
                state="B",
                total_wire_length_um=26_090,
                span_ratio_ppm=785_552,
            ),
            proposer=proposer,
        )


def _state_metrics(state: str) -> StateSearchMetrics:
    return StateSearchMetrics(
        state=state,
        selected_index=0,
        selected_frequency_hz=1.0,
        selected_s11_db=-1.0,
        valid_search=False,
        figure_of_merit=0.1,
        reflected_power_fraction=0.9,
        realized_gain_dbi=None,
    )


def _evaluation(proposal: PairedProposal, score: float) -> PairedEvaluation:
    curve = SearchCurve(
        solver_name="nec2",
        solver_mode="subprocess",
        frequency_hz=(1.0,),
        s11_db=(-1.0,),
    )
    return PairedEvaluation(
        hardware_hash="hardware",
        state_a_geometry_hash="state-a",
        state_b_geometry_hash="state-b",
        pair_hash=pair_hash(proposal),
        metrics=PairedMetrics(
            state_a=_state_metrics("A"),
            state_b=_state_metrics("B"),
            base_score=score,
            valid_pair_search=False,
            search_score=score,
            worst_reflected_power_fraction=0.9,
        ),
        trajectory=TrajectoryAudit(
            valid=True,
            minimum_clearance_m=None,
            minimum_pitch_m=None,
            minimum_height_m=None,
            maximum_adjacent_node_displacement_m=None,
            state_geometry_hashes=(),
        ),
        state_a_curve=curve,
        state_b_curve=curve,
    )


def _es(seed: int = 101) -> tuple[BCompletionRestartedES, _RecordingDecoder]:
    decoder = _RecordingDecoder()
    return (
        BCompletionRestartedES(
            seed=seed,
            parent_id="p01",
            parents=PARENTS,
            decoder=decoder,
        ),
        decoder,
    )


def test_parent_codes_are_assigned_from_the_b_only_key() -> None:
    assert assign_parent_codes(PARENTS) == {"p01": 1, "p02": 2}
    wrong = (
        BOnlyParentCodeKey(
            parent_id="p01",
            state_b_geometry_hash=P02.state_b_geometry_hash,
            hardware_hash=P01.hardware_hash,
            run_id=SOURCE_RUN_ID,
            step_index=52,
            proposal_index=52,
        ),
        BOnlyParentCodeKey(
            parent_id="p02",
            state_b_geometry_hash=P01.state_b_geometry_hash,
            hardware_hash=P02.hardware_hash,
            run_id=SOURCE_RUN_ID,
            step_index=136,
            proposal_index=136,
        ),
    )
    with pytest.raises(BCompletionAgentError, match="does not yield frozen"):
        assign_parent_codes(wrong)


def test_all_twenty_streams_have_frozen_first_draws() -> None:
    assert len(FIRST_DRAW_HEX) == 20
    for (agent, parent_id, seed), expected in FIRST_DRAW_HEX.items():
        rng = build_stream_rng(
            seed=seed,
            agent=agent,  # type: ignore[arg-type]
            parent_id=parent_id,  # type: ignore[arg-type]
            parents=PARENTS,
        )
        actual = tuple(value.hex() for value in rng.random(2, dtype=np.float64))
        assert actual == expected


def test_random_consumes_one_two_value_draw_per_proposal_only() -> None:
    decoder = _RecordingDecoder()
    proposer = BCompletionRandomProposer(
        seed=101,
        parent_id="p01",
        parents=PARENTS,
        decoder=decoder,
    )
    direct = build_stream_rng(
        seed=101,
        agent=RANDOM_AGENT,
        parent_id="p01",
        parents=PARENTS,
    )
    first = proposer.propose()
    proposer.observe(_evaluation(first, 0.1))
    proposer.propose()
    expected = [
        tuple(float(value) for value in direct.random(2, dtype=np.float64))
        for _ in range(2)
    ]
    assert [raw for raw, _agent in decoder.calls] == expected
    assert all(agent == RANDOM_AGENT for _raw, agent in decoder.calls)


def test_random_and_es_first_rejection_is_fatal() -> None:
    decoder = _RecordingDecoder()
    random = BCompletionRandomProposer(
        seed=101,
        parent_id="p01",
        parents=PARENTS,
        decoder=decoder,
    )
    proposal = random.propose()
    with pytest.raises(BCompletionFatalRejectionError, match="total A-only decoder"):
        random.reject(proposal)

    es, _ = _es()
    proposal = es.propose()
    pending = es.pending_raw
    with pytest.raises(BCompletionFatalRejectionError, match="total A-only decoder"):
        es.reject(proposal)
    assert es.pending_raw == pending


def test_es_cold_draw_and_strict_score_replacement_are_exact() -> None:
    es, decoder = _es()
    direct = build_stream_rng(
        seed=101,
        agent=ES_AGENT,
        parent_id="p01",
        parents=PARENTS,
    )
    expected_first_array = direct.random(2, dtype=np.float64)
    expected_first = tuple(float(value) for value in expected_first_array)
    first = es.propose()
    assert es.pending_raw == expected_first
    es.observe(_evaluation(first, 0.5))
    assert es.parent_raw == expected_first

    expected_second = reflect_normalized(
        expected_first_array + direct.normal(0.0, ES_INITIAL_SIGMA, 2)
    )
    second = es.propose()
    second_raw = es.pending_raw
    assert second_raw == tuple(float(value) for value in expected_second)
    es.observe(_evaluation(second, 0.5))
    assert es.parent_raw == expected_first
    assert es.consecutive_non_improvements == 1

    third = es.propose()
    third_raw = es.pending_raw
    es.observe(_evaluation(third, 0.500_001))
    assert es.parent_raw == third_raw
    assert es.consecutive_non_improvements == 0
    assert all(agent == ES_AGENT for _raw, agent in decoder.calls)


def test_es_adapts_only_after_the_frozen_block() -> None:
    es, _ = _es()
    proposal = es.propose()
    es.observe(_evaluation(proposal, 0.0))
    for index in range(ES_ADAPTATION_BLOCK):
        proposal = es.propose()
        es.observe(_evaluation(proposal, float(index + 1)))
        if index < ES_ADAPTATION_BLOCK - 1:
            assert es.sigma == ES_INITIAL_SIGMA
    assert es.sigma == ES_INITIAL_SIGMA * 1.5

    for _ in range(ES_ADAPTATION_BLOCK):
        proposal = es.propose()
        es.observe(_evaluation(proposal, float(ES_ADAPTATION_BLOCK)))
    assert es.sigma == ES_INITIAL_SIGMA


def test_es_restarts_after_exact_frozen_stagnation() -> None:
    es, _ = _es()
    direct = build_stream_rng(
        seed=101,
        agent=ES_AGENT,
        parent_id="p01",
        parents=PARENTS,
    )
    direct.random(2, dtype=np.float64)
    proposal = es.propose()
    es.observe(_evaluation(proposal, 1.0))
    for index in range(ES_RESTART_STAGNATION):
        direct.normal(0.0, ES_INITIAL_SIGMA, 2)
        proposal = es.propose()
        es.observe(_evaluation(proposal, 1.0))
        assert es.restart_pending == (index == ES_RESTART_STAGNATION - 1)
    expected_restart = tuple(
        float(value) for value in direct.random(2, dtype=np.float64)
    )
    restarted = es.propose()
    assert es.pending_raw == expected_restart
    es.observe(_evaluation(restarted, -1.0))
    assert es.parent_raw == expected_restart
    assert es.sigma == ES_INITIAL_SIGMA
    assert es.consecutive_non_improvements == 0
    assert not es.restart_pending


def test_es_pending_and_matching_evaluation_contract_is_strict() -> None:
    es, _ = _es()
    with pytest.raises(BCompletionAgentError, match="without a pending"):
        es.observe(_evaluation(_RecordingDecoder()((0.5, 0.5), ES_AGENT), 0.0))
    proposal = es.propose()
    with pytest.raises(BCompletionAgentError, match="before pending outcome"):
        es.propose()
    mismatched = _evaluation(proposal, 0.0).model_copy(
        update={"pair_hash": "not-the-pending-pair"}
    )
    with pytest.raises(BCompletionAgentError, match="does not match"):
        es.observe(mismatched)


def test_stream_builder_rejects_nonfrozen_seed_and_bad_parent_set() -> None:
    with pytest.raises(BCompletionAgentError, match="five-seed"):
        build_stream_rng(
            seed=999,
            agent=RANDOM_AGENT,
            parent_id="p01",
            parents=PARENTS,
        )
    with pytest.raises(BCompletionAgentError, match="exactly two"):
        assign_parent_codes((P01,))
    assert FROZEN_SEEDS == (101, 202, 303, 404, 505)
