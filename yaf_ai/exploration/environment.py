"""Auditable antenna exploration environment backed by YAF's physics oracle."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

from yaf_ai.exploration.freeform_wire import (
    FREEFORM_FREQUENCY_POINTS,
    evaluate_dual_band_metrics,
    validate_freeform_geometry,
)
from yaf_ai.exploration.pixel import PixelProposalSpace, PixelTopology
from yaf_ai.exploration.proposal_space import (
    PATCH_PROPOSAL_SPACE,
    ProposalSpace,
    get_proposal_space,
)
from yaf_ai.exploration.wire import evaluate_wire_metrics, validate_meander_geometry
from yaf_ai.inverse_design.pipeline import InverseDesignPipeline, PipelineConfig
from yaf_core.domain.design import DesignSpec
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.base import SolverUnavailableError, YAFError

if TYPE_CHECKING:
    from yaf_ai.exploration.logger import ExplorationLogger

log = structlog.get_logger(__name__)


class DiscoverySignal(str, Enum):
    """Predefined evidence classes for the GOAI open-exploration track."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    SOLVER_DISAGREEMENT = "solver_disagreement"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class DiscoveryPolicy(BaseModel):
    """Thresholds fixed before an exploration run begins."""

    model_config = ConfigDict(frozen=True)

    classic_improvement_fraction: float = Field(default=0.10, ge=0.0)
    max_cross_solver_s11_difference_db: float = Field(default=3.0, gt=0.0)
    minimum_negative_samples: int = Field(default=3, ge=2)


class ExplorationConfig(BaseModel):
    """Immutable definition of one antenna exploration problem."""

    model_config = ConfigDict(frozen=True)

    spec: DesignSpec
    evaluation_budget: int = Field(gt=0)
    seed: int = 42
    solver: Literal["auto", "openems", "nec2"] = "openems"
    require_real_solver: bool = True
    proposal_space_version: str = PATCH_PROPOSAL_SPACE.version
    fixed_problem_definition: str = Field(
        default=(
            "The design spec, solver and mesh rules, score function, evaluation budget, "
            "discovery thresholds, and solver-mode honesty checks are fixed."
        ),
        min_length=1,
    )
    explorable_problem_definition: str = Field(
        default=(
            "The agent may explore antenna geometry through bounded parametric templates "
            "and planar pixel topology proposals."
        ),
        min_length=1,
    )
    discovery_policy: DiscoveryPolicy = Field(default_factory=DiscoveryPolicy)
    optimizer_window: int | None = Field(default=None, ge=1)
    nec2_segments_per_wavelength: int = Field(default=20, ge=1)


class GeometryProposal(BaseModel):
    """One agent action: a geometry plus the parameters that produced it."""

    model_config = ConfigDict(frozen=True)

    geometry: Geometry
    parameters: dict[str, float] = Field(default_factory=dict)
    proposer: str
    topology: PixelTopology | None = None


class StepResult(BaseModel):
    """Stable, serializable result returned for each accepted action."""

    model_config = ConfigDict(frozen=True)

    step_index: int
    timestamp: datetime
    solver_name: str
    solver_mode: str
    metrics: dict[str, float]
    score: float
    geometry_hash: str
    geometry_summary: dict[str, Any]
    proposal_parameters: dict[str, float]
    proposer: str
    topology: PixelTopology | None = None


class Observation(BaseModel):
    """Compact environment state exposed to an exploration agent."""

    model_config = ConfigDict(frozen=True)

    step_index: int
    budget_remaining: int
    best_score: float | None = None
    best_geometry_hash: str | None = None
    last_result: StepResult | None = None


class DiscoveryAssessment(BaseModel):
    """Evidence-based classification against predeclared discovery signals."""

    model_config = ConfigDict(frozen=True)

    signal: DiscoverySignal
    reason: str
    classic_improvement_fraction: float | None = None
    cross_solver_s11_difference_db: float | None = None
    candidate_mean_score: float | None = None
    random_mean_score: float | None = None


class EvaluationBudgetExhaustedError(YAFError):
    """Raised when an agent calls step after consuming the fixed budget."""


class ExplorationEvaluationError(YAFError):
    """Raised when the shared YAF pipeline cannot evaluate a proposal."""


def geometry_hash(geometry: Geometry) -> str:
    """Hash physical geometry content while ignoring its random UUID."""

    payload = geometry.model_dump(mode="json", exclude={"id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def geometry_summary(geometry: Geometry) -> dict[str, Any]:
    """Return a compact audit-safe geometry description."""

    dimensions = [0.0, 0.0, 0.0]
    if geometry.vertices:
        for axis in range(3):
            values = [vertex[axis] for vertex in geometry.vertices]
            dimensions[axis] = max(values) - min(values)
    return {
        "name": geometry.name,
        "representation": geometry.representation,
        "num_vertices": geometry.num_vertices,
        "num_faces": geometry.num_faces,
        "dimensions_m": dimensions,
        "antenna_class": geometry.metadata.get("antenna_class"),
    }


def assess_discovery(
    *,
    candidate_scores: list[float],
    random_scores: list[float],
    classic_score: float,
    nec2_min_s11_db: float | None,
    openems_min_s11_db: float | None,
    policy: DiscoveryPolicy,
) -> DiscoveryAssessment:
    """Classify evidence without silently upgrading a candidate into a discovery."""

    cross_difference: float | None = None
    if nec2_min_s11_db is not None and openems_min_s11_db is not None:
        cross_difference = abs(nec2_min_s11_db - openems_min_s11_db)
        if cross_difference > policy.max_cross_solver_s11_difference_db:
            return DiscoveryAssessment(
                signal=DiscoverySignal.SOLVER_DISAGREEMENT,
                reason="NEC2 and openEMS differ beyond the predeclared 3 dB tolerance.",
                cross_solver_s11_difference_db=cross_difference,
            )

    candidate_best = max(candidate_scores) if candidate_scores else None
    improvement: float | None = None
    if candidate_best is not None and classic_score > 0.0:
        improvement = candidate_best / classic_score - 1.0
        if (
            improvement >= policy.classic_improvement_fraction
            and cross_difference is not None
        ):
            return DiscoveryAssessment(
                signal=DiscoverySignal.POSITIVE,
                reason="Candidate beats the classic template and is cross-solver consistent.",
                classic_improvement_fraction=improvement,
                cross_solver_s11_difference_db=cross_difference,
            )

    minimum = policy.minimum_negative_samples
    if len(candidate_scores) >= minimum and len(random_scores) >= minimum:
        candidate_mean = sum(candidate_scores) / len(candidate_scores)
        random_mean = sum(random_scores) / len(random_scores)
        if candidate_mean < random_mean:
            return DiscoveryAssessment(
                signal=DiscoverySignal.NEGATIVE,
                reason="Exploration is systematically worse than the matched random baseline.",
                classic_improvement_fraction=improvement,
                cross_solver_s11_difference_db=cross_difference,
                candidate_mean_score=candidate_mean,
                random_mean_score=random_mean,
            )

    return DiscoveryAssessment(
        signal=DiscoverySignal.INSUFFICIENT_EVIDENCE,
        reason="The run does not yet satisfy a predeclared discovery condition.",
        classic_improvement_fraction=improvement,
        cross_solver_s11_difference_db=cross_difference,
    )


class AntennaExplorationEnv:
    """Budgeted agent environment using the existing inverse-design oracle."""

    def __init__(
        self,
        config: ExplorationConfig,
        *,
        pipeline: InverseDesignPipeline | None = None,
        audit_logger: ExplorationLogger | None = None,
        runs_root: Path = Path("runs"),
    ) -> None:
        self.config = config
        self.proposal_space: ProposalSpace | PixelProposalSpace = get_proposal_space(
            config.proposal_space_version
        )
        self._pipeline = pipeline or InverseDesignPipeline(
            PipelineConfig(
                n_candidates=1,
                top_k=1,
                max_pipeline_loops=1,
                use_surrogate=False,
                use_diff_fdtd=False,
                use_topo=False,
                use_high_fidelity=True,
                verify_top_n=1,
                generator="parametric",
            )
        )
        if audit_logger is None:
            from yaf_ai.exploration.logger import ExplorationLogger

            audit_logger = ExplorationLogger(config=config, runs_root=runs_root)
        self._logger = audit_logger
        self._results: list[StepResult] = []
        self._best: StepResult | None = None

    @property
    def run_id(self) -> str:
        return self._logger.run_id

    @property
    def results(self) -> tuple[StepResult, ...]:
        return tuple(self._results)

    @property
    def budget_remaining(self) -> int:
        return self.config.evaluation_budget - len(self._results)

    def reset(self) -> Observation:
        """Reset in-memory episode state before the first evaluation."""

        self._results = []
        self._best = None
        return self._observation()

    def record_parameter_rejection(
        self, parameters: dict[str, float], proposer: str, reason: str
    ) -> None:
        """Audit a generator-level rejection without consuming solver budget."""

        placeholder = Geometry(
            name=f"{proposer}_rejected_parameters",
            vertices=[[0.0, 0.0, 0.0]],
            faces=[],
            metadata={
                "antenna_class": "rejected_freeform_wire_3d",
                "design_features": parameters,
            },
        )
        self._logger.append_rejection(
            GeometryProposal(
                geometry=placeholder,
                parameters=parameters,
                proposer=proposer,
            ),
            reason,
            self.budget_remaining,
        )

    async def step(self, action: GeometryProposal) -> StepResult:
        """Evaluate one proposal through YAF's shared solve and score path."""

        if self.budget_remaining <= 0:
            raise EvaluationBudgetExhaustedError(
                f"evaluation budget exhausted for run {self.run_id}"
            )
        try:
            self.proposal_space.validate_parameters(action.parameters)
            if isinstance(self.proposal_space, PixelProposalSpace):
                if action.topology is None:
                    raise ValueError("pixel proposal must include a topology descriptor")
                self.proposal_space.decode_topology(action.topology)
            elif action.topology is not None:
                raise ValueError("continuous proposal cannot include pixel topology")
            if action.geometry.metadata.get("antenna_class") == "meander_dipole":
                validate_meander_geometry(action.geometry)
            if action.geometry.metadata.get("antenna_class") in {
                "freeform_wire_3d",
                "day6_ocfd",
                "day6_straight_dipole",
            }:
                validate_freeform_geometry(action.geometry)
            self._validate_geometry(action.geometry)
        except ValueError as error:
            self._logger.append_rejection(action, str(error), self.budget_remaining)
            raise

        day6_wire = action.geometry.metadata.get("antenna_class") in {
            "freeform_wire_3d",
            "day6_ocfd",
            "day6_straight_dipole",
        }
        sim_spec = SimulationSpec(
            name=f"exploration_{self.run_id}_{len(self._results)}",
            frequency_range=self.config.spec.frequency_range,
            frequency_points=FREEFORM_FREQUENCY_POINTS if day6_wire else 51,
            solver_settings={
                "nec2_segments_per_wavelength": self.config.nec2_segments_per_wavelength,
            } if day6_wire else {},
            far_field_request=None if day6_wire else {},
        )
        verified = await self._pipeline._verify(
            [action.geometry],
            sim_spec,
            self.config.spec,
            solver_name=self.config.solver,
        )
        if verified is None:
            raise ExplorationEvaluationError(
                f"pipeline could not evaluate geometry {action.geometry.name!r}"
            )

        geometry, simulation = verified
        solver_mode = str(simulation.solver_metadata.get("solver_mode", "unknown"))
        if self.config.require_real_solver and solver_mode not in {"native", "subprocess"}:
            raise SolverUnavailableError(
                simulation.solver_name,
                str(simulation.job_id),
                f"exploration requires real physics; received solver_mode={solver_mode}",
            )

        wire_class = geometry.metadata.get("antenna_class")
        if wire_class in {"meander_dipole", "box_straight_dipole"}:
            metrics = evaluate_wire_metrics(simulation, self.config.spec)
        elif wire_class in {
            "freeform_wire_3d",
            "day6_ocfd",
            "day6_straight_dipole",
        }:
            metrics = evaluate_dual_band_metrics(simulation)
        else:
            metrics = self._pipeline._evaluate_metrics(simulation, self.config.spec)
        result = StepResult(
            step_index=len(self._results),
            timestamp=datetime.now(UTC),
            solver_name=simulation.solver_name,
            solver_mode=solver_mode,
            metrics=metrics,
            score=metrics["composite_score"],
            geometry_hash=geometry_hash(geometry),
            geometry_summary=geometry_summary(geometry),
            proposal_parameters=action.parameters,
            proposer=action.proposer,
            topology=action.topology,
        )
        self._results.append(result)
        if self._best is None or result.score > self._best.score:
            self._best = result
        self._logger.append_step(result)
        log.info(
            "exploration_step_complete",
            run_id=self.run_id,
            step_index=result.step_index,
            solver_mode=result.solver_mode,
            score=result.score,
            geometry_hash=result.geometry_hash,
        )
        return result

    def observation(self) -> Observation:
        """Return the current environment state without mutating it."""

        return self._observation()

    def finish(self) -> Path:
        """Write the stable run summary and return its path."""

        return self._logger.write_summary(self._results)

    def _observation(self) -> Observation:
        return Observation(
            step_index=len(self._results),
            budget_remaining=self.budget_remaining,
            best_score=self._best.score if self._best else None,
            best_geometry_hash=self._best.geometry_hash if self._best else None,
            last_result=self._results[-1] if self._results else None,
        )

    def _validate_geometry(self, geometry: Geometry) -> None:
        if not geometry.vertices:
            raise ValueError("geometry proposal must contain vertices")
        summary = geometry_summary(geometry)
        dimensions = summary["dimensions_m"]
        allowed = self.config.spec.size_constraint.dimensions
        if any(float(actual) > limit + 1e-12 for actual, limit in zip(dimensions, allowed, strict=True)):
            raise ValueError(
                f"geometry dimensions {dimensions} exceed fixed size constraint {allowed}"
            )
