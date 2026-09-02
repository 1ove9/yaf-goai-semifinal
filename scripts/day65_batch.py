"""Run, resume, and archive the preregistered Day 6.5 v2 matrix."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.day65_batch import DAY65_BATCH_ID, run_day65_batch


def _archived(repo_root: Path) -> set[str]:
    payload = json.loads(
        (repo_root / "artifacts" / "runs" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    return {str(item["run_id"]) for item in payload}


def _archive(repo_root: Path, run_id: str, role: str, note: str) -> None:
    if run_id in _archived(repo_root):
        return
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "archive_run.py"),
            run_id,
            "--role",
            role,
            "--note",
            note,
        ],
        cwd=repo_root,
        check=True,
    )


async def _run() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    state = await run_day65_batch(repo_root)
    source_root = repo_root / "runs" / f"batch_{DAY65_BATCH_ID}"
    output = repo_root / "artifacts" / "analysis" / DAY65_BATCH_ID
    output.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "state.json"):
        (output / name).write_bytes((source_root / name).read_bytes())
    archived = _archived(repo_root)
    for record in state.runs:
        if record.status != "completed" or record.run_id in archived:
            continue
        role = "agent-gp" if record.agent == "es" else "baseline-random"
        _archive(
            repo_root,
            record.run_id,
            role,
            f"batch={DAY65_BATCH_ID} spec=dual seed={record.seed} agent={record.agent}",
        )
        archived.add(record.run_id)
    failed = [record for record in state.runs if record.status == "failed"]
    print(f"completed={len(state.runs) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


def main() -> int:
    """Execute the full sequential matrix."""

    try:
        return asyncio.run(_run())
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"day65_batch: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
