"""YAF command-line interface.

One-command entry points so a fresh ``pip install`` can experience the
platform without reading any docs:

    yaf info             # what's available on this machine
    yaf demo dipole      # half-wave dipole → S11 / VSWR / gain
    yaf demo fdtd        # differentiable FDTD gradient check
    yaf demo vae         # train the β-VAE designer (2 epochs)
    yaf demo bayesian    # GP + EI Bayesian optimization
    yaf demo pipeline    # end-to-end inverse-design loop
    yaf serve            # start the FastAPI server
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import runpy
import shutil
import sys

import click


def _version() -> str:
    try:
        return importlib.metadata.version("yaf")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0 (uninstalled)"


def _run_module(module: str, argv: list[str]) -> None:
    """Run ``python -m module argv...`` in-process."""
    old_argv = sys.argv
    sys.argv = [module, *argv]
    try:
        runpy.run_module(module, run_name="__main__")
    finally:
        sys.argv = old_argv


@click.group()
@click.version_option(version=_version(), prog_name="yaf")
def main() -> None:
    """YAF — YuanXu Antenna Forge: AI-driven antenna inverse design."""


@main.command()
def info() -> None:
    """Show versions and which solvers/backends are available on this machine."""
    click.echo(f"YAF version     : {_version()}")
    click.echo(f"Python          : {sys.version.split()[0]}")

    strict = os.environ.get("YAF_NO_FALLBACK", "").strip().lower() in {"1", "true", "yes", "on"}
    click.echo(f"YAF_NO_FALLBACK : {'ON (missing solvers raise errors)' if strict else 'off (analytical fallback allowed, results labeled)'}")

    click.echo("\nSolvers:")
    nec2c = shutil.which("nec2c")
    click.echo(f"  nec2c (MoM)          : {nec2c or 'NOT FOUND -> fallback_analytical'}")
    openems = importlib.util.find_spec("openems") is not None
    click.echo(f"  openEMS (FDTD)       : {'python bindings available' if openems else 'NOT FOUND -> fallback_analytical'}")

    click.echo("\nAI backends:")
    for pkg in ("torch", "jax", "flax", "optax", "scipy"):
        try:
            click.echo(f"  {pkg:<20} : {importlib.metadata.version(pkg)}")
        except importlib.metadata.PackageNotFoundError:
            click.echo(f"  {pkg:<20} : not installed")

    if not (nec2c or openems):
        click.echo(
            "\n⚠  No real EM solver found. Demos run on closed-form analytical models\n"
            "   (clearly labeled). Real-solver setup: docs/next-steps.md, Phase A."
        )


@main.group()
def demo() -> None:
    """Run built-in demos."""


@demo.command()
def dipole() -> None:
    """Half-wave dipole at 2.45 GHz → S11 / VSWR / gain (NEC2 or fallback)."""
    import asyncio

    import numpy as np

    from yaf_core.domain.geometry import Geometry
    from yaf_core.domain.simulation import SimulationSpec
    from yaf_solvers.nec2_adapter.adapter import NEC2Adapter

    async def _run() -> None:
        f_center = 2.45e9
        wavelength = 299792458.0 / f_center
        length = wavelength / 2
        geom = Geometry(
            name="half-wave dipole",
            representation="mesh",
            vertices=[
                [-length / 2, 0.0, 0.0],
                [length / 2, 0.0, 0.0],
                [-length / 2, 0.001, 0.0],
                [length / 2, 0.001, 0.0],
            ],
            faces=[[0, 1, 2], [1, 2, 3]],
        )
        spec = SimulationSpec(
            name="dipole sweep", frequency_range=(2.4e9, 2.5e9), frequency_points=51
        )
        adapter = NEC2Adapter()
        mesh = await adapter.mesh(geom, spec)
        result = await adapter.solve(mesh, spec)

        mode = result.solver_metadata.get("solver_mode", "unknown")
        click.echo(f"Solver: {result.solver_name} v{result.solver_version} [{mode}]")
        if mode == "fallback_analytical":
            click.secho(
                "⚠  ANALYTICAL FALLBACK — closed-form dipole model, not an EM simulation.",
                fg="yellow",
            )
        if result.s_params is not None:
            s11 = [
                20 * float(np.log10(abs(result.s_params.s_matrix[i][0][0]) + 1e-12))
                for i in range(len(result.s_params.frequency))
            ]
            best = int(np.argmin(np.array(s11)))
            click.echo(
                f"Best S11: {s11[best]:.2f} dB @ {result.s_params.frequency[best] / 1e9:.3f} GHz"
            )
        click.echo(f"Gain: {result.gain_dbi:.2f} dBi   VSWR: {result.vswr:.2f}")

    asyncio.run(_run())


@demo.command()
def fdtd() -> None:
    """Differentiable FDTD: verify gradient flow through the EM solver."""
    _run_module("yaf_ai.differentiable.diff_fdtd_jax", ["--demo"])


@demo.command()
@click.option("--epochs", default=2, show_default=True, help="Training epochs.")
def vae(epochs: int) -> None:
    """Train the β-VAE antenna designer and save weights."""
    _run_module("yaf_ai.generative.vae_designer", ["--train", "--epochs", str(epochs)])


@demo.command()
def bayesian() -> None:
    """Bayesian optimization (GP + Expected Improvement) demo."""
    _run_module("yaf_ai.optimization.bayesian", ["--demo"])


@demo.command()
def pipeline() -> None:
    """End-to-end inverse-design pipeline (generate → screen → refine → verify)."""
    _run_module("yaf_ai.inverse_design.pipeline", ["--demo"])


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True)
@click.option("--reload", "reload_", is_flag=True, help="Auto-reload on code changes.")
def serve(host: str, port: int, reload_: bool) -> None:
    """Start the YAF API server (FastAPI + WebSocket)."""
    import uvicorn

    uvicorn.run("yaf_api.main:app", host=host, port=port, reload=reload_)


if __name__ == "__main__":
    main()
