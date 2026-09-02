"""Tests for traceable batch statistics derived from synthetic JSONL logs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yaf_ai.exploration.analysis import analyze_batch, build_analysis
from yaf_ai.exploration.batch import (
    BatchConfig,
    BatchConfigDocument,
    BatchRunRecord,
    BatchState,
    batch_config_hash,
)
from yaf_ai.exploration.environment import DiscoveryPolicy
from yaf_ai.exploration.proposal_space import PATCH_PROPOSAL_SPACE
from yaf_ai.exploration.specs import get_spec

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _source_run(
    root: Path,
    *,
    run_id: str,
    seed: int,
    scores: tuple[float, ...],
) -> None:
    directory = root / run_id
    directory.mkdir(parents=True)
    lines = [
        json.dumps(
            {
                "run_id": run_id,
                "step_index": index,
                "solver_mode": "subprocess",
                "metrics": {
                    "composite_score": score,
                    "min_s11_db": -10.0 - index,
                },
                "score": score,
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
                    "run_id": run_id,
                    "config_hash": "b" * 64,
                    "seed": seed,
                    "steps_completed": len(scores),
                }
            )
            + "\n"
        ).encode("utf-8")
    )


def _record(agent: str, seed: int) -> BatchRunRecord:
    run_id = f"analysis-wifi24-{agent}-s{seed}"
    return BatchRunRecord(
        run_key=f"wifi24:{agent}:{seed}",
        run_id=run_id,
        spec_name="wifi24",
        agent=agent,
        seed=seed,
        budget=1 if agent == "classic" else 2,
        status="completed",
        duration_seconds=0.1,
        started_at=NOW,
        finished_at=NOW,
    )


def test_analysis_computes_means_pairs_and_best_so_far(tmp_path: Path) -> None:
    records = (
        _record("classic", 0),
        _record("gp", 101),
        _record("gp", 202),
        _record("random", 101),
        _record("random", 202),
    )
    score_sequences = {
        records[0].run_id: (0.4,),
        records[1].run_id: (0.2, 0.5),
        records[2].run_id: (0.6, 0.4),
        records[3].run_id: (0.3, 0.4),
        records[4].run_id: (0.5, 0.55),
    }
    for record in records:
        _source_run(
            tmp_path,
            run_id=record.run_id,
            seed=record.seed,
            scores=score_sequences[record.run_id],
        )

    config = BatchConfig(
        batch_id="analysis",
        specs={"wifi24": get_spec("wifi24")},
        budget=2,
        seeds=(101, 202),
        proposal_space=PATCH_PROPOSAL_SPACE,
        discovery_policy=DiscoveryPolicy(),
        calibration_seconds={"wifi24": 0.1},
        duration_limit_seconds=10.0,
        estimated_total_seconds=0.9,
        selection_reason="synthetic test",
    )
    document = BatchConfigDocument(config_hash="a" * 64, config=config)
    state = BatchState(batch_id="analysis", config_hash="a" * 64, runs=records)

    summary = build_analysis(state, document, runs_root=tmp_path)

    gp = next(item for item in summary.aggregates if item.agent == "gp")
    random = next(item for item in summary.aggregates if item.agent == "random")
    assert gp.mean_best_score == pytest.approx(0.55)
    assert gp.sample_std_best_score == pytest.approx(0.0707106781)
    assert random.mean_best_score == pytest.approx(0.475)
    assert [pair.difference for pair in summary.paired_differences] == pytest.approx(
        [0.1, 0.05]
    )
    gp_101 = next(
        row for row in summary.rows if row.agent == "gp" and row.seed == 101
    )
    gp_202 = next(
        row for row in summary.rows if row.agent == "gp" and row.seed == 202
    )
    assert gp_101.best_so_far == (0.2, 0.5)
    assert gp_101.evaluations_to_best == 2
    assert gp_202.best_so_far == (0.6, 0.6)
    assert gp_202.evaluations_to_best == 1
    assert set(gp.source_run_ids) == {records[1].run_id, records[2].run_id}


def test_analysis_writes_json_report_and_agg_png(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    records = (
        _record("classic", 0),
        _record("gp", 101),
        _record("random", 101),
    )
    for record, scores in zip(
        records,
        ((0.4,), (0.3, 0.5), (0.2, 0.45)),
        strict=True,
    ):
        _source_run(
            runs_root,
            run_id=record.run_id,
            seed=record.seed,
            scores=scores,
        )
    config = BatchConfig(
        batch_id="render",
        specs={"wifi24": get_spec("wifi24")},
        budget=2,
        seeds=(101,),
        proposal_space=PATCH_PROPOSAL_SPACE,
        discovery_policy=DiscoveryPolicy(),
        calibration_seconds={"wifi24": 0.1},
        duration_limit_seconds=10.0,
        estimated_total_seconds=0.5,
        selection_reason="synthetic render test",
    )
    config_hash = batch_config_hash(config)
    document = BatchConfigDocument(config_hash=config_hash, config=config)
    state = BatchState(batch_id="render", config_hash=config_hash, runs=records)
    batch_directory = runs_root / "batch_render"
    batch_directory.mkdir(parents=True)
    (batch_directory / "config.json").write_bytes(
        (
            json.dumps(document.model_dump(mode="json"), sort_keys=True) + "\n"
        ).encode("utf-8")
    )
    (batch_directory / "state.json").write_bytes(
        (json.dumps(state.model_dump(mode="json"), sort_keys=True) + "\n").encode(
            "utf-8"
        )
    )

    rendered = analyze_batch("render", repo_root=tmp_path)
    output = tmp_path / "artifacts" / "analysis" / "render"

    assert rendered.batch_id == "render"
    assert (output / "summary.json").is_file()
    assert (output / "report.md").is_file()
    assert (output / "wifi24-best-so-far.png").stat().st_size > 0
    assert b"\r" not in (output / "summary.json").read_bytes()
    report = (output / "report.md").read_text(encoding="utf-8")
    table_row = "| wifi24 | yes (+25.00%, threshold 10%)"
    assert table_row in report
    assert report.index(table_row) < report.index("### Interpretation")
