"""Mock-only tests for the superseding paired-state execution layer."""

from __future__ import annotations

import ast
import hashlib
import json
import uuid
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from yaf_ai.exploration.paired_agents import (
    ES_INITIAL_SIGMA,
    PairedRandomProposer,
    PairedRestartedES,
    decode_normalized,
    encode_warm_parent,
)
from yaf_ai.exploration.paired_cross_check import (
    CrossCheckNotAuthorizedError,
    run_paired_cross_check,
)
from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    HardwareSpec,
    PairedEvaluation,
    PairedProposal,
    SearchCurve,
    StateControl,
    StateLabel,
    audit_trajectory,
    build_state_geometry,
    iter_manual_pairs,
)
from yaf_ai.exploration.paired_preflight import calculate_budget
from yaf_ai.exploration.paired_runner import (
    PREFLIGHT_RUN_ID_PREFIX,
    PairedEvaluationRecord,
    PairedRunConfig,
    PairedRunError,
    _evaluation,
    freeze_candidate,
    load_paired_evaluations,
    run_paired_adaptive,
)
from yaf_ai.exploration.paired_solver import (
    NEC2_SEGMENTS_PER_WAVELENGTH,
    PairedNEC2Solver,
    PairedSolverError,
)
from yaf_core.domain.geometry import Geometry, Mesh
from yaf_core.domain.simulation import SimulationResult, SimulationSpec, SParamResult
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter


def _legal_proposals(count: int, proposer: str = "test") -> tuple[PairedProposal, ...]:
    selected: list[PairedProposal] = []
    for _hardware_index, _pair_index, proposal in iter_manual_pairs():
        proposal = proposal.model_copy(update={"proposer": proposer})
        if audit_trajectory(proposal).valid:
            selected.append(proposal)
            if len(selected) == count:
                return tuple(selected)
    raise AssertionError("manual grid did not contain enough legal proposals")


def _invalid_proposal() -> PairedProposal:
    return PairedProposal(
        hardware=HardwareSpec(
            turn_count=6,
            feed_gap_ratio_ppm=20_000,
            terminal_ratio_ppm=1_000_000,
        ),
        state_a=StateControl(
            state="A", total_wire_length_um=50_000, span_ratio_ppm=1_000_000
        ),
        state_b=StateControl(
            state="B", total_wire_length_um=22_000, span_ratio_ppm=1_000_000
        ),
        proposer="invalid",
    )


def _curve(state: StateLabel, depth_db: float = -8.0) -> SearchCurve:
    frequencies = STATE_A_FREQUENCIES_HZ if state == "A" else STATE_B_FREQUENCIES_HZ
    values = [-0.1] * len(frequencies)
    values[50] = depth_db
    return SearchCurve(
        solver_name="nec2",
        solver_mode="subprocess",
        frequency_hz=frequencies,
        s11_db=tuple(values),
        realized_gain_dbi=None,
    )


def _evaluation_with_score(
    proposal: PairedProposal,
    score: float,
) -> PairedEvaluation:
    evaluation = _evaluation(proposal, _curve("A"), _curve("B"))
    metrics = evaluation.metrics.model_copy(
        update={"search_score": score, "base_score": min(score, 1.0)}
    )
    return evaluation.model_copy(update={"metrics": metrics})


class FakeNEC2Adapter:
    """Records calls while returning deterministic S11-only subprocess results."""

    def __init__(self, *, mode: str = "subprocess", drop_mesh_radius: bool = False) -> None:
        self.mode = mode
        self.drop_mesh_radius = drop_mesh_radius
        self.mesh_calls = 0
        self.solve_calls = 0
        self.specs: list[SimulationSpec] = []

    async def mesh(self, geometry: Geometry, spec: SimulationSpec) -> Mesh:
        self.mesh_calls += 1
        self.specs.append(spec)
        metadata = dict(geometry.metadata)
        if self.drop_mesh_radius:
            metadata.pop("wire_radius_m", None)
        return Mesh(
            geometry_id=geometry.id,
            solver_name="nec2",
            nodes=geometry.vertices,
            elements=geometry.faces,
            element_type="wire",
            metadata=metadata,
        )

    async def solve(self, _mesh: Mesh, spec: SimulationSpec) -> SimulationResult:
        self.solve_calls += 1
        frequencies = [
            spec.frequency_range[0]
            + index
            * (spec.frequency_range[1] - spec.frequency_range[0])
            / (spec.frequency_points - 1)
            for index in range(spec.frequency_points)
        ]
        return SimulationResult(
            job_id=uuid.uuid4(),
            solver_name="nec2",
            solver_version="test",
            status="success",
            s_params=SParamResult(
                frequency=frequencies,
                s_matrix=[[[0.1 + 0.0j]]] * spec.frequency_points,
            ),
            solver_metadata={"solver_mode": self.mode},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "frequencies", "expected_range"),
    (
        ("A", STATE_A_FREQUENCIES_HZ, (2.400e9, 2.500e9)),
        ("B", STATE_B_FREQUENCIES_HZ, (5.725e9, 5.875e9)),
    ),
)
async def test_paired_solver_uses_exact_band_density_radius_and_s11_only(
    state: StateLabel,
    frequencies: tuple[float, ...],
    expected_range: tuple[float, float],
) -> None:
    proposal = _legal_proposals(1)[0]
    control = proposal.state_a if state == "A" else proposal.state_b
    geometry = build_state_geometry(proposal.hardware, control)
    fake = FakeNEC2Adapter()
    solver = PairedNEC2Solver(cast(NEC2Adapter, fake))
    curve = await solver(geometry, state, frequencies)
    spec = fake.specs[0]
    assert curve.frequency_hz == frequencies
    assert curve.realized_gain_dbi is None
    assert curve.solver_mode == "subprocess"
    assert spec.frequency_range == expected_range
    assert spec.frequency_points == 101
    assert spec.solver_settings == {
        "nec2_segments_per_wavelength": NEC2_SEGMENTS_PER_WAVELENGTH
    }
    assert NEC2_SEGMENTS_PER_WAVELENGTH == 20
    assert spec.far_field_request is None
    assert geometry.metadata["wire_radius_m"] == proposal.hardware.wire_radius_um * 1e-6


@pytest.mark.asyncio
async def test_solver_rejects_missing_radius_and_mutated_geometry_before_nec2() -> None:
    proposal = _legal_proposals(1)[0]
    original = build_state_geometry(proposal.hardware, proposal.state_a)
    fake = FakeNEC2Adapter()
    solver = PairedNEC2Solver(cast(NEC2Adapter, fake))
    missing_metadata = dict(original.metadata)
    missing_metadata.pop("wire_radius_m")
    missing = original.model_copy(update={"metadata": missing_metadata})
    with pytest.raises(PairedSolverError, match="wire_radius_m"):
        await solver(missing, "A", STATE_A_FREQUENCIES_HZ)
    mutated_vertices = [list(row) for row in original.vertices]
    mutated_vertices[0][0] += 1e-6
    mutated = original.model_copy(update={"vertices": mutated_vertices})
    with pytest.raises(PairedSolverError, match="frozen quantized identity"):
        await solver(mutated, "A", STATE_A_FREQUENCIES_HZ)
    assert fake.mesh_calls == 0
    assert fake.solve_calls == 0


@pytest.mark.asyncio
async def test_solver_rejects_mesh_radius_loss_and_non_subprocess() -> None:
    proposal = _legal_proposals(1)[0]
    geometry = build_state_geometry(proposal.hardware, proposal.state_a)
    lost = FakeNEC2Adapter(drop_mesh_radius=True)
    with pytest.raises(PairedSolverError, match="silently lost"):
        await PairedNEC2Solver(cast(NEC2Adapter, lost))(
            geometry, "A", STATE_A_FREQUENCIES_HZ
        )
    assert lost.solve_calls == 0
    analytical = FakeNEC2Adapter(mode="fallback_analytical")
    with pytest.raises(PairedSolverError, match="requires subprocess"):
        await PairedNEC2Solver(cast(NEC2Adapter, analytical))(
            geometry, "A", STATE_A_FREQUENCIES_HZ
        )


def test_solver_imports_no_legacy_wire_or_anchor_radius_sources() -> None:
    source = Path("yaf_ai/exploration/paired_solver.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    forbidden = ("wire", "day65", "semifinal_anchor", "semifinal_rod_anchor")
    assert not any(any(token in module for token in forbidden) for module in imported)


def test_literal_false_config_and_cross_check_lock() -> None:
    with pytest.raises(ValidationError):
        PairedRunConfig(
            run_id="illegal-crosscheck",
            agent="manual",
            seed=0,
            evaluation_budget=1,
            anchor_released=False,
            openems_cross_check_authorized=True,
            preregistration_commit="374fb05",
        )
    with pytest.raises(CrossCheckNotAuthorizedError):
        run_paired_cross_check()


def test_random_seed_101_first_ten_proposal_fields_are_frozen() -> None:
    proposer = PairedRandomProposer(101)
    actual = []
    for _index in range(10):
        proposal = proposer.propose()
        actual.append(
            (
                proposal.hardware.turn_count,
                proposal.hardware.feed_gap_ratio_ppm,
                proposal.hardware.terminal_ratio_ppm,
                proposal.state_a.total_wire_length_um,
                proposal.state_a.span_ratio_ppm,
                proposal.state_b.total_wire_length_um,
                proposal.state_b.span_ratio_ppm,
            )
        )
    assert actual == [
        (6, 34377, 784805, 79564, 830639, 43223, 968640),
        (4, 58927, 224524, 90275, 923415, 32834, 767393),
        (6, 42945, 390308, 67734, 916474, 29982, 881819),
        (4, 22208, 250409, 92048, 956357, 37348, 872941),
        (6, 53610, 245067, 78377, 989428, 40069, 848644),
        (4, 40713, 901893, 85715, 855553, 32627, 782154),
        (4, 29161, 93132, 54564, 811798, 38080, 803004),
        (5, 44105, 966265, 72910, 945887, 22803, 914706),
        (6, 21895, 907650, 57789, 922060, 22581, 774752),
        (3, 56053, 782889, 83089, 915870, 28757, 886745),
    ]


@pytest.mark.parametrize(
    ("u", "turns"),
    ((0.0, 3), (0.25, 4), (0.5, 5), (0.75, 6), (1.0, 6)),
)
def test_turn_bins_and_half_up_quantization(u: float, turns: int) -> None:
    values = [u, 0.0125125, 0.0000005, 0.5, 0.5, 0.5, 0.5]
    proposal = decode_normalized(values, "test")
    assert proposal.hardware.turn_count == turns
    assert proposal.hardware.feed_gap_ratio_ppm == 20_501
    assert proposal.hardware.terminal_ratio_ppm == 1
    assert proposal.state_a.total_wire_length_um == 75_000
    assert proposal.state_b.total_wire_length_um == 33_500
    assert proposal.state_a.span_ratio_ppm == 880_000
    assert proposal.state_b.span_ratio_ppm == 880_000


def _next_valid(es: PairedRestartedES) -> PairedProposal:
    while True:
        proposal = es.propose()
        if audit_trajectory(proposal).valid:
            return proposal
        sigma = es.sigma
        es.reject(proposal)
        assert es.sigma == sigma


def test_es_tie_stagnation_block_adaptation_and_restart_reset() -> None:
    es = PairedRestartedES(202)
    first = _next_valid(es)
    es.observe(_evaluation_with_score(first, 0.5))
    parent_hash = es.parent_pair_hash
    tied = _next_valid(es)
    es.observe(_evaluation_with_score(tied, 0.5))
    assert es.parent_pair_hash == parent_hash
    assert es.consecutive_non_improvements == 1
    for _index in range(19):
        child = _next_valid(es)
        es.observe(_evaluation_with_score(child, 0.5))
    assert es.sigma == pytest.approx(ES_INITIAL_SIGMA / 1.5)
    for _index in range(55):
        child = _next_valid(es)
        es.observe(_evaluation_with_score(child, 0.5))
    assert es.restart_pending
    restart = _next_valid(es)
    es.observe(_evaluation_with_score(restart, 0.4))
    assert not es.restart_pending
    assert es.sigma == ES_INITIAL_SIGMA
    assert es.consecutive_non_improvements == 0


def test_warm_parent_encode_decode_round_trip() -> None:
    parent = _legal_proposals(1, "manual")[0]
    encoded = encode_warm_parent(parent)
    rebuilt = decode_normalized(encoded.tolist(), "es")
    assert rebuilt.hardware == parent.hardware
    assert rebuilt.state_a == parent.state_a
    assert rebuilt.state_b == parent.state_b


class SequenceProposer:
    """Deterministic test proposer whose first event is a rejection."""

    def __init__(self) -> None:
        self._proposals = (_invalid_proposal(), *_legal_proposals(2, "sequence"))
        self._index = 0

    def propose(self) -> PairedProposal:
        proposal = self._proposals[self._index]
        self._index += 1
        return proposal

    def observe(self, _evaluation: PairedEvaluation) -> None:
        return

    def reject(self, _proposal: PairedProposal) -> None:
        return


class InterruptibleSolver:
    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    async def __call__(
        self,
        _geometry: Geometry,
        state: StateLabel,
        _frequencies: tuple[float, ...],
    ) -> SearchCurve:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("injected adaptive interruption")
        return _curve(state)


def _adaptive_config(run_id: str) -> PairedRunConfig:
    return PairedRunConfig(
        run_id=run_id,
        agent="random",
        seed=303,
        evaluation_budget=2,
        anchor_released=False,
        openems_cross_check_authorized=False,
        preregistration_commit="374fb05",
    )


@pytest.mark.asyncio
async def test_adaptive_resume_replays_rejection_and_evaluation(tmp_path: Path) -> None:
    config = _adaptive_config("adaptive-resume")
    with pytest.raises(RuntimeError, match="adaptive interruption"):
        await run_paired_adaptive(
            config=config,
            proposer=SequenceProposer(),
            solver=InterruptibleSolver(fail_on_call=3),
            runs_root=tmp_path,
        )
    rows = [
        json.loads(line)
        for line in (tmp_path / config.run_id / "log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["event_type"] for row in rows] == [
        "paired_rejection",
        "paired_evaluation",
    ]
    summary = await run_paired_adaptive(
        config=config,
        proposer=SequenceProposer(),
        solver=InterruptibleSolver(),
        runs_root=tmp_path,
    )
    assert summary.status == "completed"
    assert summary.steps_completed == 2
    assert summary.rejected_proposals == 1
    assert summary.proposal_attempts == 3
    assert summary.verdict_ceiling == "insufficient_evidence"
    assert len(load_paired_evaluations(tmp_path / config.run_id / "log.jsonl")) == 2


def test_preflight_higher_quantile_and_budget_boundaries() -> None:
    p95, raw, budget, classification = calculate_budget(
        tuple(float(index) for index in range(1, 21))
    )
    assert p95 == 20.0
    assert raw == 168
    assert budget == 168
    assert classification == "exploratory_small_sample"
    assert calculate_budget((1.0,) * 20)[2:] == (
        300,
        "three_seed_descriptive_statistics",
    )
    assert calculate_budget((16.0,) * 20)[2:] == (
        210,
        "three_seed_descriptive_statistics",
    )
    assert calculate_budget((42.0,) * 20)[2:] == (
        80,
        "exploratory_small_sample",
    )
    assert calculate_budget((43.0,) * 20)[2:] == (
        78,
        "infeasible_within_submission_window",
    )


def test_preflight_script_has_no_formal_runner_calls() -> None:
    source = Path("scripts/paired_preflight.py").read_text(encoding="utf-8")
    assert "run_paired_sequence" not in source
    assert "run_paired_adaptive" not in source


def test_preflight_run_is_excluded_from_candidate_freeze() -> None:
    proposal = _legal_proposals(1)[0]
    evaluation = _evaluation_with_score(proposal, 0.5)
    timestamp = __import__("datetime").datetime.now(__import__("datetime").UTC)
    preflight = PairedEvaluationRecord(
        run_id=PREFLIGHT_RUN_ID_PREFIX,
        step_index=0,
        proposal_index=0,
        timestamp=timestamp,
        proposer="manual",
        proposal=proposal,
        evaluation=evaluation.model_copy(
            update={
                "metrics": evaluation.metrics.model_copy(
                    update={"base_score": 0.999, "valid_pair_search": True}
                )
            }
        ),
    )
    regular = preflight.model_copy(
        update={
            "run_id": "semifinal-random-s101",
            "evaluation": evaluation,
        }
    )
    assert freeze_candidate((preflight, regular)).run_id == regular.run_id
    with pytest.raises(PairedRunError, match="non-agent exclusion"):
        freeze_candidate((preflight,))


def test_frozen_anchor_archives_retain_exact_sha256() -> None:
    expected = {
        "semifinal-wifi58-meander-renderer-anchor-r1-combined": (
            "937bd9d53a992a7bfce54d886652291fbac49c366f8fd617d4681f5ff4258b89",
            "61d012118b489634f9e04c4c5a02ada6532edbf3e9088f68806376b6b07f68c7",
        ),
        "semifinal-wifi58-meander-renderer-anchor-r2-combined": (
            "8d8387a9859417d6e9f62c07a385ba4d6a89e204e579d6c0359ddeb3b241de2c",
            "5c0987c439f21147e187cbc630870b57aaea3e6736569d05d28b232fe2dd7871",
        ),
        "semifinal-wifi58-meander-renderer-anchor-r3-combined": (
            "0e9da50876fa679870160ba9349a8391c18d7917355d7cef50177899bb967a9f",
            "d5ac661dc0251d0e7dcecf7a88d967a2c510e568e3338a45c5e84399254f67a9",
        ),
        "semifinal-wifi58-rod-renderer-anchor-r1-combined": (
            "39414489ba7b34f8b94526f03c657741ce879b2d521a4061df58b93b802c699f",
            "152710277aa5f8b4586185a0a00fd77d2d0d1ebf9907d3b130fe0e0972a06d0e",
        ),
    }
    for run_id, (log_hash, summary_hash) in expected.items():
        run_directory = Path("artifacts/runs") / run_id
        assert hashlib.sha256((run_directory / "log.jsonl").read_bytes()).hexdigest() == log_hash
        assert (
            hashlib.sha256((run_directory / "summary.json").read_bytes()).hexdigest()
            == summary_hash
        )
