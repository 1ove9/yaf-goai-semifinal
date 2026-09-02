"""Mock-only tests for pixel batch recovery and source-addressed analysis."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yaf_ai.exploration.batch import (
    BatchConfig,
    BatchConfigDocument,
    BatchRunRecord,
    BatchState,
    ReferenceScore,
    RunExecution,
    batch_config_hash,
    load_batch_config,
    run_pixel_batch,
)
from yaf_ai.exploration.environment import DiscoveryPolicy
from yaf_ai.exploration.pixel import WIFI24_PIXEL_PROPOSAL_SPACE
from yaf_ai.exploration.pixel_analysis import build_pixel_analysis
from yaf_ai.exploration.specs import get_spec

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_pixel_batch_preflight_freezes_shape_and_resume_is_idempotent(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    async def mock_run(record: BatchRunRecord, _runs_root: Path) -> RunExecution:
        calls.append(record.run_key)
        return RunExecution(duration_seconds=0.1, steps_completed=record.budget)

    state = await run_pixel_batch(
        "pixel-resume",
        repo_root=tmp_path,
        executor=mock_run,
    )
    assert len(calls) == 7
    assert all(record.status == "completed" for record in state.runs)
    config_path = tmp_path / "runs" / "batch_pixel-resume" / "config.json"
    document = load_batch_config(config_path)
    assert document.config.experiment_kind == "pixel"
    assert document.config.budget == 40
    assert document.config.seeds == (101, 202, 303)

    async def unexpected(
        _record: BatchRunRecord,
        _runs_root: Path,
    ) -> RunExecution:
        raise AssertionError("completed pixel run was executed again")

    resumed = await run_pixel_batch(
        "pixel-resume",
        repo_root=tmp_path,
        executor=unexpected,
    )
    assert resumed == state


def _record(agent: str, seed: int) -> BatchRunRecord:
    return BatchRunRecord(
        run_key=f"wifi24:{agent}:{seed}",
        run_id=f"pixel-analysis-wifi24-{agent}-s{seed}",
        spec_name="wifi24",
        agent=agent,
        seed=seed,
        budget=2,
        status="completed",
        duration_seconds=0.1,
        started_at=NOW,
        finished_at=NOW,
    )


def _source_run(root: Path, record: BatchRunRecord, scores: tuple[float, ...]) -> None:
    directory = root / record.run_id
    directory.mkdir(parents=True)
    topology = WIFI24_PIXEL_PROPOSAL_SPACE.describe_mask(
        WIFI24_PIXEL_PROPOSAL_SPACE.classic_mask()
    )
    lines = [
        json.dumps(
            {
                "event_type": "evaluation",
                "run_id": record.run_id,
                "step_index": index,
                "solver_mode": "subprocess",
                "metrics": {"min_s11_db": -10.0 - index},
                "score": score,
                "topology": topology.model_dump(mode="json"),
            },
            separators=(",", ":"),
        )
        for index, score in enumerate(scores)
    ]
    (directory / "log.jsonl").write_bytes(
        ("\n".join(lines) + "\n").encode("utf-8")
    )
    (directory / "summary.json").write_bytes(
        (
            json.dumps(
                {
                    "run_id": record.run_id,
                    "config_hash": "b" * 64,
                    "seed": record.seed,
                    "steps_completed": len(scores),
                    "rejected_proposals": 0,
                }
            )
            + "\n"
        ).encode("utf-8")
    )


def test_pixel_analysis_computes_pairs_curves_and_reference_answers(
    tmp_path: Path,
) -> None:
    records = (
        _record("evolve_pixel", 101),
        _record("evolve_pixel", 202),
        _record("random_pixel", 101),
        _record("random_pixel", 202),
    )
    sequences = ((0.4, 0.7), (0.8, 0.6), (0.3, 0.5), (0.55, 0.65))
    for record, scores in zip(records, sequences, strict=True):
        _source_run(tmp_path, record, scores)
    config = BatchConfig(
        batch_id="pixel-analysis",
        specs={"wifi24": get_spec("wifi24")},
        budget=2,
        seeds=(101, 202),
        proposal_space=WIFI24_PIXEL_PROPOSAL_SPACE,
        discovery_policy=DiscoveryPolicy(),
        calibration_seconds={"wifi24": 0.1},
        duration_limit_seconds=3600.0,
        estimated_total_seconds=0.9,
        selection_reason="synthetic",
        experiment_kind="pixel",
        reference_scores=(
            ReferenceScore(
                label="Day 2 wifi24 classic",
                score=0.510190364124435,
                source_run_id="day2-wifi24-classic-s0",
            ),
            ReferenceScore(
                label="Day 2 wifi24 parametric GP best",
                score=0.7726173256030144,
                source_run_id="day2-wifi24-gp-s505",
            ),
        ),
    )
    config_hash = batch_config_hash(config)
    document = BatchConfigDocument(config_hash=config_hash, config=config)
    state = BatchState(
        batch_id="pixel-analysis",
        config_hash=config_hash,
        runs=records,
    )

    summary = build_pixel_analysis(document, state.runs, runs_root=tmp_path)

    assert [pair.difference for pair in summary.paired_differences] == pytest.approx(
        [0.2, 0.15]
    )
    evolve_101 = next(
        row
        for row in summary.rows
        if row.agent == "evolve_pixel" and row.seed == 101
    )
    assert evolve_101.best_so_far == (0.4, 0.7)
    assert summary.questions.best_pixel_score == pytest.approx(0.8)
    assert summary.questions.exceeds_day2_classic
    assert summary.questions.exceeds_day2_parametric_gp
