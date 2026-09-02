"""
Solver adapter base class — provides common infrastructure for solver adapters.

All concrete solver adapters inherit from BaseSolverAdapter, which
implements the SolverAdapter Protocol with shared logic for:
- Error handling
- Progress reporting
- Logging
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from yaf_core.domain.geometry import Geometry, Mesh
from yaf_core.domain.simulation import SimulationResult, SimulationSpec

#: Warning attached to every result produced by an analytical fallback path.
FALLBACK_WARNING = (
    "This result was produced by a closed-form analytical fallback, NOT a real "
    "electromagnetic solver. It only demonstrates that the pipeline runs; do not "
    "use it for engineering decisions. Install the solver (see docs/next-steps.md) "
    "or set YAF_NO_FALLBACK=1 to turn silent degradation into a hard error."
)


class YAFError(Exception):
    """Base exception for all YAF errors."""
    pass


class SolverError(YAFError):
    """Solver execution failure."""
    def __init__(self, solver: str, job_id: str, message: str) -> None:
        super().__init__(f"[{solver}] Job {job_id}: {message}")
        self.solver = solver
        self.job_id = job_id


class SolverUnavailableError(SolverError):
    """Raised when a real solver is unavailable and fallback is disabled.

    Triggered by ``YAF_NO_FALLBACK=1`` — recommended in CI so that a missing
    solver binary cannot silently turn physics into closed-form approximation.
    """
    def __init__(self, solver: str, job_id: str, reason: str) -> None:
        super().__init__(
            solver,
            job_id,
            f"real solver unavailable ({reason}) and YAF_NO_FALLBACK is set — "
            "refusing to return analytical-fallback results",
        )


class MeshError(YAFError):
    """Mesh generation failure."""
    pass


class GeometryError(YAFError):
    """Geometry validation or conversion failure."""
    pass


class BaseSolverAdapter(ABC):
    """Abstract base for all solver adapters.

    Subclasses must implement:
    - mesh()
    - solve()
    - to_native_format()
    - from_native_result()
    """

    name: str = "base"
    version: str = "0.1.0"
    supports: set[str] = set()

    def __init__(self) -> None:
        self._running_jobs: dict[str, asyncio.Task[Any]] = {}

    async def capabilities(self) -> dict[str, Any]:
        """Return solver capabilities metadata."""
        return {
            "name": self.name,
            "version": self.version,
            "methods": sorted(self.supports),
            "frequency_range": [1e6, 100e9],
            "max_cells": 1e7,
            "gpu_support": False,
        }

    @abstractmethod
    async def mesh(self, geometry: Geometry, spec: SimulationSpec) -> Mesh:
        ...

    @abstractmethod
    async def solve(
        self,
        mesh: Mesh,
        spec: SimulationSpec,
        progress_callback: Callable[[float], Any] | None = None,
    ) -> SimulationResult:
        ...

    @abstractmethod
    def to_native_format(self, geometry: Geometry) -> bytes:
        ...

    @abstractmethod
    async def from_native_result(self, raw_output: bytes) -> SimulationResult:
        ...

    @staticmethod
    def fallback_allowed() -> bool:
        """Whether analytical fallback is permitted (YAF_NO_FALLBACK unset)."""
        return os.environ.get("YAF_NO_FALLBACK", "").strip().lower() not in {
            "1", "true", "yes", "on",
        }

    def _require_fallback_allowed(self, job_id: str, reason: str) -> None:
        """Raise SolverUnavailableError if strict mode forbids fallback."""
        if not self.fallback_allowed():
            raise SolverUnavailableError(self.name, job_id, reason)

    @staticmethod
    def _mark_solver_mode(result: SimulationResult, mode: str) -> SimulationResult:
        """Label a result with how it was produced.

        ``mode`` is one of ``"native"`` (in-process solver bindings),
        ``"subprocess"`` (external solver binary), or ``"fallback_analytical"``
        (closed-form approximation — carries an explicit warning).
        """
        result.solver_metadata["solver_mode"] = mode
        if mode == "fallback_analytical":
            result.solver_metadata["warning"] = FALLBACK_WARNING
        return result

    async def cancel(self, job_id: str) -> None:
        """Cancel a running job."""
        if job_id in self._running_jobs:
            self._running_jobs[job_id].cancel()
            del self._running_jobs[job_id]

    async def health_check(self) -> bool:
        """Check solver executable availability."""
        return True

    async def close(self) -> None:
        """Release resources."""
        for job_id in list(self._running_jobs):
            await self.cancel(job_id)
