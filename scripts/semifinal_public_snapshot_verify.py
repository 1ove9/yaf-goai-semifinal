"""Verify the history-free public semifinal snapshot without solver calls."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
RECEIPT_PATH = ROOT / "docs" / "provenance" / "PUBLIC-SNAPSHOT-RECEIPT.json"
B_COMPLETION_PATH = (
    ROOT
    / "artifacts"
    / "analysis"
    / "semifinal-paired-b-completion-v1"
    / "appendix.json"
)
A_SPAN_PATH = (
    ROOT
    / "artifacts"
    / "analysis"
    / "semifinal-a-span-support-causal-probe-v1"
    / "summary.json"
)
SUPPORT_CERTIFICATE_PATH = (
    ROOT
    / "artifacts"
    / "analysis"
    / "semifinal-paired-b-completion-v1-certificate"
    / "summary.json"
)
MANIFEST_PATH = ROOT / "artifacts" / "runs" / "manifest.json"
SEEDS = (101, 202, 303, 404, 505)
PARENTS = ("p01", "p02")
AGENTS = ("random", "es")


class SnapshotVerificationError(RuntimeError):
    """Raised when the public snapshot differs from its frozen receipt."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotVerificationError(message)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_receipt() -> dict[str, Any]:
    receipt = cast(dict[str, Any], _load_json(RECEIPT_PATH))
    _require(receipt["schema_version"] == 1, "unsupported receipt schema")
    _require(
        receipt["publication_mode"] == "sanitized-root-snapshot",
        "publication mode is not sanitized-root-snapshot",
    )
    _require(receipt["history_intentionally_omitted"] is True, "history omission is not recorded")

    manifest_receipt = receipt["manifest"]
    _require(manifest_receipt["entry_count"] == 255, "receipt manifest count is not 255")
    _require(
        _sha256(ROOT / manifest_receipt["path"]) == manifest_receipt["sha256"],
        "manifest SHA-256 differs from the receipt",
    )
    for relative_path, expected_hash in receipt["frozen_files"].items():
        _require(
            _sha256(ROOT / relative_path) == expected_hash,
            f"frozen file SHA-256 mismatch: {relative_path}",
        )
    return receipt


def _verify_manifest() -> int:
    manifest = _load_json(MANIFEST_PATH)
    _require(isinstance(manifest, list), "manifest must be a JSON list")
    run_ids = [entry["run_id"] for entry in manifest]
    _require(len(run_ids) == 255, "manifest does not contain 255 entries")
    _require(len(set(run_ids)) == len(run_ids), "manifest contains duplicate run IDs")
    return len(run_ids)


def _verify_b_completion() -> tuple[int, int, int]:
    appendix = _load_json(B_COMPLETION_PATH)
    manifest_entries = cast(list[dict[str, Any]], _load_json(MANIFEST_PATH))
    manifest_index = {entry["run_id"]: entry for entry in manifest_entries}
    _require(appendix["schema_version"] == 1, "unsupported B-completion schema")
    _require(
        appendix["study_id"] == "semifinal-paired-b-parent-conditional-completion-v1",
        "unexpected B-completion study ID",
    )
    _require(
        appendix["mapping_version"] == "b-parent-a-only-exact-support-v1",
        "unexpected B-completion mapping",
    )
    _require(
        appendix["spec_revision"] == "1.0-b-parent-a-only-exact-support",
        "unexpected B-completion specification",
    )
    _require(appendix["study_status"] == "complete", "B-completion study is not complete")
    for key in (
        "completed_prefix",
        "failed_run_id",
        "matrix_exception_type",
        "matrix_exception_message",
    ):
        _require(appendix[key] is None, f"B-completion terminal field is not null: {key}")
    _require(
        appendix["scientific_endpoint"]
        == "b_completion_pair_validity_without_effect_crossing",
        "unexpected B-completion endpoint",
    )
    _require(appendix["verdict_ceiling"] == "insufficient_evidence", "invalid verdict ceiling")

    rows = appendix["rows"]
    expected_run_ids = {
        f"semifinal-paired-b-completion-{parent}-{agent}-s{seed}"
        for parent in PARENTS
        for agent in AGENTS
        for seed in SEEDS
    }
    _require(len(rows) == 20, "B-completion matrix does not contain 20 rows")
    _require({row["run_id"] for row in rows} == expected_run_ids, "B-completion matrix IDs differ")

    for row in rows:
        _require(row["execution_status"] == "completed", f"incomplete run: {row['run_id']}")
        _require(row["source_status"] == "completed", f"incomplete source: {row['run_id']}")
        _require(row["accepted_count"] == 300, f"accepted count differs: {row['run_id']}")
        _require(row["proposal_attempts"] == 300, f"proposal count differs: {row['run_id']}")
        _require(row["rejected_count"] == 0, f"rejections present: {row['run_id']}")
        _require(
            row["solver_mode_counts"] == {"subprocess": 600},
            f"unexpected solver mode count: {row['run_id']}",
        )
        for field in ("log_sha256", "summary_sha256"):
            value = row[field]
            _require(
                isinstance(value, str)
                and len(value) == 64
                and all(character in "0123456789abcdef" for character in value),
                f"invalid {field}: {row['run_id']}",
            )
        manifest_entry = manifest_index.get(row["run_id"])
        if manifest_entry is None:
            raise SnapshotVerificationError(f"run absent from manifest: {row['run_id']}")
        _require(
            manifest_entry["sha256"]["log.jsonl"] == row["log_sha256"],
            f"manifest log hash differs: {row['run_id']}",
        )
        _require(
            manifest_entry["sha256"]["summary.json"] == row["summary_sha256"],
            f"manifest summary hash differs: {row['run_id']}",
        )

    accepted_count = sum(int(row["accepted_count"]) for row in rows)
    h1_count = sum(int(row["h1_count"]) for row in rows)
    h2_count = sum(int(row["h2_count"]) for row in rows)
    _require(accepted_count == 6000, "B-completion accepted total is not 6000")
    _require(h1_count == appendix["h1_count"] == 702, "B-completion H1 count is not 702")
    _require(h2_count == appendix["h2_count"] == 0, "B-completion H2 count is not zero")
    selected = appendix["selected_hypothesis"]
    _require(
        selected["run_id"] == "semifinal-paired-b-completion-p01-es-s303",
        "selected-hypothesis run differs",
    )
    _require(selected["step_index"] == 265, "selected-hypothesis step differs")
    _require(selected["proposal_index"] == 265, "selected-hypothesis proposal differs")
    _require(selected["valid_pair_search"] is True, "selected hypothesis is not pair-valid")
    _require(
        selected["pair_hash"]
        == "59a7e7df8fe7b8c3e6a07333e84ef12099886c5971a9815891ef63e1d041f259",
        "selected-hypothesis pair hash differs",
    )
    _require(
        selected["worst_reflected_power_fraction"] == 0.23010531242953516,
        "selected-hypothesis score differs",
    )
    return accepted_count, h1_count, h2_count


def _verify_a_span_probe() -> tuple[int, int, str]:
    summary = _load_json(A_SPAN_PATH)
    endpoint = "span_support_sufficient_in_frozen_counterfactuals"
    _require(summary["schema_version"] == 1, "unsupported A-span probe schema")
    _require(
        summary["study_id"] == summary["run_id"] == "semifinal-a-span-support-causal-probe-v1",
        "unexpected A-span probe identity",
    )
    _require(
        summary["config_hash"]
        == "6bba05ceb825e79c9495957317d06d7930ef63f8bc4588e10cf3a0d1af8953b5",
        "A-span probe config hash differs",
    )
    _require(summary["study_status"] == "complete", "A-span probe is not complete")
    _require(summary["scientific_endpoint"] == endpoint, "unexpected A-span probe endpoint")
    _require(summary["verdict_ceiling"] == "insufficient_evidence", "invalid probe ceiling")
    _require(summary["solver_calls_completed"] == 32, "A-span solver-call count is not 32")
    _require(summary["solver_mode_counts"] == {"subprocess": 32}, "probe mode is not subprocess")
    _require(summary["monotonic_responses"] == 10, "A-span monotonic count is not 10")
    _require(summary["high_dose_improvements"] == 10, "A-span high-dose count is not 10")
    _require(summary["p01_crossings"] == 5, "p01 crossing count is not 5")
    _require(summary["p02_crossings"] == 5, "p02 crossing count is not 5")

    blocks = summary["blocks"]
    _require(len(blocks) == 10, "A-span probe does not contain 10 blocks")
    expected_blocks = {(parent, seed) for parent in PARENTS for seed in SEEDS}
    _require(
        {(block["parent_id"], int(block["seed"])) for block in blocks} == expected_blocks,
        "A-span parent/seed matrix differs",
    )
    for block in blocks:
        _require(block["monotonic_response"] is True, "non-monotonic probe block")
        _require(block["high_dose_improvement"] is True, "high-dose improvement absent")
        _require(block["positive_dose_reference_crossing"] is True, "probe crossing absent")
        doses = block["doses"]
        _require([dose["dose_ppm"] for dose in doses] == [0, 50000, 100000], "dose grid differs")
        for dose in doses:
            _require(dose["eligible_for_original_h1_h2"] is False, "probe entered H1/H2")
            _require(dose["eligible_for_original_candidate_pool"] is False, "probe entered pool")
            _require(dose["eligible_for_original_agent_comparison"] is False, "probe entered agent comparison")
            _require(dose["physical_40mm_trajectory_valid"] is True, "invalid 40 mm trajectory")
            _require(dose["trajectory_valid"] is True, "invalid diagnostic trajectory")
            _require(dose["state_a_valid"] is True, "invalid diagnostic state A")
            _require(dose["diagnostic_pair_valid"] is True, "invalid diagnostic pair")
        for dose in doses[1:]:
            _require(dose["counterfactual_only"] is True, "positive dose is not counterfactual-only")
            _require(dose["outside_original_span_support"] is True, "positive dose is in old support")
    call_indices = sorted(dose["call_index"] for block in blocks for dose in block["doses"])
    _require(call_indices == list(range(2, 32)), "A-span dose call indices differ")
    return 32, 10, endpoint


def _verify_support_certificate() -> int:
    summary = _load_json(SUPPORT_CERTIFICATE_PATH)
    _require(
        summary["study_id"] == "semifinal-paired-b-parent-conditional-completion-v1",
        "unexpected support-certificate study ID",
    )
    _require(
        summary["mapping_version"] == "b-parent-a-only-exact-support-v1",
        "unexpected support-certificate mapping",
    )
    _require(summary["status"] == "support_certificate_passed", "support certificate failed")
    _require(summary["checked_span_count"] == 480002, "certificate checked count differs")
    _require(summary["expected_span_count"] == 480002, "certificate expected count differs")
    _require(summary["failed_span_count"] == 0, "certificate has failed spans")
    _require(summary["solver_calls"] == 0, "certificate invoked a solver")
    _require(summary["openems_calls"] == 0, "certificate invoked openEMS")
    certificate = summary["certificate"]
    _require(certificate["status"] == "passed", "nested certificate status differs")
    _require(certificate["checked_span_count"] == 480002, "nested checked count differs")
    _require(certificate["expected_span_count"] == 480002, "nested expected count differs")
    _require(certificate["failed_span_count"] == 0, "nested failed count differs")
    return 480002


def verify_snapshot_metadata() -> dict[str, int | str]:
    """Verify all frozen snapshot metadata without invoking a solver."""

    receipt = _verify_receipt()
    manifest_count = _verify_manifest()
    accepted_count, h1_count, h2_count = _verify_b_completion()
    solver_calls, monotonic_responses, endpoint = _verify_a_span_probe()
    certificate_span_count = _verify_support_certificate()
    facts = receipt["terminal_facts"]
    _require(facts["h1_count"] == h1_count, "receipt H1 differs")
    _require(facts["h2_count"] == h2_count, "receipt H2 differs")
    _require(facts["b_completion_accepted_count"] == accepted_count, "receipt accepted total differs")
    _require(facts["a_span_probe_solver_calls"] == solver_calls, "receipt solver-call total differs")
    _require(
        facts["a_span_probe_monotonic_responses"] == monotonic_responses,
        "receipt monotonic total differs",
    )
    _require(facts["a_span_probe_scientific_endpoint"] == endpoint, "receipt endpoint differs")
    _require(
        facts["support_certificate_checked_spans"] == certificate_span_count,
        "receipt certificate count differs",
    )
    _require(facts["support_certificate_failed_spans"] == 0, "receipt certificate failures differ")
    _require(facts["verdict_ceiling"] == "insufficient_evidence", "receipt ceiling differs")
    return {
        "manifest_count": manifest_count,
        "accepted_count": accepted_count,
        "h1_count": h1_count,
        "h2_count": h2_count,
        "a_span_probe_solver_calls": solver_calls,
        "a_span_probe_monotonic_responses": monotonic_responses,
        "a_span_probe_endpoint": endpoint,
        "support_certificate_checked_spans": certificate_span_count,
    }


def _verify_archive() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "archive_run.py"), "--verify"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        detail = output.strip()[-2000:] or "no archive output"
        raise SnapshotVerificationError(
            f"archive verification returned {result.returncode}: {detail}"
        )
    _require("MISMATCH" not in output, "archive verification reported MISMATCH")
    ok_lines = [line for line in output.splitlines() if line.endswith(": OK")]
    _require(len(ok_lines) == 255, "archive verification did not report 255 OK entries")


def main() -> int:
    try:
        facts = verify_snapshot_metadata()
        _verify_archive()
    except (KeyError, OSError, TypeError, ValueError, SnapshotVerificationError) as exc:
        print(f"semifinal_public_snapshot_verify: FAIL: {exc}", file=sys.stderr)
        return 1

    print("solver_calls=0")
    print("history_mode=sanitized_root_snapshot")
    print("original_history_replay=not_available")
    print(f"archive_verify={facts['manifest_count']}/{facts['manifest_count']} OK")
    print(f"b_completion_h1_h2={facts['h1_count']}/{facts['h2_count']}")
    print(f"a_span_probe_solver_calls={facts['a_span_probe_solver_calls']}")
    print(f"a_span_probe_monotonic={facts['a_span_probe_monotonic_responses']}/10")
    print(f"a_span_probe_endpoint={facts['a_span_probe_endpoint']}")
    print(
        "support_certificate="
        f"{facts['support_certificate_checked_spans']}/"
        f"{facts['support_certificate_checked_spans']} OK"
    )
    print("final_verdict=insufficient_evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
