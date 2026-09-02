"""Parent-return ES used only by the post-freeze R2 study."""

from __future__ import annotations

import math

from yaf_ai.exploration.day65_batch import ES_INITIAL_SIGMA
from yaf_ai.exploration.paired_agents import (
    PairedRestartedES,
    decode_normalized,
    encode_warm_parent,
)
from yaf_ai.exploration.paired_meander import (
    PairedEvaluation,
    PairedMeanderError,
    PairedProposal,
    pair_hash,
)


class R2ParentReturnES(PairedRestartedES):
    """Restart the frozen ES at one immutable parent without consuming RNG."""

    def __init__(
        self,
        seed: int,
        *,
        return_parent: PairedProposal,
        return_parent_search_score: float,
    ) -> None:
        if not math.isfinite(return_parent_search_score):
            raise PairedMeanderError("R2 return-parent score must be finite")
        super().__init__(
            seed,
            warm_parent=return_parent,
            warm_parent_search_score=return_parent_search_score,
        )
        self._return_parent = encode_warm_parent(return_parent)
        self._return_parent_search_score = return_parent_search_score
        self._restart_count = 0

    @property
    def restart_count(self) -> int:
        """Return the number of completed parent-return resets."""

        return self._restart_count

    @property
    def return_parent_pair_hash(self) -> str:
        """Return the immutable parent identity used by every reset."""

        return pair_hash(decode_normalized(self._return_parent.tolist(), "es"))

    def observe(self, evaluation: PairedEvaluation) -> None:
        """Observe one accepted child and replace a scheduled global restart."""

        super().observe(evaluation)
        if self._pending_restart:
            self._return_to_frozen_parent()

    def _return_to_frozen_parent(self) -> None:
        self._parent = self._return_parent.copy()
        self._parent_search_score = self._return_parent_search_score
        self._pending_restart = False
        self._sigma = ES_INITIAL_SIGMA
        self._block_accepted = 0
        self._block_successes = 0
        self._consecutive_non_improvements = 0
        self._restart_count += 1
