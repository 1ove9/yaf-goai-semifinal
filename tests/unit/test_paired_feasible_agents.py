"""Determinism and island-isolation tests for stratified feasible agents."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from yaf_ai.exploration.day65_batch import ES_INITIAL_SIGMA
from yaf_ai.exploration.paired_feasible_agents import (
    ES_STRATIFIED_AGENT_CODE,
    ES_STRATIFIED_PROPOSER,
    RANDOM_STRATIFIED_AGENT_CODE,
    RANDOM_STRATIFIED_PROPOSER,
    StratifiedRandomProposer,
    StratifiedRestartedES,
    build_stratified_proposer,
)
from yaf_ai.exploration.paired_meander import (
    MANUAL_TURN_COUNTS,
    PairedEvaluation,
    PairedMeanderError,
    PairedProposal,
    pair_hash,
)


def _evaluation(proposal: PairedProposal, score: float) -> PairedEvaluation:
    return cast(
        PairedEvaluation,
        SimpleNamespace(
            pair_hash=pair_hash(proposal),
            metrics=SimpleNamespace(search_score=score),
        ),
    )


def _accept(
    proposer: StratifiedRandomProposer | StratifiedRestartedES,
    score: float,
) -> PairedProposal:
    proposal = proposer.propose()
    proposer.observe(_evaluation(proposal, score))
    return proposal


def test_agent_codes_and_accepted_round_robin_are_frozen() -> None:
    assert RANDOM_STRATIFIED_AGENT_CODE == 1
    assert ES_STRATIFIED_AGENT_CODE == 2

    for proposer in (StratifiedRandomProposer(101), StratifiedRestartedES(101)):
        turns = [_accept(proposer, float(index)).hardware.turn_count for index in range(12)]
        assert turns == [3, 4, 5, 6] * 3
        assert proposer.accepted_count == 12
        assert proposer.current_turn == 3


def test_rejection_retains_stratum_and_does_not_consume_quota() -> None:
    for proposer in (StratifiedRandomProposer(202), StratifiedRestartedES(202)):
        rejected = proposer.propose()
        assert rejected.hardware.turn_count == 3
        proposer.reject(rejected)
        assert proposer.accepted_count == 0
        assert proposer.current_turn == 3
        accepted = _accept(proposer, 1.0)
        assert accepted.hardware.turn_count == 3
        assert proposer.accepted_count == 1
        assert proposer.current_turn == 4


def test_each_turn_rng_is_independent_of_other_turn_rejections() -> None:
    rejected_first = StratifiedRandomProposer(303)
    first = rejected_first.propose()
    rejected_first.reject(first)
    replacement = rejected_first.propose()
    rejected_first.observe(_evaluation(replacement, 0.0))
    turn_four_after_rejection = rejected_first.propose()

    accepted_first = StratifiedRandomProposer(303)
    _accept(accepted_first, 0.0)
    turn_four_without_rejection = accepted_first.propose()

    assert pair_hash(turn_four_after_rejection) == pair_hash(turn_four_without_rejection)


@pytest.mark.parametrize(
    "factory",
    [StratifiedRandomProposer, StratifiedRestartedES],
)
def test_same_seed_replays_and_different_seed_separates(
    factory: type[StratifiedRandomProposer] | type[StratifiedRestartedES],
) -> None:
    def trace(seed: int) -> tuple[str, ...]:
        proposer = factory(seed)
        hashes: list[str] = []
        for index in range(40):
            proposal = proposer.propose()
            hashes.append(pair_hash(proposal))
            if index % 7 == 2:
                proposer.reject(proposal)
            else:
                proposer.observe(_evaluation(proposal, float(index % 5)))
        return tuple(hashes)

    assert trace(404) == trace(404)
    assert trace(404) != trace(505)


def test_pending_contract_rejects_mismatches_and_double_calls() -> None:
    random = StratifiedRandomProposer(101)
    random_pending = random.propose()
    with pytest.raises(PairedMeanderError, match="before pending outcome"):
        random.propose()
    other_random = StratifiedRandomProposer(202).propose()
    with pytest.raises(PairedMeanderError, match="does not match"):
        random.reject(other_random)
    with pytest.raises(PairedMeanderError, match="does not match"):
        random.observe(_evaluation(other_random, 0.0))
    random.reject(random_pending)
    with pytest.raises(PairedMeanderError, match="without a pending"):
        random.observe(_evaluation(random_pending, 0.0))

    es = StratifiedRestartedES(101)
    es_pending = es.propose()
    with pytest.raises(PairedMeanderError, match="before pending outcome"):
        es.propose()
    other_es = StratifiedRestartedES(202).propose()
    with pytest.raises(PairedMeanderError, match="does not match"):
        es.reject(other_es)
    with pytest.raises(PairedMeanderError, match="does not match"):
        es.observe(_evaluation(other_es, 0.0))
    es.reject(es_pending)
    with pytest.raises(PairedMeanderError, match="without a pending"):
        es.observe(_evaluation(es_pending, 0.0))


def test_es_parent_and_adaptation_are_island_local() -> None:
    proposer = StratifiedRestartedES(101)
    for turn in MANUAL_TURN_COUNTS:
        proposal = _accept(proposer, 1.0)
        assert proposal.hardware.turn_count == turn

    original = {
        turn: proposer.parent_pair_hash_for_turn(turn)
        for turn in MANUAL_TURN_COUNTS
    }
    improved_three = _accept(proposer, 2.0)
    assert improved_three.hardware.turn_count == 3
    assert proposer.parent_pair_hash_for_turn(3) == pair_hash(improved_three)
    assert {
        turn: proposer.parent_pair_hash_for_turn(turn)
        for turn in (4, 5, 6)
    } == {turn: original[turn] for turn in (4, 5, 6)}
    assert proposer.sigma_for_turn(3) == ES_INITIAL_SIGMA
    assert proposer.sigma_for_turn(4) == ES_INITIAL_SIGMA


def test_es_restart_is_same_turn_and_deterministically_replayable() -> None:
    first = StratifiedRestartedES(505)
    second = StratifiedRestartedES(505)

    for cycle in range(77):
        for turn in MANUAL_TURN_COUNTS:
            score = 1.0 if cycle == 0 else 0.0
            left = _accept(first, score)
            right = _accept(second, score)
            assert left.hardware.turn_count == turn
            assert pair_hash(left) == pair_hash(right)

    assert first.restart_counts == second.restart_counts
    assert first.restart_counts == {3: 1, 4: 1, 5: 1, 6: 1}
    assert {
        turn: first.parent_pair_hash_for_turn(turn)
        for turn in MANUAL_TURN_COUNTS
    } == {
        turn: second.parent_pair_hash_for_turn(turn)
        for turn in MANUAL_TURN_COUNTS
    }


def test_unknown_turn_introspection_is_rejected() -> None:
    proposer = StratifiedRestartedES(101)
    with pytest.raises(PairedMeanderError, match="outside the stratified islands"):
        proposer.sigma_for_turn(7)


def test_terminal_diagnostics_are_replay_stable() -> None:
    left = StratifiedRestartedES(303)
    right = StratifiedRestartedES(303)
    for index in range(24):
        left_proposal = left.propose()
        right_proposal = right.propose()
        assert left_proposal == right_proposal
        if index in {4, 13, 22}:
            left.reject(left_proposal)
            right.reject(right_proposal)
        else:
            score = float(index % 7)
            left.observe(_evaluation(left_proposal, score))
            right.observe(_evaluation(right_proposal, score))
    assert left.diagnostics == right.diagnostics
    assert left.diagnostics.accepted_count == 21
    assert tuple(item.turn_count for item in left.diagnostics.islands) == (3, 4, 5, 6)
    assert tuple(item.accepted_count for item in left.diagnostics.islands) == (6, 5, 5, 5)


def test_factory_and_random_diagnostics_are_frozen() -> None:
    random = build_stratified_proposer(RANDOM_STRATIFIED_PROPOSER, 101)
    es = build_stratified_proposer(ES_STRATIFIED_PROPOSER, 101)
    assert isinstance(random, StratifiedRandomProposer)
    assert isinstance(es, StratifiedRestartedES)
    for index in range(5):
        _accept(random, float(index))
    assert random.diagnostics.accepted_count == 5
    assert tuple(item.accepted_count for item in random.diagnostics.islands) == (2, 1, 1, 1)
    assert all(item.restart_count == 0 for item in random.diagnostics.islands)
    assert all(item.parent_pair_hash is None for item in random.diagnostics.islands)
    with pytest.raises(PairedMeanderError, match="unknown stratified agent"):
        build_stratified_proposer("unknown", 101)  # type: ignore[arg-type]
