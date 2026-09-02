"""Run, resume, and archive the preregistered Day 6 comparison matrix."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.day6 import run_day6_batch


def _archived(repo_root: Path) -> set[str]:
    path = repo_root / "artifacts" / "runs" / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
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
    state = await run_day6_batch(repo_root)
    state_artifact = (
        repo_root / "artifacts" / "analysis" / "day6-freeform" / "batch-state.json"
    )
    state_artifact.parent.mkdir(parents=True, exist_ok=True)
    state_artifact.write_bytes(
        (
            json.dumps(
                state.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    archived = _archived(repo_root)
    for record in state.runs:
        if record.status != "completed" or record.run_id in archived:
            continue
        role = "agent-gp" if record.agent == "gp" else "baseline-random"
        _archive(
            repo_root,
            record.run_id,
            role,
            f"batch=day6-freeform spec=dual seed={record.seed} agent={record.agent}",
        )
        archived.add(record.run_id)
    failed = [record for record in state.runs if record.status == "failed"]
    print(f"completed={len(state.runs) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
