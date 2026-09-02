"""Deterministic constrained-random and (1+1) pixel-topology proposers."""

from __future__ import annotations

import numpy as np

from yaf_ai.exploration.environment import (
    AntennaExplorationEnv,
    ExplorationConfig,
    GeometryProposal,
    StepResult,
)
from yaf_ai.exploration.pixel import (
    WIFI24_PIXEL_PROPOSAL_SPACE,
    PixelProposalSpace,
    pixel_geometry,
)


def _proposal(
    space: PixelProposalSpace,
    mask: np.ndarray,
    proposer: str,
    *,
    mutation_k: int,
) -> GeometryProposal:
    geometry, topology = pixel_geometry(space, mask, proposer)
    return GeometryProposal(
        geometry=geometry,
        parameters={
            "metal_fraction": topology.metal_pixels / (space.rows * space.columns),
            "novelty_vs_classic_rectangle": topology.novelty_vs_classic_rectangle,
            "mutation_k": float(mutation_k),
        },
        proposer=proposer,
        topology=topology,
    )


class RandomPixelBaseline:
    """Unbiased frontier growth over valid symmetric feed-connected masks."""

    def __init__(
        self,
        config: ExplorationConfig,
        *,
        space: PixelProposalSpace = WIFI24_PIXEL_PROPOSAL_SPACE,
    ) -> None:
        self.config = config
        self.space = space
        self._rng = np.random.default_rng(config.seed)

    def _orbit(self, row: int, column: int) -> set[tuple[int, int]]:
        orbit = {(row, column)}
        if self.space.symmetry:
            orbit.add((row, self.space.columns - 1 - column))
        return orbit

    def _frontier_orbits(self, mask: np.ndarray) -> list[set[tuple[int, int]]]:
        candidates: dict[tuple[tuple[int, int], ...], set[tuple[int, int]]] = {}
        for row, column in np.argwhere(mask):
            for next_row, next_column in (
                (int(row) - 1, int(column)),
                (int(row) + 1, int(column)),
                (int(row), int(column) - 1),
                (int(row), int(column) + 1),
            ):
                if not (
                    0 <= next_row < self.space.rows
                    and 0 <= next_column < self.space.columns
                ):
                    continue
                orbit = self._orbit(next_row, next_column)
                if any(not bool(mask[cell]) for cell in orbit):
                    key = tuple(sorted(orbit))
                    candidates[key] = orbit
        return list(candidates.values())

    def sample_mask(self) -> np.ndarray:
        """Grow one connected mask, choosing every frontier orbit uniformly."""

        mask = np.zeros((self.space.rows, self.space.columns), dtype=bool)
        for cell in self._orbit(*self.space.feed_cell):
            mask[cell] = True
        minimum = max(int(0.25 * mask.size), int(mask.sum()))
        maximum = int(0.85 * mask.size)
        target = int(self._rng.integers(minimum, maximum + 1))
        while int(mask.sum()) < target:
            frontier = self._frontier_orbits(mask)
            if not frontier:
                break
            selected = frontier[int(self._rng.integers(0, len(frontier)))]
            for cell in selected:
                mask[cell] = True
        self.space.validate_mask(mask)
        return mask

    def propose(self) -> GeometryProposal:
        """Return one deterministic constrained-random proposal."""

        return _proposal(
            self.space,
            self.sample_mask(),
            "random_pixel",
            mutation_k=0,
        )

    async def run(self, environment: AntennaExplorationEnv) -> list[StepResult]:
        results: list[StepResult] = []
        while environment.budget_remaining > 0:
            results.append(await environment.step(self.propose()))
        return results


class EvolvePixelAgent:
    """Seeded (1+1) evolution starting from the classic rectangle mask."""

    def __init__(
        self,
        config: ExplorationConfig,
        *,
        space: PixelProposalSpace = WIFI24_PIXEL_PROPOSAL_SPACE,
    ) -> None:
        self.config = config
        self.space = space
        self._rng = np.random.default_rng(config.seed)
        self._parent = space.classic_mask()
        self._parent_score: float | None = None
        self._pending = self._parent.copy()
        self._mutation_k = 4

    @property
    def mutation_k(self) -> int:
        """Current adaptive number of independent symmetry-orbit flips."""

        return self._mutation_k

    def _mutable_cells(self) -> list[tuple[int, int]]:
        width = (self.space.columns + 1) // 2 if self.space.symmetry else self.space.columns
        feed_orbit = {
            self.space.feed_cell,
            (
                self.space.feed_cell[0],
                self.space.columns - 1 - self.space.feed_cell[1],
            ),
        }
        return [
            (row, column)
            for row in range(self.space.rows)
            for column in range(width)
            if (row, column) not in feed_orbit
        ]

    def _mutated_mask(self) -> np.ndarray:
        cells = self._mutable_cells()
        flips = min(self._mutation_k, len(cells))
        for _ in range(256):
            candidate = self._parent.copy()
            indices = self._rng.choice(len(cells), size=flips, replace=False)
            for raw_index in np.atleast_1d(indices):
                row, column = cells[int(raw_index)]
                candidate[row, column] = not bool(candidate[row, column])
                if self.space.symmetry:
                    mirror = self.space.columns - 1 - column
                    candidate[row, mirror] = candidate[row, column]
            try:
                self.space.validate_mask(candidate)
            except ValueError:
                continue
            return candidate
        return self._parent.copy()

    def propose(self) -> GeometryProposal:
        """Propose the initial rectangle or one valid mutation of the parent."""

        self._pending = (
            self._parent.copy()
            if self._parent_score is None
            else self._mutated_mask()
        )
        return _proposal(
            self.space,
            self._pending,
            "evolve_pixel",
            mutation_k=0 if self._parent_score is None else self._mutation_k,
        )

    def observe(self, score: float) -> None:
        """Accept strict improvements and adapt mutation size deterministically."""

        if self._parent_score is None or score > self._parent_score:
            self._parent = self._pending.copy()
            self._parent_score = score
            self._mutation_k = min(self._mutation_k + 1, 16)
        else:
            self._mutation_k = max(self._mutation_k - 1, 1)

    async def run(self, environment: AntennaExplorationEnv) -> list[StepResult]:
        results: list[StepResult] = []
        while environment.budget_remaining > 0:
            result = await environment.step(self.propose())
            self.observe(result.score)
            results.append(result)
        return results
