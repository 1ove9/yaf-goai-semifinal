"""Domain contracts for requirement-driven antenna discovery.

The discovery layer deliberately separates fast analytical screening from
solver-verified evidence.  A candidate is never presented as simulated unless
an installed electromagnetic solver actually evaluated it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field, model_validator

from yaf_core.domain.geometry import Geometry


class AntennaTopology(str, enum.Enum):
    DIPOLE = "dipole"
    PATCH = "patch"
    BOWTIE = "bowtie"
    SPIRAL = "spiral"
    MEANDER = "meander"
    FRACTAL = "fractal"
    HORN = "horn"


class DiscoveryState(str, enum.Enum):
    PENDING = "pending"
    EXPLORING = "exploring"
    SCREENING = "screening"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            DiscoveryState.COMPLETED,
            DiscoveryState.FAILED,
            DiscoveryState.CANCELLED,
        }


class EvaluationMode(str, enum.Enum):
    ANALYTICAL_SCREENING = "analytical_screening"
    REAL_SOLVER = "real_solver"


class DiscoveryRequirements(BaseModel):
    """SI-unit contract from which every candidate and score is derived."""

    name: str = "discovered_antenna"
    frequency_range_hz: tuple[float, float]
    target_gain_dbi: float | None = None
    target_vswr: float = Field(default=2.0, gt=1.0)
    minimum_efficiency: float | None = Field(default=None, gt=0.0, le=1.0)
    max_dimensions_m: tuple[float, float, float]
    polarization: str = "linear"
    allowed_topologies: list[AntennaTopology] = Field(
        default_factory=lambda: list(AntennaTopology)
    )
    candidate_budget: int = Field(default=16, ge=4, le=64)
    generations: int = Field(default=2, ge=1, le=5)
    verify_top_k: int = Field(default=1, ge=0, le=3)
    seed: int = 42

    @model_validator(mode="after")
    def validate_physical_contract(self) -> DiscoveryRequirements:
        f_min, f_max = self.frequency_range_hz
        if f_min <= 0 or f_max <= f_min:
            raise ValueError("frequency_range_hz must be positive and increasing")
        if any(dimension <= 0 for dimension in self.max_dimensions_m):
            raise ValueError("max_dimensions_m must contain positive dimensions")
        if not self.allowed_topologies:
            raise ValueError("at least one antenna topology must be allowed")
        return self


class CandidateMetrics(BaseModel):
    resonance_hz: float
    bandwidth_hz: float
    gain_dbi: float
    efficiency: float
    vswr: float
    dimensions_m: tuple[float, float, float]


class RequirementCheck(BaseModel):
    key: str
    label: str
    target: float
    actual: float
    unit: str
    comparator: str
    passed: bool
    evidence: EvaluationMode


class AntennaCandidate(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    topology: AntennaTopology
    name: str
    generation: int
    geometry: Geometry
    parameters: dict[str, float] = Field(default_factory=dict)
    metrics: CandidateMetrics
    checks: list[RequirementCheck] = Field(default_factory=list)
    score: float = Field(ge=0.0, le=1.0)
    novelty_score: float = Field(ge=0.0, le=1.0)
    evaluation_mode: EvaluationMode = EvaluationMode.ANALYTICAL_SCREENING
    solver_name: str | None = None
    solver_mode: str | None = None
    warning: str | None = None
    parent_id: uuid.UUID | None = None


class DiscoveryRun(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    requirements: DiscoveryRequirements
    state: DiscoveryState = DiscoveryState.PENDING
    stage: str = "Queued"
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    explored_count: int = 0
    candidates: list[AntennaCandidate] = Field(default_factory=list)
    best_candidate: AntennaCandidate | None = None
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

