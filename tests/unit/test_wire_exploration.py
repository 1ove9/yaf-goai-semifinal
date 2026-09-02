"""Unit tests for the shared native meander exploration path."""

from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yaf_ai.exploration.baselines import (
    GPExplorationAgent,
    RandomSearchBaseline,
    _proposal_from_parameters,
)
from yaf_ai.exploration.batch import (
    BatchConfig,
    BatchConfigDocument,
    BatchRunRecord,
    BatchState,
    RunExecution,
    batch_config_hash,
    load_batch_config,
    run_wire_batch,
)
from yaf_ai.exploration.environment import (
    AntennaExplorationEnv,
    ExplorationConfig,
    GeometryProposal,
    StepResult,
)
from yaf_ai.exploration.logger import AuditStepRecord, ExplorationLogger, RunSummary
from yaf_ai.exploration.proposal_space import MEANDER_PROPOSAL_SPACE
from yaf_ai.exploration.specs import get_spec
from yaf_ai.exploration.wire import (
    MINIMUM_PITCH_M,
    WIRE_BOX_SIZE_M,
    build_meander_dipole,
    wire_spec_updates,
)
from yaf_ai.exploration.wire_analysis import build_wire_analysis
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter


def _parameters() -> dict[str, float]:
    return {
        "turns": 3.0,
        "span_ratio": 0.9,
        "height_ratio": 0.4,
        "feed_gap_ratio": 0.04,
        "terminal_ratio": 0.5,
    }


def _config() -> ExplorationConfig:
    spec = get_spec("wifi24").model_copy(update=wire_spec_updates())
    return ExplorationConfig(
        spec=spec,
        evaluation_budget=1,
        seed=101,
        solver="nec2",
        proposal_space_version=MEANDER_PROPOSAL_SPACE.version,
    )


def test_gp_and_random_share_exact_meander_bounds() -> None:
    gp = GPExplorationAgent(_config())
    random = RandomSearchBaseline(_config())
    assert gp.proposal_space is MEANDER_PROPOSAL_SPACE
    assert random.proposal_space is MEANDER_PROPOSAL_SPACE
    assert gp.proposal_space.bounds == random.proposal_space.bounds


def test_meander_geometry_obeys_box_pitch_and_symmetry() -> None:
    geometry = build_meander_dipole(_parameters(), "test")
    xs = [vertex[0] for vertex in geometry.vertices]
    ys = [vertex[1] for vertex in geometry.vertices]
    assert max(xs) - min(xs) <= WIRE_BOX_SIZE_M
    assert max(ys) - min(ys) <= WIRE_BOX_SIZE_M
    assert float(geometry.metadata["minimum_pitch_m"]) >= MINIMUM_PITCH_M
    points = {tuple(round(value, 12) for value in vertex) for vertex in geometry.vertices}
    assert all(tuple(-value for value in point) in points for point in points)


@pytest.mark.asyncio
async def test_invalid_meander_is_rejected_without_consuming_budget(
    tmp_path: Path,
) -> None:
    config = _config()
    proposal = _proposal_from_parameters(config, _parameters(), "gp")
    invalid_geometry = proposal.geometry.model_copy(deep=True)
    invalid_geometry.vertices[2][0] = WIRE_BOX_SIZE_M
    invalid = GeometryProposal(
        geometry=invalid_geometry,
        parameters=proposal.parameters,
        proposer=proposal.proposer,
    )
    logger = ExplorationLogger(config=config, runs_root=tmp_path, run_id="reject")
    environment = AntennaExplorationEnv(config, audit_logger=logger)
    with pytest.raises(ValueError, match="30 mm x boundary"):
        await environment.step(invalid)
    assert environment.budget_remaining == 1
    record = json.loads(logger.log_path.read_text(encoding="utf-8"))
    assert record["event_type"] == "rejected"
    assert record["budget_remaining"] == 1


@pytest.mark.asyncio
async def test_generated_short_terminal_is_a_logged_rejection(tmp_path: Path) -> None:
    config = _config()
    parameters = {**_parameters(), "terminal_ratio": 0.001}
    proposal = _proposal_from_parameters(config, parameters, "gp")
    logger = ExplorationLogger(
        config=config, runs_root=tmp_path, run_id="generated-reject"
    )
    environment = AntennaExplorationEnv(config, audit_logger=logger)
    with pytest.raises(ValueError, match="shorter than four wire radii"):
        await environment.step(proposal)
    assert environment.budget_remaining == 1
    payload = json.loads(logger.log_path.read_text(encoding="utf-8"))
    assert payload["event_type"] == "rejected"
    assert payload["proposal_parameters"] == parameters


def test_both_adapters_consume_same_native_centerline() -> None:
    geometry = build_meander_dipole(_parameters(), "test")
    spec = SimulationSpec(
        frequency_range=(2.4e9, 2.5e9),
        frequency_points=11,
        far_field_request=None,
    )
    nec2 = NEC2Adapter()
    nec_mesh = asyncio.run(nec2.mesh(geometry, spec))
    deck = nec2._build_nec_deck(nec_mesh, spec).to_bytes().decode("ascii")
    assert deck.count("GW ") == len(geometry.faces)
    assert " 5.00000E-05" in deck
    assert "EX 0 1 1" in deck

    openems = OpenEMSAdapter()
    openems_mesh = asyncio.run(openems.mesh(geometry, spec))
    xml_bytes, _ = openems._build_sim_xml(openems_mesh, spec)
    root = ET.fromstring(xml_bytes)
    metals = [
        item
        for item in root.findall(".//Metal")
        if item.get("Name", "").startswith("meander_wire_")
    ]
    assert len(metals) == len(geometry.faces) - 1
    assert root.find(".//LumpedElement") is not None


@pytest.mark.asyncio
async def test_wire_batch_resume_and_failure_isolation(tmp_path: Path) -> None:
    calls: list[str] = []

    async def mock_executor(
        record: BatchRunRecord, _runs_root: Path
    ) -> RunExecution:
        calls.append(record.run_key)
        return RunExecution(duration_seconds=0.1, steps_completed=record.budget)

    first = await run_wire_batch(
        "wire-test",
        repo_root=tmp_path,
        executor=mock_executor,
        duration_limit_seconds=10.0,
        choices=((2, (101,)),),
    )
    assert len(calls) == 3
    assert all(record.status == "completed" for record in first.runs)
    document = load_batch_config(
        tmp_path / "runs" / "batch_wire-test" / "config.json"
    )
    assert document.config.solver == "nec2"
    assert document.config.experiment_kind == "wire"
    assert document.config.proposal_space == MEANDER_PROPOSAL_SPACE

    resumed = await run_wire_batch(
        "wire-test",
        repo_root=tmp_path,
        executor=mock_executor,
        duration_limit_seconds=10.0,
        choices=((2, (101,)),),
    )
    assert resumed == first
    assert len(calls) == 3

    failure_calls: list[str] = []

    async def failing_executor(
        record: BatchRunRecord, _runs_root: Path
    ) -> RunExecution:
        failure_calls.append(record.run_key)
        if record.agent == "gp":
            raise RuntimeError("synthetic wire failure")
        return RunExecution(duration_seconds=0.1, steps_completed=record.budget)

    failed = await run_wire_batch(
        "wire-failure-test",
        repo_root=tmp_path,
        executor=failing_executor,
        duration_limit_seconds=10.0,
        choices=((2, (101,)),),
    )
    by_agent = {record.agent: record for record in failed.runs}
    assert by_agent["gp"].status == "failed"
    assert by_agent["random"].status == "completed"
    assert failure_calls[-1] == "wifi24:random:101"


def _write_fake_wire_run(
    artifacts_root: Path,
    record: BatchRunRecord,
    scores: tuple[float, ...],
) -> None:
    directory = artifacts_root / record.run_id
    directory.mkdir(parents=True)
    config = _config().model_copy(
        update={"evaluation_budget": len(scores), "seed": record.seed}
    )
    steps = [
        AuditStepRecord(
            run_id=record.run_id,
            step_index=index,
            timestamp=datetime.now(UTC),
            geometry_summary={},
            geometry_hash=f"{index + 1:064x}",
            solver_name="nec2",
            solver_mode="subprocess",
            metrics={
                "min_s11_db": -10.0 - index,
                "gain_dbi": 2.0,
                "realized_gain_dbi": 1.5,
                "vswr": 1.5,
            },
            score=score,
            seed=record.seed,
            config_hash="a" * 64,
            proposal_parameters=_parameters(),
            proposer=record.agent,
        )
        for index, score in enumerate(scores)
    ]
    log = "".join(record.model_dump_json() + "\n" for record in steps)
    (directory / "log.jsonl").write_text(log, encoding="utf-8", newline="\n")
    summary = RunSummary(
        run_id=record.run_id,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        seed=record.seed,
        config_hash="a" * 64,
        config=config.model_dump(mode="json"),
        steps_completed=len(steps),
        evaluation_budget=len(steps),
        solver_mode_counts={"subprocess": len(steps)},
        top_designs=sorted(steps, key=lambda item: item.score, reverse=True)[:3],
    )
    (directory / "summary.json").write_text(
        summary.model_dump_json(), encoding="utf-8", newline="\n"
    )


def test_wire_analysis_means_pairs_and_best_so_far(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    specifications = {"wifi24": get_spec("wifi24").model_copy(update=wire_spec_updates())}
    config = BatchConfig(
        batch_id="wire-analysis",
        specs=specifications,
        solver="nec2",
        budget=3,
        seeds=(101, 202),
        proposal_space=MEANDER_PROPOSAL_SPACE,
        discovery_policy=_config().discovery_policy,
        calibration_seconds={"wifi24": 0.1},
        duration_limit_seconds=10.0,
        estimated_total_seconds=1.3,
        selection_reason="unit test",
        experiment_kind="wire",
    )
    config_hash_value = batch_config_hash(config)
    document = BatchConfigDocument(config_hash=config_hash_value, config=config)
    definitions = (
        ("classic", 0, (0.4,)),
        ("gp", 101, (0.5, 0.7, 0.6)),
        ("gp", 202, (0.4, 0.8, 0.75)),
        ("random", 101, (0.5, 0.55, 0.54)),
        ("random", 202, (0.65, 0.60, 0.62)),
    )
    records: list[BatchRunRecord] = []
    artifacts_root = tmp_path / "artifacts"
    for agent, seed, scores in definitions:
        run_id = f"wire-analysis-wifi24-{agent}-s{seed}"
        record = BatchRunRecord(
            run_key=f"wifi24:{agent}:{seed}",
            run_id=run_id,
            spec_name="wifi24",
            agent=agent,
            seed=seed,
            budget=len(scores),
            status="completed",
            duration_seconds=0.1,
            started_at=now,
            finished_at=now,
        )
        records.append(record)
        _write_fake_wire_run(artifacts_root, record, scores)
    state = BatchState(
        batch_id="wire-analysis",
        config_hash=config_hash_value,
        runs=tuple(records),
    )
    summary = build_wire_analysis(state, document, artifacts_root=artifacts_root)
    assert summary.classic_score == 0.4
    aggregates = {item.agent: item for item in summary.aggregates}
    assert aggregates["gp"].mean_best_score == pytest.approx(0.75)
    assert aggregates["random"].mean_best_score == pytest.approx(0.60)
    pairs = {item.seed: item for item in summary.paired_differences}
    assert pairs[101].difference == pytest.approx(0.15)
    assert pairs[202].difference == pytest.approx(0.15)
    gp_101 = next(
        row for row in summary.rows if row.agent == "gp" and row.seed == 101
    )
    assert gp_101.best_so_far == pytest.approx((0.5, 0.7, 0.7))
    assert gp_101.evaluations_to_best == 2


def test_native_wire_deck_uses_adaptive_odd_segmentation() -> None:
    geometry = build_meander_dipole(_parameters(), "test")
    spec = SimulationSpec(
        frequency_range=(2.4e9, 2.5e9),
        frequency_points=11,
        far_field_request=None,
    )
    adapter = NEC2Adapter()
    mesh = asyncio.run(adapter.mesh(geometry, spec))
    deck = adapter._build_nec_deck(mesh, spec).to_bytes().decode("ascii")
    segment_counts = [
        int(line.split()[2]) for line in deck.splitlines() if line.startswith("GW")
    ]
    assert segment_counts[0] == 1
    assert max(segment_counts) > 1
    assert all(count % 2 == 1 for count in segment_counts)


@pytest.mark.asyncio
async def test_gp_resamples_when_geometry_construction_is_rejected() -> None:
    class RejectOnceGP(GPExplorationAgent):
        attempts = 0

        def propose(self) -> GeometryProposal:
            self.attempts += 1
            if self.attempts == 1:
                raise ValueError("synthetic proposal-layer rejection")
            return _proposal_from_parameters(self.config, _parameters(), "gp")

    class OneStepEnvironment:
        budget_remaining = 1

        async def step(self, proposal: GeometryProposal) -> StepResult:
            self.budget_remaining = 0
            return StepResult(
                step_index=0,
                timestamp=datetime.now(UTC),
                solver_name="nec2",
                solver_mode="subprocess",
                metrics={"composite_score": 0.5},
                score=0.5,
                geometry_hash="a" * 64,
                geometry_summary={},
                proposal_parameters=proposal.parameters,
                proposer=proposal.proposer,
            )

    agent = RejectOnceGP(_config())
    environment = OneStepEnvironment()
    results = await agent.run(environment)  # type: ignore[arg-type]
    assert agent.attempts == 2
    assert len(results) == 1
