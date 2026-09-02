"""Run a small auditable antenna exploration episode."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from yaf_ai.exploration.baselines import (
    ClassicTemplateBaseline,
    ExplorationAgent,
    GPExplorationAgent,
    RandomSearchBaseline,
)
from yaf_ai.exploration.environment import AntennaExplorationEnv, ExplorationConfig
from yaf_ai.exploration.proposal_space import proposal_space_for_solver
from yaf_ai.exploration.specs import SPEC_NAMES, get_spec


def build_agent(name: str, config: ExplorationConfig) -> ExplorationAgent:
    """Construct one CLI-selected agent with the shared run config."""

    if name == "random":
        return RandomSearchBaseline(config)
    if name == "classic":
        return ClassicTemplateBaseline(config)
    if name == "gp":
        return GPExplorationAgent(config)
    raise ValueError(f"unknown agent: {name}")


async def run_demo(args: argparse.Namespace) -> int:
    """Execute one episode and print the audit-oriented result summary."""

    proposal_space = proposal_space_for_solver(args.solver)
    config = ExplorationConfig(
        spec=get_spec(args.spec),
        evaluation_budget=args.budget,
        seed=args.seed,
        solver=args.solver,
        proposal_space_version=proposal_space.version,
    )
    environment = AntennaExplorationEnv(
        config,
        runs_root=Path(args.runs_root),
    )
    environment.reset()
    agent = build_agent(args.agent, config)
    results = await agent.run(environment)
    summary_path = environment.finish()

    print(f"run_id: {environment.run_id}")
    print(f"audit_log: {summary_path.parent / 'log.jsonl'}")
    print(f"summary: {summary_path}")
    print("solver_modes: " + ", ".join(result.solver_mode for result in results))
    print("top_designs:")
    for rank, result in enumerate(
        sorted(results, key=lambda item: item.score, reverse=True)[:3],
        start=1,
    ):
        print(
            f"  {rank}. hash={result.geometry_hash[:12]} "
            f"S11={result.metrics['min_s11_db']:.3f} dB "
            f"score={result.score:.6f} mode={result.solver_mode}"
        )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default="wifi24", choices=SPEC_NAMES)
    parser.add_argument("--budget", type=int, default=12)
    parser.add_argument("--agent", choices=["gp", "random", "classic"], default="gp")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--solver", choices=["openems", "nec2", "auto"], default="openems")
    parser.add_argument("--runs-root", default="runs")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_demo(parse_args())))
