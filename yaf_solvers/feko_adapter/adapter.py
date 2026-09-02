"""FEKO MoM/MLFMA/PO/UTD solver adapter (skeleton). Requires Altair FEKO license."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from yaf_core.domain.geometry import Geometry, Mesh
from yaf_core.domain.simulation import SimulationResult, SimulationSpec
from yaf_solvers.base import BaseSolverAdapter


class FEKOAdapter(BaseSolverAdapter):
    """FEKO MoM/MLFMA/PO/UTD solver adapter (skeleton). Requires Altair FEKO license."""

    name = "feko"
    version = "2024.0"
    supports = {"mom", "mlfma", "po", "utd"}

    async def capabilities(self) -> dict[str, Any]:
        caps = await super().capabilities()
        caps.update({"gpu_support": True, "requires_license": True})
        return caps

    async def mesh(self, geometry: Geometry, spec: SimulationSpec) -> Mesh:
        return Mesh(
            geometry_id=geometry.id,
            solver_name=self.name,
            metadata={"status": "skeleton"},
        )

    async def solve(
        self,
        mesh: Mesh,
        spec: SimulationSpec,
        progress_callback: Callable[[float], None] | None = None,
    ) -> SimulationResult:
        return SimulationResult(
            job_id=uuid.uuid4(),
            solver_name=self.name,
            solver_version=self.version,
            status="skeleton_not_implemented",
        )

    def to_native_format(self, geometry: Geometry) -> bytes:
        return b""

    async def from_native_result(self, raw_output: bytes) -> SimulationResult:
        return SimulationResult(
            job_id=uuid.uuid4(),
            solver_name=self.name,
            solver_version=self.version,
            status="success",
        )
