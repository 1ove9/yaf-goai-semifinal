"""Run a calibrated, recoverable GP-versus-random exploration batch."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.batch import (
    BatchRunRecord,
    load_batch_config,
    materialize_failed_wire_evidence,
    run_batch,
    run_pixel_batch,
    run_wire_batch,
    seal_interrupted_wire_batch,
)

ROLE_BY_AGENT = {
    "gp": "agent-gp",
    "random": "baseline-random",
    "classic": "baseline-classic",
    "evolve_pixel": "other",
    "random_pixel": "baseline-random",
    "preflight_pixel": "smoke",
}


def _archived_run_ids(repo_root: Path) -> set[str]:
    manifest_path = repo_root / "artifacts" / "runs" / "manifest.json"
    if not manifest_path.is_file():
        return set()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {str(item["run_id"]) for item in payload}


def archive_completed_runs(
    records: tuple[BatchRunRecord, ...],
    *,
    batch_id: str,
    repo_root: Path,
) -> None:
    """Archive each completed matrix run exactly once through the public CLI."""

    archived = _archived_run_ids(repo_root)
    archive_script = repo_root / "scripts" / "archive_run.py"
    for record in records:
        if record.status not in {"completed", "failed"} or record.run_id in archived:
            continue
        run_directory = repo_root / "runs" / record.run_id
        if not (run_directory / "log.jsonl").is_file() or not (
            run_directory / "summary.json"
        ).is_file():
            continue
        note = (
            f"batch={batch_id} spec={record.spec_name} seed={record.seed} "
            f"agent={record.agent} status={record.status}"
        )
        if record.status == "failed":
            note += f" deprecated_run error={record.error}"
        subprocess.run(
            [
                sys.executable,
                str(archive_script),
                record.run_id,
                "--role",
                "other" if record.status == "failed" else ROLE_BY_AGENT[record.agent],
                "--note",
                note,
            ],
            cwd=repo_root,
            check=True,
        )
        archived.add(record.run_id)


async def _run(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    if args.seal_interrupted:
        if not args.batch_id.startswith(("day4-wire", "day5-wire")):
            raise ValueError("--seal-interrupted is valid only for wire batches")
        state = seal_interrupted_wire_batch(
            args.batch_id,
            repo_root=repo_root,
            reason=args.reason,
        )
        archive_completed_runs(
            state.runs,
            batch_id=args.batch_id,
            repo_root=repo_root,
        )
        print(f"sealed_batch_id={args.batch_id}")
        return 0
    if args.batch_id == "day3-pixel":
        runner = run_pixel_batch
    elif args.batch_id.startswith(("day4-wire", "day5-wire")):
        runner = run_wire_batch
    else:
        runner = run_batch
    state = await runner(
        args.batch_id,
        repo_root=repo_root,
        on_completed=lambda record: archive_completed_runs(
            (record,),
            batch_id=args.batch_id,
            repo_root=repo_root,
        ),
    )
    if args.batch_id.startswith(("day4-wire", "day5-wire")):
        materialize_failed_wire_evidence(state, repo_root / "runs")
        archive_completed_runs(
            state.runs,
            batch_id=args.batch_id,
            repo_root=repo_root,
        )
    config = load_batch_config(
        repo_root / "runs" / f"batch_{args.batch_id}" / "config.json"
    )
    completed = sum(record.status == "completed" for record in state.runs)
    failed = sum(record.status == "failed" for record in state.runs)
    print(f"batch_id={args.batch_id}")
    print(f"config_hash={config.config_hash}")
    print(f"budget={config.config.budget} seeds={list(config.config.seeds)}")
    print(f"completed={completed} failed={failed}")
    return 0 if failed == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--seal-interrupted", action="store_true")
    parser.add_argument(
        "--reason",
        default="operator stopped batch after a preregistered sanity check failed",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(parse_args())))
