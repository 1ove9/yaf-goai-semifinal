"""Deterministic turn-stratified proposers for the feasibility study."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

import numpy as np
from numpy.typing import NDArray

from yaf_ai.exploration.day65_batch import (
    ES_ADAPTATION_BLOCK,
    ES_INITIAL_SIGMA,
    ES_MAX_SIGMA,
    ES_MIN_SIGMA,
    ES_RESTART_STAGNATION,
    ES_SIGMA_FACTOR,
    ES_SUCCESS_TARGET,
    reflect_normalized,
)
from yaf_ai.exploration.paired_feasible_coordinates import (
    decode_feasible_normalized,
)
from yaf_ai.exploration.paired_meander import (
    MANUAL_TURN_COUNTS,
    PairedEvaluation,
    PairedMeanderError,
    PairedProposal,
    pair_hash,
)

FEASIBLE_VECTOR_DIMENSIONS = 6
RANDOM_STRATIFIED_AGENT_CODE = 1
ES_STRATIFIED_AGENT_CODE = 2
RANDOM_STRATIFIED_PROPOSER: Literal["random-stratified-v1"] = (
    "random-stratified-v1"
)
ES_STRATIFIED_PROPOSER: Literal["es-stratified-v1"] = "es-stratified-v1"

StratifiedAgentName = Literal["random-stratified-v1", "es-stratified-v1"]


@dataclass(frozen=True)
class StratifiedIslandDiagnostics:
    """Replay-comparable terminal state for one fixed-turn island."""

    turn_count: int
    accepted_count: int
    restart_count: int
    parent_pair_hash: str | None
    sigma: float | None
    consecutive_non_improvements: int | None


@dataclass(frozen=True)
class StratifiedAgentDiagnostics:
    """Replay-comparable state for the complete four-island proposer."""

    agent: StratifiedAgentName
    accepted_count: int
    islands: tuple[StratifiedIslandDiagnostics, ...]


def _accepted_for_turn(total: int, turn_count: int) -> int:
    quotient, remainder = divmod(total, len(MANUAL_TURN_COUNTS))
    return quotient + int(MANUAL_TURN_COUNTS.index(turn_count) < remainder)


def _island_rng(seed: int, agent_code: int, turn_count: int) -> np.random.Generator:
    sequence = np.random.SeedSequence([seed, agent_code, turn_count, 1])
    return np.random.Generator(np.random.PCG64(sequence))


def _evaluation_matches(proposal: PairedProposal, evaluation: PairedEvaluation) -> bool:
    return pair_hash(proposal) == evaluation.pair_hash


class StratifiedRandomProposer:
    """Uniform feasible-coordinate draws under a fixed accepted-turn schedule."""

    agent_code = RANDOM_STRATIFIED_AGENT_CODE

    def __init__(self, seed: int) -> None:
        self._rngs = {
            turn: _island_rng(seed, self.agent_code, turn)
            for turn in MANUAL_TURN_COUNTS
        }
        self._accepted_count = 0
        self._pending_proposal: PairedProposal | None = None

    @property
    def accepted_count(self) -> int:
        return self._accepted_count

    @property
    def current_turn(self) -> int:
        return MANUAL_TURN_COUNTS[
            self._accepted_count % len(MANUAL_TURN_COUNTS)
        ]

    @property
    def diagnostics(self) -> StratifiedAgentDiagnostics:
        """Return the deterministic state reconstructed from accepted events."""

        return StratifiedAgentDiagnostics(
            agent=RANDOM_STRATIFIED_PROPOSER,
            accepted_count=self._accepted_count,
            islands=tuple(
                StratifiedIslandDiagnostics(
                    turn_count=turn,
                    accepted_count=_accepted_for_turn(self._accepted_count, turn),
                    restart_count=0,
                    parent_pair_hash=None,
                    sigma=None,
                    consecutive_non_improvements=None,
                )
                for turn in MANUAL_TURN_COUNTS
            ),
        )

    def propose(self) -> PairedProposal:
        if self._pending_proposal is not None:
            raise PairedMeanderError("stratified Random propose called before pending outcome")
        turn = self.current_turn
        values = self._rngs[turn].random(FEASIBLE_VECTOR_DIMENSIONS)
        proposal = decode_feasible_normalized(
            turn,
            values.tolist(),
            RANDOM_STRATIFIED_PROPOSER,
        )
        self._pending_proposal = proposal
        return proposal

    def reject(self, proposal: PairedProposal) -> None:
        if self._pending_proposal is None or proposal != self._pending_proposal:
            raise PairedMeanderError("stratified Random rejection does not match pending proposal")
        self._pending_proposal = None

    def observe(self, evaluation: PairedEvaluation) -> None:
        if self._pending_proposal is None:
            raise PairedMeanderError("stratified Random observe called without a pending proposal")
        if not _evaluation_matches(self._pending_proposal, evaluation):
            raise PairedMeanderError("stratified Random evaluation does not match pending proposal")
        self._pending_proposal = None
        self._accepted_count += 1


@dataclass
class _ESIsland:
    rng: np.random.Generator
    parent: NDArray[np.float64] | None = None
    parent_search_score: float | None = None
    sigma: float = ES_INITIAL_SIGMA
    block_accepted: int = 0
    block_successes: int = 0
    consecutive_non_improvements: int = 0
    pending_restart: bool = False
    restart_count: int = 0


class StratifiedRestartedES:
    """Four independent cold restarted ES islands with accepted round-robin."""

    agent_code = ES_STRATIFIED_AGENT_CODE

    def __init__(self, seed: int) -> None:
        self._islands = {
            turn: _ESIsland(_island_rng(seed, self.agent_code, turn))
            for turn in MANUAL_TURN_COUNTS
        }
        self._accepted_count = 0
        self._pending_vector: NDArray[np.float64] | None = None
        self._pending_proposal: PairedProposal | None = None
        self._pending_turn: int | None = None

    @property
    def accepted_count(self) -> int:
        return self._accepted_count

    @property
    def current_turn(self) -> int:
        return MANUAL_TURN_COUNTS[
            self._accepted_count % len(MANUAL_TURN_COUNTS)
        ]

    @property
    def restart_counts(self) -> dict[int, int]:
        return {
            turn: self._islands[turn].restart_count
            for turn in MANUAL_TURN_COUNTS
        }

    @property
    def diagnostics(self) -> StratifiedAgentDiagnostics:
        """Return all four isolated ES states for independent replay checks."""

        return StratifiedAgentDiagnostics(
            agent=ES_STRATIFIED_PROPOSER,
            accepted_count=self._accepted_count,
            islands=tuple(
                StratifiedIslandDiagnostics(
                    turn_count=turn,
                    accepted_count=_accepted_for_turn(self._accepted_count, turn),
                    restart_count=self._islands[turn].restart_count,
                    parent_pair_hash=self.parent_pair_hash_for_turn(turn),
                    sigma=self._islands[turn].sigma,
                    consecutive_non_improvements=(
                        self._islands[turn].consecutive_non_improvements
                    ),
                )
                for turn in MANUAL_TURN_COUNTS
            ),
        )

    def sigma_for_turn(self, turn_count: int) -> float:
        return self._island(turn_count).sigma

    def parent_pair_hash_for_turn(self, turn_count: int) -> str | None:
        island = self._island(turn_count)
        if island.parent is None:
            return None
        return pair_hash(
            decode_feasible_normalized(
                turn_count,
                island.parent.tolist(),
                ES_STRATIFIED_PROPOSER,
            )
        )

    def _island(self, turn_count: int) -> _ESIsland:
        try:
            return self._islands[turn_count]
        except KeyError as error:
            raise PairedMeanderError("turn count is outside the stratified islands") from error

    def _draw(self, island: _ESIsland) -> NDArray[np.float64]:
        if island.parent is None or island.pending_restart:
            return island.rng.random(FEASIBLE_VECTOR_DIMENSIONS)
        return reflect_normalized(
            island.parent
            + island.rng.normal(0.0, island.sigma, FEASIBLE_VECTOR_DIMENSIONS)
        )

    def propose(self) -> PairedProposal:
        if self._pending_proposal is not None:
            raise PairedMeanderError("stratified ES propose called before pending outcome")
        turn = self.current_turn
        vector = self._draw(self._islands[turn])
        proposal = decode_feasible_normalized(
            turn,
            vector.tolist(),
            ES_STRATIFIED_PROPOSER,
        )
        self._pending_vector = vector
        self._pending_proposal = proposal
        self._pending_turn = turn
        return proposal

    def reject(self, proposal: PairedProposal) -> None:
        if self._pending_proposal is None or proposal != self._pending_proposal:
            raise PairedMeanderError("stratified ES rejection does not match pending proposal")
        self._clear_pending()

    def observe(self, evaluation: PairedEvaluation) -> None:
        if (
            self._pending_vector is None
            or self._pending_proposal is None
            or self._pending_turn is None
        ):
            raise PairedMeanderError("stratified ES observe called without a pending proposal")
        if not _evaluation_matches(self._pending_proposal, evaluation):
            raise PairedMeanderError("stratified ES evaluation does not match pending proposal")

        turn = self._pending_turn
        pending = self._pending_vector.copy()
        island = self._islands[turn]
        score = evaluation.metrics.search_score
        self._clear_pending()

        if island.parent is None or island.pending_restart:
            island.parent = pending
            island.parent_search_score = score
            island.sigma = ES_INITIAL_SIGMA
            island.block_accepted = 0
            island.block_successes = 0
            island.consecutive_non_improvements = 0
            if island.pending_restart:
                island.restart_count += 1
            island.pending_restart = False
        else:
            if island.parent_search_score is None:
                raise PairedMeanderError("stratified ES parent score is missing")
            success = score > island.parent_search_score
            if success:
                island.parent = pending
                island.parent_search_score = score
                island.block_successes += 1
                island.consecutive_non_improvements = 0
            else:
                island.consecutive_non_improvements += 1
            island.block_accepted += 1
            if island.block_accepted == ES_ADAPTATION_BLOCK:
                success_fraction = island.block_successes / ES_ADAPTATION_BLOCK
                if success_fraction > ES_SUCCESS_TARGET:
                    island.sigma = min(ES_MAX_SIGMA, island.sigma * ES_SIGMA_FACTOR)
                else:
                    island.sigma = max(ES_MIN_SIGMA, island.sigma / ES_SIGMA_FACTOR)
                island.block_accepted = 0
                island.block_successes = 0
            if island.consecutive_non_improvements >= ES_RESTART_STAGNATION:
                island.pending_restart = True

        self._accepted_count += 1

    def _clear_pending(self) -> None:
        self._pending_vector = None
        self._pending_proposal = None
        self._pending_turn = None


StratifiedProposer: TypeAlias = StratifiedRandomProposer | StratifiedRestartedES


def build_stratified_proposer(
    agent: StratifiedAgentName,
    seed: int,
) -> StratifiedProposer:
    """Build one frozen stratified proposer from its config identity."""

    if agent == RANDOM_STRATIFIED_PROPOSER:
        return StratifiedRandomProposer(seed)
    if agent == ES_STRATIFIED_PROPOSER:
        return StratifiedRestartedES(seed)
    raise PairedMeanderError(f"unknown stratified agent: {agent}")
