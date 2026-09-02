"""Deterministic seven-dimensional proposers for paired-state exploration."""

from __future__ import annotations

import math
from collections.abc import Sequence

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
from yaf_ai.exploration.paired_meander import (
    MANUAL_TURN_COUNTS,
    HardwareSpec,
    PairedEvaluation,
    PairedMeanderError,
    PairedProposal,
    StateControl,
    pair_hash,
)

VECTOR_DIMENSIONS = 7
FEED_GAP_BOUNDS = (20_000, 60_000)
TERMINAL_BOUNDS = (0, 1_000_000)
STATE_A_LENGTH_BOUNDS = (50_000, 100_000)
STATE_B_LENGTH_BOUNDS = (22_000, 45_000)
SPAN_BOUNDS = (760_000, 1_000_000)


def _normalized(values: Sequence[float]) -> NDArray[np.float64]:
    array = np.asarray(values, dtype=np.float64)
    if array.shape != (VECTOR_DIMENSIONS,):
        raise PairedMeanderError("paired proposal vector must have seven dimensions")
    if not bool(np.all(np.isfinite(array))) or bool(np.any(array < 0.0)) or bool(
        np.any(array > 1.0)
    ):
        raise PairedMeanderError("paired normalized coordinates must be finite in [0,1]")
    return array


def _half_up_map(value: float, bounds: tuple[int, int]) -> int:
    lower, upper = bounds
    mapped = lower + value * (upper - lower)
    quantized = math.floor(mapped + 0.5)
    return min(upper, max(lower, quantized))


def decode_normalized(
    values: Sequence[float],
    proposer: str,
) -> PairedProposal:
    """Decode, half-up quantize, then construct the frozen paired proposal."""

    vector = _normalized(values)
    turn_index = min(3, math.floor(float(vector[0]) * 4.0))
    hardware = HardwareSpec(
        turn_count=MANUAL_TURN_COUNTS[turn_index],
        feed_gap_ratio_ppm=_half_up_map(float(vector[1]), FEED_GAP_BOUNDS),
        terminal_ratio_ppm=_half_up_map(float(vector[2]), TERMINAL_BOUNDS),
    )
    return PairedProposal(
        hardware=hardware,
        state_a=StateControl(
            state="A",
            total_wire_length_um=_half_up_map(
                float(vector[3]), STATE_A_LENGTH_BOUNDS
            ),
            span_ratio_ppm=_half_up_map(float(vector[4]), SPAN_BOUNDS),
        ),
        state_b=StateControl(
            state="B",
            total_wire_length_um=_half_up_map(
                float(vector[5]), STATE_B_LENGTH_BOUNDS
            ),
            span_ratio_ppm=_half_up_map(float(vector[6]), SPAN_BOUNDS),
        ),
        proposer=proposer,
    )


def _inverse(value: int, bounds: tuple[int, int]) -> float:
    lower, upper = bounds
    if not lower <= value <= upper:
        raise PairedMeanderError("warm-parent field lies outside frozen bounds")
    return (value - lower) / (upper - lower)


def encode_warm_parent(proposal: PairedProposal) -> NDArray[np.float64]:
    """Encode a quantized committed parent using the frozen inverse map."""

    try:
        turn_index = MANUAL_TURN_COUNTS.index(proposal.hardware.turn_count)
    except ValueError as error:
        raise PairedMeanderError("warm parent turn count is outside the frozen bins") from error
    return np.asarray(
        (
            (turn_index + 0.5) / 4.0,
            _inverse(proposal.hardware.feed_gap_ratio_ppm, FEED_GAP_BOUNDS),
            _inverse(proposal.hardware.terminal_ratio_ppm, TERMINAL_BOUNDS),
            _inverse(
                proposal.state_a.total_wire_length_um,
                STATE_A_LENGTH_BOUNDS,
            ),
            _inverse(proposal.state_a.span_ratio_ppm, SPAN_BOUNDS),
            _inverse(
                proposal.state_b.total_wire_length_um,
                STATE_B_LENGTH_BOUNDS,
            ),
            _inverse(proposal.state_b.span_ratio_ppm, SPAN_BOUNDS),
        ),
        dtype=np.float64,
    )


class PairedRandomProposer:
    """Independent uniform draws with deterministic rejection advancement."""

    def __init__(self, seed: int) -> None:
        self._rng = np.random.default_rng(seed)

    def propose(self) -> PairedProposal:
        return decode_normalized(self._rng.random(VECTOR_DIMENSIONS).tolist(), "random")

    def observe(self, _evaluation: PairedEvaluation) -> None:
        return

    def reject(self, _proposal: PairedProposal) -> None:
        return


class PairedRestartedES:
    """Frozen restarted (1+1)-ES over the paired seven-dimensional vector."""

    def __init__(
        self,
        seed: int,
        *,
        warm_parent: PairedProposal | None = None,
        warm_parent_search_score: float | None = None,
    ) -> None:
        if (warm_parent is None) != (warm_parent_search_score is None):
            raise PairedMeanderError("warm parent and score must be supplied together")
        self._rng = np.random.default_rng(seed)
        self._parent = (
            None if warm_parent is None else encode_warm_parent(warm_parent)
        )
        self._parent_search_score = warm_parent_search_score
        self._pending: NDArray[np.float64] | None = None
        self._pending_proposal: PairedProposal | None = None
        self._pending_restart = False
        self._sigma = ES_INITIAL_SIGMA
        self._block_accepted = 0
        self._block_successes = 0
        self._consecutive_non_improvements = 0

    @property
    def sigma(self) -> float:
        return self._sigma

    @property
    def consecutive_non_improvements(self) -> int:
        return self._consecutive_non_improvements

    @property
    def restart_pending(self) -> bool:
        return self._pending_restart

    @property
    def parent_pair_hash(self) -> str | None:
        if self._parent is None:
            return None
        return pair_hash(decode_normalized(self._parent.tolist(), "es"))

    def _draw(self) -> NDArray[np.float64]:
        if self._parent is None or self._pending_restart:
            return self._rng.random(VECTOR_DIMENSIONS)
        return reflect_normalized(
            self._parent
            + self._rng.normal(0.0, self._sigma, VECTOR_DIMENSIONS)
        )

    def propose(self) -> PairedProposal:
        if self._pending is not None:
            raise PairedMeanderError("ES propose called before pending outcome")
        self._pending = self._draw()
        self._pending_proposal = decode_normalized(self._pending.tolist(), "es")
        return self._pending_proposal

    def reject(self, proposal: PairedProposal) -> None:
        if self._pending_proposal is None or proposal != self._pending_proposal:
            raise PairedMeanderError("ES rejection does not match pending proposal")
        self._pending = None
        self._pending_proposal = None

    def observe(self, evaluation: PairedEvaluation) -> None:
        if self._pending is None or self._pending_proposal is None:
            raise PairedMeanderError("ES observe called without a pending proposal")
        if pair_hash(self._pending_proposal) != evaluation.pair_hash:
            raise PairedMeanderError("ES evaluation does not match pending proposal")
        score = evaluation.metrics.search_score
        pending = self._pending.copy()
        self._pending = None
        self._pending_proposal = None
        if self._parent is None or self._pending_restart:
            self._parent = pending
            self._parent_search_score = score
            self._pending_restart = False
            self._sigma = ES_INITIAL_SIGMA
            self._block_accepted = 0
            self._block_successes = 0
            self._consecutive_non_improvements = 0
            return
        if self._parent_search_score is None:
            raise PairedMeanderError("ES parent search score is missing")
        success = score > self._parent_search_score
        if success:
            self._parent = pending
            self._parent_search_score = score
            self._block_successes += 1
            self._consecutive_non_improvements = 0
        else:
            self._consecutive_non_improvements += 1
        self._block_accepted += 1
        if self._block_accepted == ES_ADAPTATION_BLOCK:
            success_fraction = self._block_successes / ES_ADAPTATION_BLOCK
            if success_fraction > ES_SUCCESS_TARGET:
                self._sigma = min(
                    ES_MAX_SIGMA,
                    self._sigma * ES_SIGMA_FACTOR,
                )
            else:
                self._sigma = max(
                    ES_MIN_SIGMA,
                    self._sigma / ES_SIGMA_FACTOR,
                )
            self._block_accepted = 0
            self._block_successes = 0
        if self._consecutive_non_improvements >= ES_RESTART_STAGNATION:
            self._pending_restart = True
