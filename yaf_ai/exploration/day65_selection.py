"""Source-only top-two selection for the Day 6.5 v2 hunt."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.day65_batch import (
    DAY65_BATCH_ID,
    DAY65_BUDGET,
    DAY65_OCFD_RUN_ID,
    DAY65_OCFD_SCORE,
    DAY65_SEEDS,
    Day65BatchConfigDocument,
    day65_batch_config_document,
)
from yaf_ai.exploration.logger import AuditStepRecord

DAY65_SELECTION_FILE = f"artifacts/analysis/{DAY65_BATCH_ID}/selection.json"


class SelectedDay65Design(BaseModel):
    """One immutable unshaped-score-ranked v2 candidate address."""

    model_config = ConfigDict(frozen=True)

    rank: int = Field(gt=0)
    source_run_id: str
    source_step_index: int = Field(ge=0)
    source_geometry_hash: str
    source_config_hash: str
    source_base_score: float
    source_search_score: float
    source_valid_both_bands: bool
    proposal_parameters: dict[str, float]
    proposer: str
    ocfd_run_id: str = DAY65_OCFD_RUN_ID
    ocfd_score: float = DAY65_OCFD_SCORE
    oracle_improvement_fraction: float


class Day65SelectionDocument(BaseModel):
    """Committed source-only selection made before v2 openEMS output."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    batch_id: str = DAY65_BATCH_ID
    selected_at: datetime
    selection_rule: str
    batch_config_hash: str
    candidates: tuple[SelectedDay65Design, SelectedDay65Design]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def _load_evaluations(path: Path) -> tuple[AuditStepRecord, ...]:
    records: list[AuditStepRecord] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = json.loads(line)
            if raw.get("event_type") == "evaluation":
                records.append(AuditStepRecord.model_validate(raw))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise CrossCheckError(f"cannot load Day 6.5 evidence {path}: {error}") from error
    return tuple(records)


def rank_unique_base_score_records(
    records: Sequence[AuditStepRecord], count: int = 2
) -> tuple[AuditStepRecord, ...]:
    """Rank only unshaped base score with frozen tie-breaks and deduplication."""

    ordered = sorted(records, key=lambda row: (-row.score, row.run_id, row.step_index))
    selected: list[AuditStepRecord] = []
    hashes: set[str] = set()
    for record in ordered:
        if record.geometry_hash in hashes:
            continue
        hashes.add(record.geometry_hash)
        selected.append(record)
        if len(selected) == count:
            break
    if len(selected) != count:
        raise CrossCheckError(
            f"Day 6.5 selector found {len(selected)} unique records, expected {count}"
        )
    return tuple(selected)


def _load_batch_config(repo_root: Path) -> Day65BatchConfigDocument:
    path = repo_root / "artifacts" / "analysis" / DAY65_BATCH_ID / "config.json"
    try:
        stored = Day65BatchConfigDocument.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load Day 6.5 batch config: {error}") from error
    expected = day65_batch_config_document()
    if stored != expected:
        raise CrossCheckError("archived Day 6.5 batch config changed")
    return stored


def select_day65_designs(repo_root: Path) -> Day65SelectionDocument:
    """Select exactly two ES rows from complete archived source evidence."""

    config = _load_batch_config(repo_root)
    records: list[AuditStepRecord] = []
    for seed in DAY65_SEEDS:
        run_id = f"{DAY65_BATCH_ID}-dual-es-s{seed}"
        records.extend(
            _load_evaluations(repo_root / "artifacts" / "runs" / run_id / "log.jsonl")
        )
    expected_count = DAY65_BUDGET * len(DAY65_SEEDS)
    if len(records) != expected_count:
        raise CrossCheckError(
            f"Day 6.5 ES evidence has {len(records)} evaluations, "
            f"expected {expected_count}"
        )
    ranked = rank_unique_base_score_records(records)
    candidates = tuple(
        SelectedDay65Design(
            rank=rank,
            source_run_id=record.run_id,
            source_step_index=record.step_index,
            source_geometry_hash=record.geometry_hash,
            source_config_hash=record.config_hash,
            source_base_score=record.score,
            source_search_score=record.metrics["search_score"],
            source_valid_both_bands=bool(record.metrics["valid_both_bands"]),
            proposal_parameters=record.proposal_parameters,
            proposer=record.proposer,
            oracle_improvement_fraction=record.score / DAY65_OCFD_SCORE - 1.0,
        )
        for rank, record in enumerate(ranked, start=1)
    )
    return Day65SelectionDocument(
        selected_at=datetime.now(UTC),
        selection_rule=config.config.top_selection_rule,
        batch_config_hash=config.config_hash,
        candidates=(candidates[0], candidates[1]),
    )


def write_day65_selection(repo_root: Path) -> Day65SelectionDocument:
    """Persist or integrity-check the frozen top-two selection."""

    path = repo_root / DAY65_SELECTION_FILE
    selected = select_day65_designs(repo_root)
    if path.is_file():
        stored = Day65SelectionDocument.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if stored.model_copy(update={"selected_at": selected.selected_at}) != selected:
            raise CrossCheckError("committed Day 6.5 selection differs from source logs")
        return stored
    _write_json(path, selected.model_dump(mode="json"))
    return selected


def load_day65_selection(repo_root: Path) -> Day65SelectionDocument:
    """Load and recompute selection before any v2 cross-check solve."""

    path = repo_root / DAY65_SELECTION_FILE
    if not path.is_file():
        raise CrossCheckError("Day 6.5 selection must be committed before cross-check")
    stored = Day65SelectionDocument.model_validate_json(path.read_text(encoding="utf-8"))
    recomputed = select_day65_designs(repo_root)
    if stored.model_copy(update={"selected_at": recomputed.selected_at}) != recomputed:
        raise CrossCheckError("Day 6.5 selection no longer matches archived evidence")
    return stored
