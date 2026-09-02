# ============================================================
# REFERENCE
#   仿造来源：OpenAI function-calling 工具协议（DeepSeek 兼容）
#   关键设计点：
#     - 工具 = 智能体伸向真实物理的手：simulate_patch / simulate_dipole
#       直连 openEMS/NEC2 适配器，run_inverse_design 驱动完整管线
#     - LLM 单位友好（GHz/mm），内部换算 SI（米/赫兹）
#     - 诚实契约贯穿：每个结果都带 solver_mode；fallback_analytical
#       必须显式告知用户是解析估算；工具异常返回 {"error": ...} 让
#       LLM 能向用户解释，绝不静默编数
#     - S11 曲线降采样 ~12 点随结果返回，LLM 可推理曲线形状（谐振
#       偏高/偏低、带宽）并提出下一步调参
# ============================================================

"""
Assistant tool layer — the function-calling bridge to real solvers.

Each tool validates LLM-friendly arguments (GHz/mm), runs the real
adapter or pipeline, and returns a compact, honestly-labeled summary.
"""

from __future__ import annotations

import shutil
from typing import Any

import numpy as np
from pydantic import BaseModel, Field, ValidationError

from yaf_core.domain.simulation import SimulationResult, SimulationSpec

_GHZ = 1e9
_MM = 1e-3


class PatchArgs(BaseModel):
    """simulate_patch arguments (mm / GHz)."""

    width_mm: float = Field(gt=0, le=1000)
    length_mm: float = Field(gt=0, le=1000)
    substrate_thickness_mm: float = Field(default=1.6, gt=0, le=20)
    eps_r: float = Field(default=4.4, ge=1, le=100)
    loss_tangent: float = Field(default=0.02, ge=0, le=1)
    feed_x_mm: float | None = Field(default=None)
    f_min_ghz: float = Field(gt=0, le=100)
    f_max_ghz: float = Field(gt=0, le=100)
    with_far_field: bool = False


class DipoleArgs(BaseModel):
    """simulate_dipole arguments (mm / GHz)."""

    length_mm: float = Field(gt=0, le=10000)
    f_min_ghz: float = Field(gt=0, le=100)
    f_max_ghz: float = Field(gt=0, le=100)


class DesignArgs(BaseModel):
    """run_inverse_design arguments."""

    name: str = "assistant_design"
    f_min_ghz: float = Field(gt=0, le=100)
    f_max_ghz: float = Field(gt=0, le=100)
    target_gain_dbi: float | None = None
    target_vswr: float | None = Field(default=2.0, gt=1)
    target_efficiency: float | None = Field(default=None, gt=0, le=1)
    max_width_mm: float = Field(default=200.0, gt=0, le=5000)
    max_height_mm: float = Field(default=200.0, gt=0, le=5000)
    max_depth_mm: float = Field(default=100.0, gt=0, le=5000)
    candidate_budget: int = Field(default=12, ge=4, le=32)


TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "simulate_patch",
            "description": (
                "Run a REAL openEMS FDTD simulation of a rectangular "
                "microstrip patch antenna (PEC patch on a lossy substrate "
                "over a ground plane, probe-fed). Returns S11 curve "
                "summary, resonance, VSWR; with_far_field=true also "
                "returns real gain/efficiency via NF2FF (slower). Takes "
                "~30-90 s. length_mm is the resonant dimension."
            ),
            "parameters": PatchArgs.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_dipole",
            "description": (
                "Run a REAL solver simulation (NEC2 MoM or openEMS FDTD) "
                "of a center-fed wire dipole of the given total length. "
                "Returns S11 curve summary, resonance, VSWR. Takes ~10-60 s."
            ),
            "parameters": DipoleArgs.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_inverse_design",
            "description": (
                "Run the full AI inverse-design pipeline: generate diverse "
                "antenna candidates around the band, screen them, and "
                "verify the best with a real solver. Use when the user "
                "states requirements but no concrete geometry. Takes "
                "~1-3 min. Check oracle_mode in the result: only "
                "'subprocess'/'native' means real physics."
            ),
            "parameters": DesignArgs.model_json_schema(),
        },
    },
]


def _band(f_min_ghz: float, f_max_ghz: float) -> tuple[float, float]:
    if f_max_ghz <= f_min_ghz:
        raise ValueError("f_max_ghz must be greater than f_min_ghz")
    return (f_min_ghz * _GHZ, f_max_ghz * _GHZ)


def _summary(result: SimulationResult) -> dict[str, Any]:
    """Compact, honestly-labeled result for the LLM."""
    out: dict[str, Any] = {
        "solver_mode": result.solver_metadata.get("solver_mode", "unknown"),
        "engine": result.solver_metadata.get("engine", result.solver_name),
        "simulation_time_sec": round(result.simulation_time_sec, 1),
    }
    if out["solver_mode"] == "fallback_analytical":
        out["warning"] = (
            "ANALYTICAL ESTIMATE, not a real EM simulation — tell the "
            "user explicitly"
        )
    if result.s_params is not None:
        freqs = np.asarray(result.s_params.frequency)
        s11 = np.abs([s[0][0] for s in result.s_params.s_matrix])
        with np.errstate(divide="ignore"):
            s11_db = 20 * np.log10(np.maximum(s11, 1e-12))
        i = int(np.argmin(s11_db))
        step = max(len(freqs) // 12, 1)
        out.update({
            "resonance_ghz": round(float(freqs[i]) / _GHZ, 4),
            "s11_min_db": round(float(s11_db[i]), 2),
            "vswr_at_band_center": (
                round(result.vswr, 2)
                if result.vswr is not None and np.isfinite(result.vswr)
                else "inf"
            ),
            "s11_db_curve": [
                [round(float(f) / _GHZ, 3), round(float(d), 1)]
                for f, d in zip(
                    freqs[::step], s11_db[::step], strict=False
                )
            ],
        })
    if result.gain_dbi is not None:
        out["gain_dbi"] = round(result.gain_dbi, 2)
    if result.efficiency is not None:
        out["radiation_efficiency"] = round(result.efficiency, 3)
    if "nf2ff_warning" in result.solver_metadata:
        out["nf2ff_warning"] = result.solver_metadata["nf2ff_warning"]
    return out


async def _simulate_patch(raw: dict[str, Any]) -> dict[str, Any]:
    from yaf_core.geometry.parametric import ParametricGenerator
    from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

    a = PatchArgs(**raw)
    length_m = a.length_mm * _MM
    feed_inset = 0.0
    if a.feed_x_mm is not None:
        feed_inset = float(
            np.clip(length_m / 2 - a.feed_x_mm * _MM, 0.0, length_m)
        )
    geom = ParametricGenerator.rectangular_patch(
        width=a.width_mm * _MM,
        length=length_m,
        substrate_thickness=a.substrate_thickness_mm * _MM,
        feed_inset=feed_inset,
    )
    geom.metadata.update({
        "eps_r": a.eps_r,
        "loss_tangent": a.loss_tangent,
        "substrate_width": 1.5 * a.width_mm * _MM,
        "substrate_length": 1.5 * a.length_mm * _MM,
        "feed_x": None if a.feed_x_mm is None else a.feed_x_mm * _MM,
    })
    spec = SimulationSpec(
        name="assistant_patch",
        frequency_range=_band(a.f_min_ghz, a.f_max_ghz),
        frequency_points=51,
        far_field_request={} if a.with_far_field else None,
    )
    adapter = OpenEMSAdapter()
    mesh = await adapter.mesh(geom, spec)
    result = await adapter.solve(mesh, spec)
    return {"design": raw, **_summary(result)}


async def _simulate_dipole(raw: dict[str, Any]) -> dict[str, Any]:
    from yaf_core.domain.geometry import Geometry
    from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
    from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

    a = DipoleArgs(**raw)
    half = a.length_mm * _MM / 2
    geom = Geometry(
        name="assistant_dipole",
        representation="mesh",
        vertices=[[0.0, 0.0, -half], [0.0, 0.0, half]],
        faces=[[0, 1]],
        metadata={"length": a.length_mm * _MM, "radius": a.length_mm * _MM / 500},
    )
    spec = SimulationSpec(
        name="assistant_dipole",
        frequency_range=_band(a.f_min_ghz, a.f_max_ghz),
        frequency_points=51,
    )
    nec2 = NEC2Adapter()
    adapter = nec2 if await nec2.health_check() else OpenEMSAdapter()
    mesh = await adapter.mesh(geom, spec)
    result = await adapter.solve(mesh, spec)
    return {"design": raw, **_summary(result)}


async def _run_inverse_design(raw: dict[str, Any]) -> dict[str, Any]:
    from yaf_ai.inverse_design.discovery import AntennaDiscoveryEngine
    from yaf_core.domain.discovery import DiscoveryRequirements, EvaluationMode

    a = DesignArgs(**raw)
    requirements = DiscoveryRequirements(
        name=a.name,
        frequency_range_hz=_band(a.f_min_ghz, a.f_max_ghz),
        target_gain_dbi=a.target_gain_dbi,
        target_vswr=a.target_vswr,
        minimum_efficiency=a.target_efficiency,
        max_dimensions_m=(
            a.max_width_mm * _MM,
            a.max_height_mm * _MM,
            a.max_depth_mm * _MM,
        ),
        candidate_budget=a.candidate_budget,
        generations=2,
        verify_top_k=2,
    )
    candidates, warnings = await AntennaDiscoveryEngine(requirements).run()
    best = candidates[0]
    verified = [
        candidate
        for candidate in candidates
        if candidate.evaluation_mode == EvaluationMode.REAL_SOLVER
    ]

    out: dict[str, Any] = {
        "oracle_mode": best.solver_mode or "analytical_screening",
        "converged": best.score >= 0.75,
        # non-finite floats (VSWR=inf) are not valid JSON — stringify
        "metrics": {
            "score": round(best.score, 3),
            "resonance_ghz": round(best.metrics.resonance_hz / _GHZ, 4),
            "bandwidth_mhz": round(best.metrics.bandwidth_hz / 1e6, 1),
            "gain_dbi": round(best.metrics.gain_dbi, 2),
            "vswr": round(best.metrics.vswr, 2),
            "efficiency": round(best.metrics.efficiency, 3),
        },
        "candidates_generated": len(candidates),
        "topologies_explored": sorted({
            candidate.topology.value for candidate in candidates
        }),
        "verified_candidates": len(verified),
    }
    if not verified:
        out["warning"] = (
            "verification did NOT run on a real solver — treat metrics "
            "as estimates and tell the user"
        )
    if warnings:
        out["discovery_warnings"] = warnings
    out["best_geometry"] = {
        "candidate_id": str(best.id),
        "name": best.name,
        "topology": best.topology.value,
        "dimensions_mm": [
            round(value * 1000, 2) for value in best.metrics.dimensions_m
        ],
        "parameters_mm": {
            key: round(value * 1000, 2)
            for key, value in best.parameters.items()
            if key.endswith("_m")
        },
        "dimensionless_parameters": {
            key: round(value, 4)
            for key, value in best.parameters.items()
            if not key.endswith("_m")
        },
        "vertices": best.geometry.vertices,
        "faces": best.geometry.faces,
    }
    if verified:
        out["verification"] = {
            "candidate_id": str(verified[0].id),
            "solver_mode": verified[0].solver_mode,
            "solver_name": verified[0].solver_name,
        }
    return out


_HANDLERS = {
    "simulate_patch": _simulate_patch,
    "simulate_dipole": _simulate_dipole,
    "run_inverse_design": _run_inverse_design,
}


async def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run one tool call; errors come back as {"error": ...} for the LLM."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return await handler(args)
    except ValidationError as e:
        return {"error": f"invalid arguments: {e.errors()}"}
    except Exception as e:  # noqa: BLE001 — surface to the LLM, never crash the stream
        return {"error": f"{type(e).__name__}: {e}"}


async def solver_availability() -> dict[str, bool]:
    """Which real solvers this host can actually run (for the prompt)."""
    from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
    from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

    openems = OpenEMSAdapter()
    nec2 = NEC2Adapter()
    return {
        "openems": openems._openems_available or openems._resolve_executable() is not None,
        "nec2": shutil.which(nec2.executable) is not None,
    }
