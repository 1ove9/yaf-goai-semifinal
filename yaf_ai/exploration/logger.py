"""Stable JSONL audit logging for antenna exploration runs."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from yaf_ai.exploration.environment import (
    ExplorationConfig,
    GeometryProposal,
    StepResult,
    geometry_hash,
    geometry_summary,
)
from yaf_ai.exploration.pixel import PixelTopology


class AuditStepRecord(BaseModel):
    """Versioned on-disk schema for one environment step."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    event_type: Literal["evaluation"] = "evaluation"
    run_id: str
    step_index: int
    timestamp: datetime
    geometry_summary: dict[str, Any]
    geometry_hash: str
    solver_name: str
    solver_mode: str
    metrics: dict[str, float]
    score: float
    seed: int
    config_hash: str
    proposal_parameters: dict[str, float]
    proposer: str
    topology: PixelTopology | None = None


class AuditRejectionRecord(BaseModel):
    """One invalid action rejected before any solver budget was consumed."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    event_type: Literal["rejected"] = "rejected"
    run_id: str
    timestamp: datetime
    reason: str
    budget_remaining: int
    geometry_hash: str
    geometry_summary: dict[str, Any]
    seed: int
    config_hash: str
    proposal_parameters: dict[str, float]
    proposer: str
    topology: PixelTopology | None = None


class RunSummary(BaseModel):
    """Stable summary written when a run finishes."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int
    evaluation_budget: int
    solver_mode_counts: dict[str, int]
    top_designs: list[AuditStepRecord]
    rejected_proposals: int = 0
    status: Literal["completed", "failed"] = "completed"
    failure: str | None = None


def config_hash(config: ExplorationConfig) -> str:
    """Return a stable SHA-256 digest of the frozen run definition."""

    canonical = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ExplorationLogger:
    """Append-only audit writer for a single exploration run."""

    def __init__(
        self,
        *,
        config: ExplorationConfig,
        runs_root: Path = Path("runs"),
        run_id: str | None = None,
    ) -> None:
        self.config = config
        self.run_id = run_id or self._new_run_id()
        self.config_hash = config_hash(config)
        self.started_at = datetime.now(UTC)
        self.run_directory = runs_root / self.run_id
        self.run_directory.mkdir(parents=True, exist_ok=False)
        self.log_path = self.run_directory / "log.jsonl"
        self.summary_path = self.run_directory / "summary.json"
        self._records: list[AuditStepRecord] = []
        self._rejections: list[AuditRejectionRecord] = []

    def _append_payload(self, payload: BaseModel) -> None:
        line = json.dumps(
            payload.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        with self.log_path.open("ab") as handle:
            handle.write((line + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())

    def append_step(self, result: StepResult) -> AuditStepRecord:
        """Append and fsync one complete step record."""

        if result.step_index != len(self._records):
            raise ValueError(
                f"step_index must be contiguous: expected {len(self._records)}, "
                f"received {result.step_index}"
            )
        record = AuditStepRecord(
            run_id=self.run_id,
            step_index=result.step_index,
            timestamp=result.timestamp,
            geometry_summary=result.geometry_summary,
            geometry_hash=result.geometry_hash,
            solver_name=result.solver_name,
            solver_mode=result.solver_mode,
            metrics=result.metrics,
            score=result.score,
            seed=self.config.seed,
            config_hash=self.config_hash,
            proposal_parameters=result.proposal_parameters,
            proposer=result.proposer,
            topology=result.topology,
        )
        self._append_payload(record)
        self._records.append(record)
        return record

    def append_rejection(
        self,
        proposal: GeometryProposal,
        reason: str,
        budget_remaining: int,
    ) -> AuditRejectionRecord:
        """Append an invalid-proposal event without advancing the step index."""

        record = AuditRejectionRecord(
            run_id=self.run_id,
            timestamp=datetime.now(UTC),
            reason=reason,
            budget_remaining=budget_remaining,
            geometry_hash=geometry_hash(proposal.geometry),
            geometry_summary=geometry_summary(proposal.geometry),
            seed=self.config.seed,
            config_hash=self.config_hash,
            proposal_parameters=proposal.parameters,
            proposer=proposal.proposer,
            topology=proposal.topology,
        )
        self._append_payload(record)
        self._rejections.append(record)
        return record

    def write_summary(self, results: list[StepResult] | tuple[StepResult, ...]) -> Path:
        """Atomically write the final summary with top-three designs."""

        if len(results) != len(self._records):
            raise ValueError("summary results do not match the append-only audit log")
        top = sorted(self._records, key=lambda record: record.score, reverse=True)[:3]
        summary = RunSummary(
            run_id=self.run_id,
            started_at=self.started_at,
            finished_at=datetime.now(UTC),
            seed=self.config.seed,
            config_hash=self.config_hash,
            config=self.config.model_dump(mode="json"),
            steps_completed=len(self._records),
            evaluation_budget=self.config.evaluation_budget,
            solver_mode_counts=dict(Counter(record.solver_mode for record in self._records)),
            top_designs=top,
            rejected_proposals=len(self._rejections),
        )
        temporary = self.summary_path.with_suffix(".json.tmp")
        temporary.write_bytes(
            (
                json.dumps(
                    summary.model_dump(mode="json"),
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=True,
                )
                + "\n"
            ).encode("utf-8")
        )
        temporary.replace(self.summary_path)
        return self.summary_path

    def write_failure_summary(
        self,
        error: str,
        results: list[StepResult] | tuple[StepResult, ...],
    ) -> Path:
        """Seal a failed run so its partial or empty evidence remains archivable."""

        if len(results) != len(self._records):
            raise ValueError("failure results do not match the append-only audit log")
        if not self.log_path.exists():
            self.log_path.write_bytes(b"")
        summary = RunSummary(
            run_id=self.run_id,
            started_at=self.started_at,
            finished_at=datetime.now(UTC),
            seed=self.config.seed,
            config_hash=self.config_hash,
            config=self.config.model_dump(mode="json"),
            steps_completed=len(self._records),
            evaluation_budget=self.config.evaluation_budget,
            solver_mode_counts=dict(
                Counter(record.solver_mode for record in self._records)
            ),
            top_designs=sorted(
                self._records, key=lambda record: record.score, reverse=True
            )[:3],
            rejected_proposals=len(self._rejections),
            status="failed",
            failure=error,
        )
        temporary = self.summary_path.with_suffix(".json.tmp")
        temporary.write_bytes(
            (
                json.dumps(
                    summary.model_dump(mode="json"),
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=True,
                )
                + "\n"
            ).encode("utf-8")
        )
        temporary.replace(self.summary_path)
        return self.summary_path

    @staticmethod
    def load_steps(path: Path) -> list[AuditStepRecord]:
        """Read a JSONL audit log using its versioned schema."""

        records: list[AuditStepRecord] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    raw = json.loads(line)
                    if raw.get("event_type") == "rejected":
                        continue
                    records.append(AuditStepRecord.model_validate(raw))
        return records

    @staticmethod
    def _new_run_id() -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return f"{timestamp}-{uuid.uuid4().hex[:10]}"
