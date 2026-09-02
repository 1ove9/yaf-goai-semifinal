"""Isolated deterministic agents for the B-parent A-only completion study."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
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
from yaf_ai.exploration.paired_meander import (
    PairedEvaluation,
    PairedMeanderError,
    PairedProposal,
    pair_hash,
)

RAW_DIMENSIONS = 2
FROZEN_SEEDS = (101, 202, 303, 404, 505)
RNG_VERSION = "numpy-pcg64-seedsequence-v1"
STREAM_FORMAT_VERSION = "canonical-json-float-hex-lf-v1"
RNG_STREAM_REVISION = 1
RANDOM_AGENT: Literal["random-b-completion"] = "random-b-completion"
ES_AGENT: Literal["es-b-completion"] = "es-b-completion"
RANDOM_AGENT_CODE = 3
ES_AGENT_CODE = 4

AgentName = Literal["random-b-completion", "es-b-completion"]
ParentId = Literal["p01", "p02"]
RawVector: TypeAlias = tuple[float, float]
# The coordinate layer binds one frozen parent in a closure matching this API.
# Agents remain isolated from its implementation and receive only decoded proposals.
ProposalDecoder: TypeAlias = Callable[[RawVector, AgentName], PairedProposal]

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_FROZEN_PARENT_CODES: dict[ParentId, int] = {"p01": 1, "p02": 2}


class BCompletionAgentError(PairedMeanderError):
    """Raised when a frozen B-completion agent invariant is violated."""


class BCompletionFatalRejectionError(BCompletionAgentError):
    """Raised on the first proposal rejection; retry is not permitted."""


@dataclass(frozen=True)
class BOnlyParentCodeKey:
    """The complete B-only ordering key plus source-address tie breakers."""

    parent_id: ParentId
    state_b_geometry_hash: str
    hardware_hash: str
    run_id: str
    step_index: int
    proposal_index: int

    def validate(self) -> None:
        """Reject malformed provenance before it can influence an RNG stream."""

        for label, value in (
            ("state-B geometry hash", self.state_b_geometry_hash),
            ("hardware hash", self.hardware_hash),
        ):
            if _SHA256_PATTERN.fullmatch(value) is None:
                raise BCompletionAgentError(f"{label} must be lowercase SHA-256")
        if not self.run_id:
            raise BCompletionAgentError("parent source run_id must not be empty")
        if self.step_index < 0 or self.proposal_index < 0:
            raise BCompletionAgentError("parent source indices must be non-negative")

    @property
    def ordering_key(self) -> tuple[str, str, str, int, int]:
        """Return the preregistered B-only key used for numeric parent codes."""

        return (
            self.state_b_geometry_hash,
            self.hardware_hash,
            self.run_id,
            self.step_index,
            self.proposal_index,
        )


def assign_parent_codes(
    parents: Sequence[BOnlyParentCodeKey],
) -> dict[ParentId, int]:
    """Assign numeric parent codes solely from the frozen B-only ordering key."""

    if len(parents) != 2:
        raise BCompletionAgentError("exactly two B parents are required")
    for parent in parents:
        parent.validate()
    parent_ids = [parent.parent_id for parent in parents]
    if set(parent_ids) != {"p01", "p02"} or len(set(parent_ids)) != 2:
        raise BCompletionAgentError("B parents must have unique p01/p02 identities")
    ordering_keys = [parent.ordering_key for parent in parents]
    if len(set(ordering_keys)) != 2:
        raise BCompletionAgentError("B-only parent ordering keys must be unique")
    ordered = sorted(parents, key=lambda parent: parent.ordering_key)
    assigned = {
        parent.parent_id: index + 1 for index, parent in enumerate(ordered)
    }
    if assigned != _FROZEN_PARENT_CODES:
        raise BCompletionAgentError(
            "B-only parent ordering does not yield frozen p01=1/p02=2 codes"
        )
    return assigned


def _validate_seed(seed: int) -> None:
    if seed not in FROZEN_SEEDS:
        raise BCompletionAgentError("seed is outside the frozen five-seed matrix")


def _agent_code(agent: AgentName) -> int:
    if agent == RANDOM_AGENT:
        return RANDOM_AGENT_CODE
    if agent == ES_AGENT:
        return ES_AGENT_CODE
    raise BCompletionAgentError("unknown B-completion agent")


def build_stream_rng(
    *,
    seed: int,
    agent: AgentName,
    parent_id: ParentId,
    parents: Sequence[BOnlyParentCodeKey],
) -> np.random.Generator:
    """Build the sole four-slot PCG64 stream admitted by the preregistration."""

    _validate_seed(seed)
    codes = assign_parent_codes(parents)
    return np.random.Generator(
        np.random.PCG64(
            np.random.SeedSequence(
                [seed, _agent_code(agent), codes[parent_id], RNG_STREAM_REVISION]
            )
        )
    )


def _raw_tuple(values: NDArray[np.float64]) -> RawVector:
    if values.shape != (RAW_DIMENSIONS,):
        raise BCompletionAgentError("B-completion raw vector must have two dimensions")
    if not bool(np.all(np.isfinite(values))) or bool(np.any(values < 0.0)) or bool(
        np.any(values > 1.0)
    ):
        raise BCompletionAgentError(
            "B-completion normalized coordinates must be finite in [0,1]"
        )
    return (float(values[0]), float(values[1]))


class BCompletionRandomProposer:
    """Uniform A-only proposer with exactly one two-value draw per proposal."""

    def __init__(
        self,
        *,
        seed: int,
        parent_id: ParentId,
        parents: Sequence[BOnlyParentCodeKey],
        decoder: ProposalDecoder,
    ) -> None:
        self._rng = build_stream_rng(
            seed=seed,
            agent=RANDOM_AGENT,
            parent_id=parent_id,
            parents=parents,
        )
        self._decoder = decoder

    def propose(self) -> PairedProposal:
        raw = self._rng.random(RAW_DIMENSIONS, dtype=np.float64)
        return self._decoder(_raw_tuple(raw), RANDOM_AGENT)

    def observe(self, _evaluation: PairedEvaluation) -> None:
        return

    def reject(self, _proposal: PairedProposal) -> None:
        raise BCompletionFatalRejectionError(
            "the total A-only decoder produced a rejected proposal"
        )


class BCompletionRestartedES:
    """Cold single-island restarted (1+1)-ES over the frozen two coordinates."""

    def __init__(
        self,
        *,
        seed: int,
        parent_id: ParentId,
        parents: Sequence[BOnlyParentCodeKey],
        decoder: ProposalDecoder,
    ) -> None:
        self._rng = build_stream_rng(
            seed=seed,
            agent=ES_AGENT,
            parent_id=parent_id,
            parents=parents,
        )
        self._decoder = decoder
        self._parent_raw: NDArray[np.float64] | None = None
        self._parent_proposal: PairedProposal | None = None
        self._parent_search_score: float | None = None
        self._pending_raw: NDArray[np.float64] | None = None
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
    def parent_raw(self) -> RawVector | None:
        if self._parent_raw is None:
            return None
        return _raw_tuple(self._parent_raw)

    @property
    def pending_raw(self) -> RawVector | None:
        if self._pending_raw is None:
            return None
        return _raw_tuple(self._pending_raw)

    @property
    def parent_pair_hash(self) -> str | None:
        if self._parent_proposal is None:
            return None
        return pair_hash(self._parent_proposal)

    def _draw(self) -> NDArray[np.float64]:
        if self._parent_raw is None or self._pending_restart:
            return self._rng.random(RAW_DIMENSIONS, dtype=np.float64)
        return reflect_normalized(
            self._parent_raw
            + self._rng.normal(0.0, self._sigma, RAW_DIMENSIONS)
        )

    def propose(self) -> PairedProposal:
        if self._pending_raw is not None:
            raise BCompletionAgentError("ES propose called before pending outcome")
        self._pending_raw = self._draw()
        self._pending_proposal = self._decoder(
            _raw_tuple(self._pending_raw), ES_AGENT
        )
        return self._pending_proposal

    def observe(self, evaluation: PairedEvaluation) -> None:
        if self._pending_raw is None or self._pending_proposal is None:
            raise BCompletionAgentError("ES observe called without a pending proposal")
        if pair_hash(self._pending_proposal) != evaluation.pair_hash:
            raise BCompletionAgentError("ES evaluation does not match pending proposal")
        score = evaluation.metrics.search_score
        pending_raw = self._pending_raw.copy()
        pending_proposal = self._pending_proposal
        self._pending_raw = None
        self._pending_proposal = None
        if self._parent_raw is None or self._pending_restart:
            self._parent_raw = pending_raw
            self._parent_proposal = pending_proposal
            self._parent_search_score = score
            self._pending_restart = False
            self._sigma = ES_INITIAL_SIGMA
            self._block_accepted = 0
            self._block_successes = 0
            self._consecutive_non_improvements = 0
            return
        if self._parent_search_score is None:
            raise BCompletionAgentError("ES parent search score is missing")
        success = score > self._parent_search_score
        if success:
            self._parent_raw = pending_raw
            self._parent_proposal = pending_proposal
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

    def reject(self, _proposal: PairedProposal) -> None:
        raise BCompletionFatalRejectionError(
            "the total A-only decoder produced a rejected proposal"
        )
