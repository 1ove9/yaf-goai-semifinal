"""Run, report, and archive the preregistered Robust Hunt R2 matrix."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import cast

from yaf_ai.exploration.paired_r2_batch import (
    R2_RUN_ID_PREFIX,
    R2_SEEDS,
    R2MatrixError,
    run_r2_matrix,
)
from yaf_ai.exploration.paired_r2_report import (
    BoundaryDiagnostics,
    R2Appendix,
    TurnDistribution,
    build_r2_appendix,
    write_r2_outputs,
)
from yaf_ai.exploration.paired_runner import PairedRunSummary


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_index(repo_root: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(
        (repo_root / "artifacts" / "runs" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(payload, list):
        raise RuntimeError("archive manifest root is not an array")
    entries: dict[str, dict[str, object]] = {}
    for raw_entry in payload:
        if not isinstance(raw_entry, dict) or not isinstance(
            raw_entry.get("run_id"), str
        ):
            raise RuntimeError("archive manifest contains a malformed entry")
        entry = cast(dict[str, object], raw_entry)
        run_id = cast(str, entry["run_id"])
        if run_id in entries:
            raise RuntimeError(f"archive manifest repeats run_id {run_id}")
        entries[run_id] = entry
    return entries


def _archive_note(seed: int) -> str:
    return f"batch=semifinal-paired-r2 agent=es-r2 seed={seed}"


def _validate_archive_entry(
    repo_root: Path,
    seed: int,
    entry: dict[str, object],
) -> None:
    run_id = f"{R2_RUN_ID_PREFIX}{seed}"
    run_directory = repo_root / "runs" / run_id
    log_path = run_directory / "log.jsonl"
    summary_path = run_directory / "summary.json"
    summary = PairedRunSummary.model_validate_json(summary_path.read_bytes())
    expected = {
        "run_id": run_id,
        "role": "other",
        "note": _archive_note(seed),
        "config_hash": summary.config_hash,
        "seed": seed,
        "steps_completed": summary.steps_completed,
        "solver_mode_counts": summary.solver_mode_counts,
        "sha256": {
            "log.jsonl": _sha256_file(log_path),
            "summary.json": _sha256_file(summary_path),
        },
        "overwritten": False,
    }
    for field, expected_value in expected.items():
        if entry.get(field) != expected_value:
            raise RuntimeError(
                f"archive manifest field {field} disagrees for {run_id}"
            )


def _archive_completed_runs(repo_root: Path) -> None:
    archived = _manifest_index(repo_root)
    for seed in R2_SEEDS:
        run_id = f"{R2_RUN_ID_PREFIX}{seed}"
        if run_id in archived:
            _validate_archive_entry(repo_root, seed, archived[run_id])
            continue
        subprocess.run(
            (
                sys.executable,
                str(repo_root / "scripts" / "archive_run.py"),
                run_id,
                "--role",
                "other",
                "--note",
                _archive_note(seed),
            ),
            cwd=repo_root,
            check=True,
        )
        archived = _manifest_index(repo_root)
        _validate_archive_entry(repo_root, seed, archived[run_id])
    subprocess.run(
        (
            sys.executable,
            str(repo_root / "scripts" / "archive_run.py"),
            "--verify",
        ),
        cwd=repo_root,
        check=True,
    )


def _turn_counts(distribution: TurnDistribution) -> str:
    return json.dumps(
        {
            "3": distribution.count_3,
            "4": distribution.count_4,
            "5": distribution.count_5,
            "6": distribution.count_6,
            "total": distribution.total,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _boundary_counts(boundary: BoundaryDiagnostics) -> str:
    payload = boundary.model_dump(mode="json")
    fields = {
        name: value
        for name, value in payload.items()
        if name not in {"pool", "denominator"}
    }
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


def _print_appendix(appendix: R2Appendix) -> None:
    for row in appendix.rows:
        short_segment_rejections = sum(
            count
            for reason, count in row.rejection_reasons.items()
            if "segment" in reason.lower()
        )
        print(
            f"seed={row.seed} status={row.execution_status} "
            f"source_status={row.source_run_status} attempts={row.proposal_attempts} "
            f"accepted={row.accepted_count} valid={row.valid_count} "
            f"rejected={row.rejected_count} best_l={row.best_valid_l} "
            f"pass={row.pass_flag} restarts={row.restart_count} "
            f"short_segment_rejections={short_segment_rejections} "
            "accepted_turn_count_distribution="
            f"{_turn_counts(row.accepted_turns)} "
            "effective_turn_count_distribution="
            f"{_turn_counts(row.effective_turns)} "
            f"boundary_pool={row.boundary.pool} "
            f"boundary_denominator={row.boundary.denominator} "
            f"boundary_1pct_by_dim={_boundary_counts(row.boundary)}"
        )
    print(
        f"R2 {appendix.study_status}: endpoint={appendix.scientific_endpoint}; "
        f"pass_count={appendix.pass_count}/5; "
        f"valid_pair_seed_count={appendix.valid_pair_seed_count}/5; "
        f"cross_seed_gate_pass={appendix.cross_seed_gate_pass}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    repo_root = args.repo_root.resolve()
    try:
        results = asyncio.run(run_r2_matrix(repo_root))
    except R2MatrixError as error:
        try:
            appendix = build_r2_appendix(repo_root, matrix_error=error)
            write_r2_outputs(repo_root, appendix)
            _print_appendix(appendix)
        except Exception as report_error:
            print(
                f"R2 matrix failed: {error.cause_type}: {error.cause_message}; "
                "diagnostic publication also failed: "
                f"{type(report_error).__name__}: {report_error}",
                file=sys.stderr,
            )
            return 1
        print(
            f"R2 matrix failed: {error.cause_type}: {error.cause_message}; "
            f"failed_seed={error.failed_seed}; "
            f"failed_seed_started={error.failed_seed_started}; "
            f"confirmed={len(error.confirmed_results)}",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(
            f"R2 orchestration failed before a structured matrix state was available: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1
    try:
        restart_counts = {
            result.summary.seed: result.restart_count for result in results
        }
        appendix = build_r2_appendix(
            repo_root,
            restart_counts=restart_counts,
        )
        write_r2_outputs(repo_root, appendix)
        if appendix.study_status != "complete":
            raise RuntimeError("R2 matrix returned without five legal terminals")
        _archive_completed_runs(repo_root)
    except Exception as error:
        print(
            f"R2 post-matrix evidence operation failed: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1
    _print_appendix(appendix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
