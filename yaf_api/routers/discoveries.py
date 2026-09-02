"""REST API for requirement-driven antenna discovery runs."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from yaf_ai.inverse_design.discovery import AntennaDiscoveryEngine
from yaf_core.domain.discovery import (
    AntennaCandidate,
    AntennaTopology,
    DiscoveryRequirements,
    DiscoveryRun,
    DiscoveryState,
)

router = APIRouter(prefix="/api/v1/discoveries", tags=["discoveries"])

_runs: dict[uuid.UUID, DiscoveryRun] = {}
_tasks: dict[uuid.UUID, asyncio.Task[None]] = {}


class DiscoveryRequest(BaseModel):
    """Human-scale API request; converted to SI units at the boundary."""

    name: str = "discovered_antenna"
    center_frequency_ghz: float = Field(gt=0.001, le=100.0)
    bandwidth_mhz: float = Field(gt=0.0, le=50_000.0)
    target_gain_dbi: float | None = Field(default=4.0, ge=-20.0, le=40.0)
    target_vswr: float = Field(default=2.0, gt=1.0, le=20.0)
    minimum_efficiency: float | None = Field(default=0.70, gt=0.0, le=1.0)
    max_width_mm: float = Field(default=100.0, gt=0.1, le=10_000.0)
    max_height_mm: float = Field(default=100.0, gt=0.1, le=10_000.0)
    max_depth_mm: float = Field(default=20.0, gt=0.1, le=10_000.0)
    polarization: str = "linear"
    allowed_topologies: list[AntennaTopology] = Field(
        default_factory=lambda: list(AntennaTopology)
    )
    candidate_budget: int = Field(default=16, ge=4, le=64)
    generations: int = Field(default=2, ge=1, le=5)
    verify_top_k: int = Field(default=1, ge=0, le=3)
    seed: int = 42

    @model_validator(mode="after")
    def validate_band(self) -> DiscoveryRequest:
        center_hz = self.center_frequency_ghz * 1e9
        half_bandwidth_hz = self.bandwidth_mhz * 1e6 / 2
        if half_bandwidth_hz >= center_hz:
            raise ValueError("bandwidth must be smaller than twice the center frequency")
        return self

    def to_requirements(self) -> DiscoveryRequirements:
        center_hz = self.center_frequency_ghz * 1e9
        half_bandwidth_hz = self.bandwidth_mhz * 1e6 / 2
        return DiscoveryRequirements(
            name=self.name,
            frequency_range_hz=(center_hz - half_bandwidth_hz, center_hz + half_bandwidth_hz),
            target_gain_dbi=self.target_gain_dbi,
            target_vswr=self.target_vswr,
            minimum_efficiency=self.minimum_efficiency,
            max_dimensions_m=(
                self.max_width_mm * 1e-3,
                self.max_height_mm * 1e-3,
                self.max_depth_mm * 1e-3,
            ),
            polarization=self.polarization,
            allowed_topologies=self.allowed_topologies,
            candidate_budget=self.candidate_budget,
            generations=self.generations,
            verify_top_k=self.verify_top_k,
            seed=self.seed,
        )


async def _execute_discovery(run_id: uuid.UUID) -> None:
    run = _runs[run_id]
    run.state = DiscoveryState.EXPLORING
    run.started_at = datetime.now(UTC)
    run.stage = "Exploring topology families"

    async def update_progress(
        stage: str,
        progress: float,
        candidates: list[AntennaCandidate],
    ) -> None:
        run.stage = stage
        run.progress = progress
        run.candidates = list(candidates)
        run.explored_count = len(candidates)
        if progress >= 0.78 and progress < 1.0:
            run.state = DiscoveryState.VERIFYING
        elif progress >= 0.40:
            run.state = DiscoveryState.SCREENING

    try:
        engine = AntennaDiscoveryEngine(run.requirements)
        candidates, warnings = await engine.run(update_progress)
        run.candidates = candidates
        run.explored_count = len(candidates)
        run.best_candidate = candidates[0] if candidates else None
        run.warnings = warnings
        run.progress = 1.0
        run.stage = "Discovery complete"
        run.state = DiscoveryState.COMPLETED
    except asyncio.CancelledError:
        run.state = DiscoveryState.CANCELLED
        run.stage = "Cancelled"
        raise
    except Exception as error:  # noqa: BLE001
        run.state = DiscoveryState.FAILED
        run.stage = "Discovery failed"
        run.error = f"{type(error).__name__}: {error}"
    finally:
        run.completed_at = datetime.now(UTC)


def _forget_task(run_id: uuid.UUID) -> None:
    _tasks.pop(run_id, None)


@router.post("", response_model=DiscoveryRun)
async def start_discovery(
    request: DiscoveryRequest,
    wait: bool = Query(default=False, description="Wait for completion; intended for tests and small runs."),
) -> DiscoveryRun:
    run = DiscoveryRun(requirements=request.to_requirements())
    _runs[run.id] = run
    if wait:
        await _execute_discovery(run.id)
    else:
        task = asyncio.create_task(_execute_discovery(run.id))
        _tasks[run.id] = task

        def forget_completed_task(_task: asyncio.Task[None]) -> None:
            _forget_task(run.id)

        task.add_done_callback(forget_completed_task)
    return run


@router.get("", response_model=list[DiscoveryRun])
async def list_discoveries() -> list[DiscoveryRun]:
    return sorted(_runs.values(), key=lambda run: run.created_at, reverse=True)


@router.get("/{run_id}", response_model=DiscoveryRun)
async def get_discovery(run_id: uuid.UUID) -> DiscoveryRun:
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Discovery run not found")
    return run


@router.delete("/{run_id}", response_model=DiscoveryRun)
async def cancel_discovery(run_id: uuid.UUID) -> DiscoveryRun:
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Discovery run not found")
    task = _tasks.get(run_id)
    if task is not None and not task.done():
        task.cancel()
    elif not run.state.is_terminal:
        run.state = DiscoveryState.CANCELLED
        run.stage = "Cancelled"
        run.completed_at = datetime.now(UTC)
    return run
