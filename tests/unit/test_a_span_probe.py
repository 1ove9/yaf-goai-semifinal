"""Solver-free invariants for the preregistered A-span support causal probe."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from yaf_ai.analysis import a_span_probe as span_analysis
from yaf_ai.exploration import a_span_probe as probe
from yaf_ai.exploration.paired_b_completion_coordinates import get_frozen_parent
from yaf_ai.exploration.paired_b_completion_gates import canonical_curve_sha256
from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    SearchCurve,
    StateControl,
    minimum_nonadjacent_clearance,
    score_state_curve,
    state_geometry_hash,
    validate_paired_geometry,
)
from yaf_ai.exploration.paired_runner import PairedEvaluationRecord
from yaf_core.domain.geometry import Geometry

EXPECTED_SOURCE_UNITS = (
    (
        "p01",
        101,
        "semifinal-paired-b-completion-p01-es-s101",
        286,
        "fb98e3539cb47e05d15fd42c16ddbb8a9f6ecf55c51f4b3ea942bbd295835bf3",
        71_001,
        981_858,
        0.24551036781205307,
    ),
    (
        "p01",
        202,
        "semifinal-paired-b-completion-p01-es-s202",
        24,
        "cc678757386ca5cbe25c34b818a151e4556b40a12e4a7ff1f7a4ff02638b40b9",
        70_973,
        992_531,
        0.23755180106137028,
    ),
    (
        "p01",
        303,
        "semifinal-paired-b-completion-p01-es-s303",
        265,
        "59a7e7df8fe7b8c3e6a07333e84ef12099886c5971a9815891ef63e1d041f259",
        70_775,
        999_881,
        0.23010531242953516,
    ),
    (
        "p01",
        404,
        "semifinal-paired-b-completion-p01-es-s404",
        209,
        "d9aa2b8bad62c71b6da2cc988c131de1415333ddbcf2085d53f65c004d551e96",
        70_816,
        999_368,
        0.23092841432431088,
    ),
    (
        "p01",
        505,
        "semifinal-paired-b-completion-p01-es-s505",
        109,
        "6ace3129ef9005e3d3d2ea804e4799f41145a7bda2719f470dcf9f7fe5b1009b",
        70_856,
        999_628,
        0.2312005376616786,
    ),
    (
        "p02",
        101,
        "semifinal-paired-b-completion-p02-es-s101",
        164,
        "754e66368ce1de867994b541a21aa5cbb07d6ef65b13536c2a00cd345d64a8c8",
        70_860,
        999_705,
        0.23269669380050187,
    ),
    (
        "p02",
        202,
        "semifinal-paired-b-completion-p02-es-s202",
        283,
        "efa222ede3e10524564cf438b57c4a45e2def304836db7476aefde8d2f03aece",
        70_825,
        999_581,
        0.23237516833229716,
    ),
    (
        "p02",
        303,
        "semifinal-paired-b-completion-p02-es-s303",
        204,
        "5f68b76c738956d271dc194022591a1a157a552416d9fde997a6f3273f72e239",
        70_788,
        999_102,
        0.23229511875494777,
    ),
    (
        "p02",
        404,
        "semifinal-paired-b-completion-p02-es-s404",
        268,
        "9666760505ce32f0aa3ce7138f449931895ece5ac252bd089d5a9c2e47131733",
        70_824,
        999_816,
        0.23219805776354677,
    ),
    (
        "p02",
        505,
        "semifinal-paired-b-completion-p02-es-s505",
        293,
        "0216ff4394e6ec4f42e26189aa50b86985c681cde410b4b4b499276a289995fc",
        70_833,
        999_921,
        0.23223486715570588,
    ),
)

EXPECTED_RUNTIME_PATH_BLOBS = {
    "yaf_ai/exploration/paired_meander.py": ("98fd67154d5f6a512fdf46b99da1fc273ba8eced"),
    "yaf_ai/exploration/paired_solver.py": ("96efa9fe3e755fbca9b31315d96a330bef7291b9"),
    "yaf_ai/exploration/paired_runner.py": ("d2ece9096be6daa86de6b281bb64a8b1150c782e"),
    "yaf_ai/exploration/paired_b_completion_coordinates.py": (
        "a1679885fbc01b33e41de7d769dd1c9cdd3b60df"
    ),
    "yaf_ai/exploration/paired_b_completion_gates.py": ("54fe49c9825f9e1df8147a28b2be7a128a7bfd5f"),
    "yaf_ai/analysis/paired_b_completion.py": ("19d30cd88730ed1354abbdebed9c0ea397fec406"),
    "scripts/archive_run.py": "b532036632d9603c500313fb2a481a009da2c6e7",
}

EXPECTED_WIDTH_RANGES_M = {
    0: (0.029945750, 0.030486440),
    50_000: (0.031445750, 0.031986440),
    100_000: (0.032945750, 0.033486440),
}

REPO_ROOT = Path(__file__).resolve().parents[2]


def _source_signature(unit: probe.FrozenSourceUnit) -> tuple[object, ...]:
    return (
        unit.parent_id,
        unit.seed,
        unit.source_run_id,
        unit.source_step_index,
        unit.source_pair_hash,
        unit.state_a_total_wire_length_um,
        unit.state_a_span_ratio_ppm,
        unit.state_a_loss,
    )


def _full_centerline_width(geometry: Geometry) -> float:
    return 2.0 * max(abs(float(vertex[0])) for vertex in geometry.vertices)


def _source_record(unit: probe.FrozenSourceUnit) -> PairedEvaluationRecord:
    log_path = REPO_ROOT / "artifacts" / "runs" / unit.source_run_id / probe.LOG_FILENAME
    lines = log_path.read_bytes().splitlines()
    record = PairedEvaluationRecord.model_validate_json(lines[unit.source_step_index])
    assert record.run_id == unit.source_run_id
    assert record.step_index == unit.source_step_index
    assert record.proposal_index == unit.source_proposal_index
    assert record.evaluation.pair_hash == unit.source_pair_hash
    return record


def _synthetic_state_a_curve(reflected_power_loss: float) -> SearchCurve:
    selected_index = 50
    s11_db = [-1.0] * len(STATE_A_FREQUENCIES_HZ)
    s11_db[selected_index] = 10.0 * math.log10(reflected_power_loss)
    return SearchCurve(
        solver_name="nec2",
        solver_mode="subprocess",
        frequency_hz=STATE_A_FREQUENCIES_HZ,
        s11_db=tuple(s11_db),
        realized_gain_dbi=None,
    )


def _synthetic_probe_events() -> tuple[dict[str, object], ...]:
    records = tuple(_source_record(unit) for unit in probe.FROZEN_SOURCE_UNITS)
    events: list[dict[str, object]] = []
    for call_index, unit_index in enumerate((0, 5)):
        unit = probe.FROZEN_SOURCE_UNITS[unit_index]
        curve = records[unit_index].evaluation.state_b_curve
        events.append(
            {
                "event_type": "a_span_probe_b_replay",
                "call_index": call_index,
                "solver_mode": "subprocess",
                "parent_id": unit.parent_id,
                "canonical_curve_sha256": canonical_curve_sha256(curve.model_dump(mode="json")),
                "state_b_curve": curve.model_dump(mode="json"),
                "timestamp": "2026-09-01T00:00:00Z",
            }
        )

    positive_losses = {50_000: 0.20, 100_000: 0.18}
    for dose_index, dose_ppm in enumerate(probe.DOSES_PPM):
        for unit_index, unit in enumerate(probe.FROZEN_SOURCE_UNITS):
            call_index = 2 + dose_index * len(probe.FROZEN_SOURCE_UNITS) + unit_index
            curve = (
                records[unit_index].evaluation.state_a_curve
                if dose_ppm == 0
                else _synthetic_state_a_curve(positive_losses[dose_ppm])
            )
            metric = score_state_curve(curve, "A")
            trajectory = probe.build_diagnostic_trajectory(unit, dose_ppm)
            hybrid_loss = max(metric.reflected_power_fraction, unit.frozen_b_loss)
            valid = trajectory.audit.valid and metric.valid_search
            events.append(
                {
                    "event_type": "a_span_probe_a_evaluation",
                    "call_index": call_index,
                    "solver_mode": "subprocess",
                    "parent_id": unit.parent_id,
                    "seed": unit.seed,
                    "source_pair_hash": unit.source_pair_hash,
                    "source_run_id": unit.source_run_id,
                    "source_step_index": unit.source_step_index,
                    "source_proposal_index": unit.source_proposal_index,
                    "dose_ppm": dose_ppm,
                    "effective_a_span_ratio_ppm": (unit.state_a_span_ratio_ppm + dose_ppm),
                    "state_a_curve": curve.model_dump(mode="json"),
                    "canonical_curve_sha256": canonical_curve_sha256(curve.model_dump(mode="json")),
                    "frozen_b_loss": unit.frozen_b_loss,
                    "trajectory_valid": trajectory.audit.valid,
                    "actual_full_width_mm": (trajectory.audit.actual_full_width_m * 1_000.0),
                    "minimum_clearance_mm": (trajectory.audit.minimum_clearance_m * 1_000.0),
                    "state_a_selected_index": metric.selected_index,
                    "state_a_selected_frequency_hz": metric.selected_frequency_hz,
                    "state_a_selected_s11_db": metric.selected_s11_db,
                    "state_a_loss": metric.reflected_power_fraction,
                    "state_a_valid": metric.valid_search,
                    "hybrid_loss": hybrid_loss,
                    "diagnostic_pair_valid": valid,
                    "diagnostic_reference_crossing": (
                        valid and hybrid_loss <= span_analysis.L_REQUIRED
                    ),
                    "source_box_size_um": 40_000,
                    "counterfactual_only": dose_ppm > 0,
                    "outside_original_span_support": dose_ppm > 0,
                    "physical_40mm_trajectory_valid": trajectory.audit.valid,
                    "eligible_for_original_candidate_pool": False,
                    "eligible_for_original_h1_h2": False,
                    "eligible_for_original_agent_comparison": False,
                    "timestamp": "2026-09-01T00:00:00Z",
                }
            )
    assert len(events) == probe.PLANNED_CALLS
    return tuple(events)


def _write_probe_events(
    path: Path,
    events: tuple[dict[str, object], ...],
) -> None:
    payload = "".join(
        json.dumps(
            event,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
        for event in events
    ).encode("utf-8")
    assert payload.endswith(b"\n") and b"\r" not in payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _write_synthetic_probe_log(path: Path) -> tuple[dict[str, object], ...]:
    events = _synthetic_probe_events()
    _write_probe_events(path, events)
    return events


def _complete_synthetic_summary(log_path: Path) -> probe.ProbeRunSummary:
    config = probe.ProbeRunConfig(
        source_commit=probe.SOURCE_COMMIT,
        preregistration_commit=probe.PREREGISTRATION_COMMIT,
        implementation_commit="a" * 40,
        execution_commit="b" * 40,
        implementation_blob="c" * 40,
        source_manifest_entry_count=probe.SOURCE_MANIFEST_ENTRY_COUNT,
        source_manifest_sha256=probe.SOURCE_MANIFEST_SHA256,
        preregistration_document_sha256=probe.PREREGISTRATION_DOCUMENT_SHA256,
        source_appendix_sha256=probe.SOURCE_APPENDIX_SHA256,
        source_report_sha256=probe.SOURCE_REPORT_SHA256,
        runtime_path_blobs={
            path.as_posix(): blob for path, blob in probe.RUNTIME_PATH_BLOBS.items()
        },
        source_units=probe.FROZEN_SOURCE_UNITS,
    )
    config_bytes = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    timestamp = datetime(2026, 9, 1, tzinfo=UTC)
    return probe.ProbeRunSummary(
        started_at=timestamp,
        finished_at=timestamp,
        config_hash=hashlib.sha256(config_bytes).hexdigest(),
        config=config,
        solver_mode_counts={"subprocess": 32},
        endpoint="span_support_sufficient_in_frozen_counterfactuals",
        high_dose_improvements=10,
        monotonic_responses=10,
        p01_crossings=5,
        p02_crossings=5,
        log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest(),
    )


def test_frozen_es_only_source_units_are_exact_and_uniquely_ordered() -> None:
    assert probe.STUDY_ID == "semifinal-a-span-support-causal-probe-v1"
    assert probe.DOSES_PPM == (0, 50_000, 100_000)
    assert tuple(_source_signature(unit) for unit in probe.FROZEN_SOURCE_UNITS) == (
        EXPECTED_SOURCE_UNITS
    )
    assert len(probe.FROZEN_SOURCE_UNITS) == 10
    assert len({(unit.parent_id, unit.seed) for unit in probe.FROZEN_SOURCE_UNITS}) == 10
    assert tuple(unit.parent_id for unit in probe.FROZEN_SOURCE_UNITS) == (
        ("p01",) * 5 + ("p02",) * 5
    )
    assert tuple(unit.seed for unit in probe.FROZEN_SOURCE_UNITS[:5]) == (
        101,
        202,
        303,
        404,
        505,
    )
    assert all("-es-" in unit.source_run_id for unit in probe.FROZEN_SOURCE_UNITS)
    assert all(
        unit.source_step_index == unit.source_proposal_index for unit in probe.FROZEN_SOURCE_UNITS
    )


def test_solver_plan_is_the_exact_preregistered_32_call_order() -> None:
    plan = probe.build_solver_plan()
    expected: list[tuple[str, str, int | None, int | None]] = [
        ("b_replay", "p01", None, None),
        ("b_replay", "p02", None, None),
    ]
    expected.extend(
        ("a_probe", unit.parent_id, dose_ppm, source_unit_index)
        for dose_ppm in probe.DOSES_PPM
        for source_unit_index, unit in enumerate(probe.FROZEN_SOURCE_UNITS)
    )
    assert probe.PLANNED_CALLS == 32
    assert len(plan) == probe.PLANNED_CALLS
    assert [
        (call.event_kind, call.parent_id, call.dose_ppm, call.unit_index) for call in plan
    ] == expected
    assert tuple(call.call_index for call in plan) == tuple(range(32))
    assert sum(call.event_kind == "b_replay" for call in plan) == 2
    assert sum(call.event_kind == "a_probe" for call in plan) == 30


def test_all_630_geometries_are_legal_and_dose_zero_reconstructs_source() -> None:
    geometry_count = 0
    widths_by_dose: dict[int, list[float]] = defaultdict(list)
    minimum_pitch = math.inf
    minimum_clearance = math.inf

    for dose_ppm in probe.DOSES_PPM:
        for unit in probe.FROZEN_SOURCE_UNITS:
            built = probe.build_diagnostic_trajectory(unit, dose_ppm)
            proposal = built.proposal
            parent = get_frozen_parent(unit.parent_id)
            effective_span = unit.state_a_span_ratio_ppm + dose_ppm

            assert proposal.hardware == parent.hardware
            assert proposal.hardware.box_size_um == 40_000
            assert proposal.state_b == parent.state_b
            assert proposal.state_a_total_wire_length_um == unit.state_a_total_wire_length_um
            assert proposal.effective_a_span_ratio_ppm == effective_span
            assert built.audit.valid
            assert built.audit.point_count == 21
            assert len(built.geometries) == 21

            if dose_ppm == 0:
                source_state = StateControl(
                    state="A",
                    total_wire_length_um=unit.state_a_total_wire_length_um,
                    span_ratio_ppm=unit.state_a_span_ratio_ppm,
                )
                source_hash = state_geometry_hash(
                    proposal.hardware,
                    source_state,
                    built.geometries[0],
                )
                assert source_hash == unit.state_a_geometry_sha256
            else:
                assert effective_span > 1_000_000
                with pytest.raises(ValidationError):
                    StateControl(
                        state="A",
                        total_wire_length_um=unit.state_a_total_wire_length_um,
                        span_ratio_ppm=effective_span,
                    )

            widths_by_dose[dose_ppm].append(_full_centerline_width(built.geometries[0]))
            for geometry in built.geometries:
                geometry_count += 1
                validate_paired_geometry(geometry)
                assert max(abs(float(vertex[0])) for vertex in geometry.vertices) <= (0.020 + 1e-12)
                assert max(abs(float(vertex[1])) for vertex in geometry.vertices) <= (0.020 + 1e-12)
                pitch = float(geometry.metadata["minimum_pitch_m"])
                clearance = minimum_nonadjacent_clearance(geometry)
                minimum_pitch = min(minimum_pitch, pitch)
                minimum_clearance = min(minimum_clearance, clearance)
                assert pitch >= 0.0015 - 1e-12
                assert clearance >= 0.0002 - 1e-12
                for start, end in geometry.faces:
                    assert math.dist(geometry.vertices[start], geometry.vertices[end]) >= (
                        0.0002 - 1e-12
                    )
                target = float(geometry.metadata["target_total_wire_length_m"])
                realized = sum(
                    math.dist(geometry.vertices[start], geometry.vertices[end])
                    for start, end in geometry.faces
                )
                assert realized == pytest.approx(target, abs=1e-9)

    assert geometry_count == 630
    assert minimum_pitch == pytest.approx(0.003612745, abs=1e-12)
    assert minimum_clearance == pytest.approx(0.000203343, abs=1e-12)
    for expected_dose, expected_range in EXPECTED_WIDTH_RANGES_M.items():
        assert min(widths_by_dose[expected_dose]) == pytest.approx(expected_range[0], abs=1e-12)
        assert max(widths_by_dose[expected_dose]) == pytest.approx(expected_range[1], abs=1e-12)
        assert max(widths_by_dose[expected_dose]) < 0.040


@pytest.mark.parametrize(
    (
        "high_dose_improvements",
        "monotonic_responses",
        "p01_crossings",
        "p02_crossings",
        "expected",
    ),
    (
        (9, 8, 2, 3, "span_support_sufficient_in_frozen_counterfactuals"),
        (9, 8, 1, 4, "span_support_contributor_not_sufficient"),
        (5, 5, 0, 0, "span_support_association_not_supported"),
        (6, 7, 0, 0, "span_support_inconclusive"),
    ),
)
def test_scientific_endpoint_has_the_four_mutually_exclusive_branches(
    high_dose_improvements: int,
    monotonic_responses: int,
    p01_crossings: int,
    p02_crossings: int,
    expected: str,
) -> None:
    assert (
        probe.classify_endpoint(
            high_dose_improvements=high_dose_improvements,
            monotonic_responses=monotonic_responses,
            p01_crossings=p01_crossings,
            p02_crossings=p02_crossings,
        )
        == expected
    )


def test_source_manifest_and_seven_runtime_blobs_remain_frozen() -> None:
    assert probe.SOURCE_COMMIT == ("e5f36fd971a7266531a6d124f553f121379ad889")
    assert probe.PREREGISTRATION_COMMIT == ("5a6e778f57d37511be7b442ef890024079d81f63")
    assert probe.SOURCE_MANIFEST_ENTRY_COUNT == 254
    assert probe.SOURCE_MANIFEST_SHA256 == (
        "9f205ae20da00e383750e3fd84acd9b75b824aa9f27e83e002960d93a89204b5"
    )
    normalized_blobs = {
        Path(path).as_posix(): blob for path, blob in probe.RUNTIME_PATH_BLOBS.items()
    }
    assert normalized_blobs == EXPECTED_RUNTIME_PATH_BLOBS


def test_frozen_runtime_worktree_hashes_use_git_text_filters() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    for path, expected_blob in probe.RUNTIME_PATH_BLOBS.items():
        assert probe._filtered_worktree_blob(repo_root, path) == expected_blob  # noqa: SLF001


def test_original_state_control_support_remains_unmodified() -> None:
    assert (
        StateControl(
            state="A",
            total_wire_length_um=70_000,
            span_ratio_ppm=1_000_000,
        ).span_ratio_ppm
        == 1_000_000
    )
    with pytest.raises(ValidationError):
        StateControl(
            state="A",
            total_wire_length_um=70_000,
            span_ratio_ppm=1_000_001,
        )


def test_analysis_recomputes_synthetic_32_event_run_and_writes_strict_outputs(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "log.jsonl"
    events = _write_synthetic_probe_log(log_path)
    loaded = probe.load_probe_events(log_path)
    assert all(isinstance(event, probe.ProbeBReplayEvent) for event in loaded[:2])
    assert all(isinstance(event, probe.ProbeAEvaluationEvent) for event in loaded[2:])
    aggregate = probe.aggregate_probe_endpoint(loaded)
    assert aggregate.model_dump() == {
        "high_dose_improvements": 10,
        "monotonic_responses": 10,
        "p01_crossings": 5,
        "p02_crossings": 5,
        "endpoint": "span_support_sufficient_in_frozen_counterfactuals",
    }
    summary = _complete_synthetic_summary(log_path)

    analysis = span_analysis.analyze_probe_events(log_path, summary)

    assert len(events) == 32
    assert analysis.solver_calls_completed == 32
    assert analysis.solver_mode_counts == {"subprocess": 32}
    assert len(analysis.b_replays) == 2
    assert len(analysis.blocks) == 10
    assert analysis.high_dose_improvements == 10
    assert analysis.monotonic_responses == 10
    assert analysis.p01_crossings == 5
    assert analysis.p02_crossings == 5
    assert analysis.scientific_endpoint == ("span_support_sufficient_in_frozen_counterfactuals")
    assert all(
        tuple(row.dose_ppm for row in block.doses) == probe.DOSES_PPM for block in analysis.blocks
    )
    assert all(
        block.doses[0].curve_sha256 == block.doses[0].source_curve_sha256
        for block in analysis.blocks
    )
    assert all(
        block.doses[2].state_a_loss < block.doses[0].state_a_loss for block in analysis.blocks
    )

    contradicted = {
        **summary.model_dump(mode="json"),
        "high_dose_improvements": 0,
    }
    with pytest.raises(
        ValueError,
        match="endpoint does not match independent recomputation",
    ):
        span_analysis.analyze_probe_events(log_path, contradicted)

    first_output = tmp_path / "analysis-1"
    second_output = tmp_path / "analysis-2"
    span_analysis.write_probe_outputs(analysis, first_output)
    span_analysis.write_probe_outputs(analysis, second_output)
    for filename in ("summary.json", "report.md"):
        payload = (first_output / filename).read_bytes()
        assert payload.endswith(b"\n")
        assert b"\r" not in payload
        assert payload == (second_output / filename).read_bytes()
    first_png = (first_output / "dose-response.png").read_bytes()
    assert first_png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(first_png) > 10_000
    assert first_png == (second_output / "dose-response.png").read_bytes()


def test_probe_loader_accepts_only_an_exact_validated_prefix(tmp_path: Path) -> None:
    events = _synthetic_probe_events()
    absent_path = tmp_path / "absent.jsonl"
    assert probe.load_probe_events(absent_path) == ()

    prefix_path = tmp_path / "prefix.jsonl"
    _write_probe_events(prefix_path, events[:13])
    prefix = probe.load_probe_events(prefix_path)
    assert len(prefix) == 13
    assert tuple(event.call_index for event in prefix) == tuple(range(13))
    probe.validate_probe_prefix(prefix)
    with pytest.raises(
        probe.ASpanProbeExecutionError,
        match="endpoint requires a complete 32-call log",
    ):
        probe.aggregate_probe_endpoint(prefix)

    broken_events = list(events[:3])
    broken_events[2] = {**broken_events[2], "call_index": 3}
    broken_path = tmp_path / "broken.jsonl"
    _write_probe_events(broken_path, tuple(broken_events))
    with pytest.raises(
        probe.ASpanProbeExecutionError,
        match="call indices are not contiguous",
    ):
        probe.load_probe_events(broken_path)

    unterminated_path = tmp_path / "unterminated.jsonl"
    unterminated_path.write_bytes(prefix_path.read_bytes().rstrip(b"\n"))
    with pytest.raises(
        probe.ASpanProbeExecutionError,
        match="newline-terminated LF-only",
    ):
        probe.load_probe_events(unterminated_path)


def test_terminal_failure_marker_permanently_forbids_retry_and_endpoint(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / probe.RUN_DIRECTORY
    events = _synthetic_probe_events()
    _write_probe_events(run_directory / probe.LOG_FILENAME, events[:3])
    marker = probe.write_probe_terminal_failure(
        run_directory,
        RuntimeError("synthetic numerical failure"),
        call_index=3,
        config_hash="d" * 64,
    )

    assert marker.status == "terminal_failure"
    assert marker.retry_forbidden is True
    assert marker.call_index == 3
    assert marker.log_lines == 3
    assert marker.solver_calls_recorded == 3
    assert "endpoint" not in marker.model_dump()
    marker_path = run_directory / probe.TERMINAL_FAILURE_FILENAME
    marker_bytes = marker_path.read_bytes()
    assert marker_bytes.endswith(b"\n") and b"\r" not in marker_bytes
    assert probe.load_probe_terminal_failure(marker_path) == marker

    with pytest.raises(
        probe.ASpanProbeExecutionError,
        match="numerical retry is forbidden",
    ):
        probe.write_probe_terminal_failure(
            run_directory,
            RuntimeError("forbidden retry"),
            call_index=3,
            config_hash="d" * 64,
        )

    adapter_constructed = False

    def fail_if_adapter_is_constructed() -> probe.NEC2Like:
        nonlocal adapter_constructed
        adapter_constructed = True
        raise AssertionError("terminal retry constructed a solver adapter")

    with pytest.raises(
        probe.ASpanProbeExecutionError,
        match="terminal failure marker exists",
    ):
        asyncio.run(
            probe.run_a_span_probe(
                tmp_path,
                implementation_commit="a" * 40,
                adapter_factory=fail_if_adapter_is_constructed,
            )
        )
    assert adapter_constructed is False
