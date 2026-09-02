"""Tests for the solver-free semifinal submission package."""

from __future__ import annotations

from pathlib import Path

import pytest

from yaf_ai.analysis.semifinal_submission import (
    _trajectory_geometries,
    build_portable_artifact,
    build_submission_datasets,
    build_submission_summary,
    render_candidate_card,
    render_evidence_index,
    render_report_markdown,
    verify_submission_package,
)
from yaf_ai.exploration.paired_meander import state_geometry_hash


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_submission_summary_reconstructs_frozen_claim_ceiling() -> None:
    summary, document = build_submission_summary(_repo_root())

    assert summary.final_verdict == "insufficient_evidence"
    assert summary.total_proposal_attempts == 6_210
    assert summary.total_rejected_proposals == 3_510
    assert summary.total_accepted_pairs == 2_700
    assert summary.total_subprocess_curves == 5_400
    assert summary.total_valid_pairs == 48
    assert summary.valid_cells == 1
    assert [item.valid_pairs for item in summary.matrix] == [0, 0, 0, 0, 0, 0, 48, 0, 0]
    assert summary.candidate.source_run_id == "semifinal-paired-es-warm-s101"
    assert summary.candidate.source_step_index == 213
    assert summary.candidate.pair_hash == (
        "8a4ad18c710ec185728fd5bff0e6f16461aea29362024893e1bb6ddd3dcc73ca"
    )
    assert summary.effect_gate.observed_reduction_fraction == pytest.approx(
        0.04674341445557906
    )
    assert not summary.effect_gate.passed
    assert not summary.instrument.candidate_openems_authorized
    assert not summary.instrument.candidate_openems_executed
    assert summary.instrument.rod_r2_result_status == "repair_not_confirmed"
    assert summary.archive.manifest_entry_count == 219
    assert summary.archive.verified_ok_count == 219
    assert summary.archive.all_ok
    assert document.verdict_ceiling == "insufficient_evidence"
    assert "within a frozen search space, budget, and seed set" in summary.title
    assert summary.static_day6_context.evidence_commit == (
        "acbf4736b8755b682d215e16fe479ffff534360d"
    )
    assert summary.static_day6_context.report_sha256 == (
        "07426556777d842bd71489a4e866f6a5487714a95e0f10b3ec52f137aac95d00"
    )
    assert summary.static_day6_context.summary_sha256 == (
        "28def8a7b5a204e7da394f458ab6bd6e027f124f0da025571065c904ef1a4df1"
    )
    assert summary.manual_comparator.evidence.evidence_commit == (
        "906835eceeae2e48a652e2b7fa891fd3e8461440"
    )
    assert (
        summary.manual_comparator.assembled_pair_count,
        summary.manual_comparator.scored_pair_count,
        summary.manual_comparator.valid_pair_count,
    ) == (5_184, 756, 0)
    assert summary.manual_comparator.selected_state_a_index == 100
    assert not summary.manual_comparator.selected_valid_pair
    assert summary.meander_r3_evidence.evidence_commit == (
        "6bee5eeac5642386f7015bf496e8a592424cb75c"
    )
    assert summary.rod_r2_evidence.log_sha256 == (
        "b3dd5214aae9c0f48f1051514109207bbb86c9f5cc3b832afc6180da62347079"
    )
    assert "ES was stable across seeds" in summary.prohibited_claims
    assert "static dual-band operation is impossible" in summary.prohibited_claims


def test_submission_package_survives_append_only_archive_extension() -> None:
    summary = verify_submission_package(_repo_root())

    assert summary.archive.manifest_entry_count == 219
    assert summary.archive.verified_ok_count == 219
    assert summary.archive.manifest_sha256 == (
        "cd6d8bd106ae6b7da478c836913a84511f1a484e55641e07f21cbe17013dfb8c"
    )
    assert summary.archive.all_ok


def test_candidate_states_and_trajectory_reconstruct_from_one_hardware_object() -> None:
    summary, document = build_submission_summary(_repo_root())
    candidate = document.candidates[0]
    geometries = _trajectory_geometries(candidate.proposal)

    assert len(geometries) == 21
    assert candidate.trajectory.valid
    assert summary.candidate.minimum_clearance_mm == pytest.approx(0.20275218914699993)
    assert summary.candidate.physical_feed_gap_mm == pytest.approx(2.33552)
    assert summary.candidate.minimum_pitch_mm == pytest.approx(3.512815)
    assert summary.candidate.minimum_height_mm == pytest.approx(0.405504378294)
    assert summary.candidate.maximum_adjacent_node_displacement_mm == pytest.approx(0.261734468034)
    assert summary.candidate.state_a.geometry_hash == (
        "4d8c585c7e4112d1d8aad9d8c33b55642549008cec6649075a75ffa4a4b15b55"
    )
    assert summary.candidate.state_b.geometry_hash == (
        "84566f8b6ab538d6ff1ae730b2ecd74f445fc127f877f8edb1a53530e509c33e"
    )
    assert summary.candidate.state_a.selected_index == 93
    assert summary.candidate.state_b.selected_index == 7
    assert state_geometry_hash(
        candidate.proposal.hardware,
        candidate.proposal.state_a,
        geometries[0],
    ) == summary.candidate.state_a.geometry_hash
    assert state_geometry_hash(
        candidate.proposal.hardware,
        candidate.proposal.state_b,
        geometries[-1],
    ) == summary.candidate.state_b.geometry_hash


def test_report_datasets_are_bounded_and_source_addressed() -> None:
    summary, document = build_submission_summary(_repo_root())
    datasets = build_submission_datasets(_repo_root(), summary, document)
    artifact = build_portable_artifact(summary, datasets)

    assert len(datasets.funnel) == 5
    assert len(datasets.valid_cells) == 9
    assert len(datasets.effect_gate) == 3
    assert len(datasets.state_a_curves) == 303
    assert len(datasets.state_b_curves) == 303
    assert all(row["source_run_id"] for row in datasets.state_a_curves)
    assert datasets.funnel[3]["stage"] == "Positive-eligible frozen hypotheses"
    assert artifact["surface"] == "report"
    manifest = artifact["manifest"]
    assert isinstance(manifest, dict)
    assert len(manifest["charts"]) == 5
    sources = artifact["sources"]
    assert isinstance(sources, list)
    curve_sources = {
        source["id"]: source
        for source in sources
        if isinstance(source, dict) and source.get("id") in {"state-a-curves", "state-b-curves"}
    }
    expected_paths = [
        "artifacts/runs/semifinal-paired-es-warm-s101/log.jsonl",
        "artifacts/runs/semifinal-paired-random-s202/log.jsonl",
        "artifacts/runs/semifinal-paired-manual-baseline/log.jsonl",
    ]
    state_a_source = curve_sources["state-a-curves"]
    assert state_a_source["path"] == "artifacts/runs"
    assert state_a_source["paths"] == expected_paths
    query = state_a_source["query"]
    assert isinstance(query, dict)
    assert query["tables_used"] == expected_paths
    assert curve_sources["state-b-curves"]["paths"] == expected_paths


def test_human_outputs_keep_hypothesis_and_failure_wording() -> None:
    summary, _ = build_submission_summary(_repo_root())
    outputs = (
        render_candidate_card(summary),
        render_evidence_index(summary),
        render_report_markdown(summary),
    )

    assert all(b"\r" not in output for output in outputs)
    combined = b"\n".join(outputs).decode("utf-8")
    assert "paired-state computational hypothesis" in combined
    assert "4.674341%" in combined
    assert "repair_not_confirmed" in combined
    assert "not YAF-M1" in combined
    assert "invented a new antenna" not in combined
    assert "state FoM=1-L" in combined
    assert "1-max(L_A,L_B)" in combined
    assert "cross-seed stability was not established" in combined
    assert "NOT RELEASED" in combined
    assert "no rod-r3 is authorized" in combined
    assert "selected state-A minimum was index 100" in combined
    assert "Physical feed gap: `2.335520 mm`" in combined
    assert "canonical JSON entry" in combined
    assert "append-safe successor" in combined
    assert "append-only" not in combined
    assert "canonical JSON entry must remain byte-identical" not in combined
    assert "acbf4736b8755b682d215e16fe479ffff534360d" in combined
    assert "6bee5eeac5642386f7015bf496e8a592424cb75c" in combined



def test_submission_package_has_verbatim_git_attribute() -> None:
    attributes = (_repo_root() / ".gitattributes").read_text(encoding="utf-8")

    assert (
        "artifacts/analysis/semifinal-submission/** -text"
        in attributes.splitlines()
    )
def test_submission_builder_source_contains_no_solver_entrypoint() -> None:
    source = (_repo_root() / "yaf_ai/analysis/semifinal_submission.py").read_text(
        encoding="utf-8"
    )
    script = (_repo_root() / "scripts/semifinal_demo.py").read_text(encoding="utf-8")

    prohibited = (
        "openems_adapter",
        "NEC2Adapter",
        "run_openems",
        "run_paired_adaptive",
        "fallback_analytical",
    )
    assert all(token not in source for token in prohibited)
    assert all(token not in script for token in prohibited)
