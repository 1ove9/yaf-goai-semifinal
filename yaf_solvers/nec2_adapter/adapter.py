# ============================================================
# REFERENCE
#   仿造来源：necpp (PyNEC) @ https://github.com/tmolteno/necpp
#             + xnec2c @ https://github.com/KJ7LNW/xnec2c
#   对标文件：necpp/example/test.py, xnec2c/src/
#   对标类/函数：nec_context, get_geometry().wire(), gn_card(), ex_card(), fr_card(), rp_card()
#   关键设计点：
#     - NEC2 经典卡片体系（GW/GE/GN/EX/FR/RP/LD…）
#     - MoM 电场积分方程（EFIE）线栅近似
#     - 频率扫描通过 FR 卡片控制
#     - 远场辐射模式通过 RP 卡片请求
#     - xnec2c fork-based 多进程频率扫描
#   YAF 的差异化改造：
#     - Python 端 NEC2CardWriter 抽象卡片生成（非 C 字符串拼接）
#     - 异步 async/await 包装 subprocess 调用
#     - 自动降级：nec2c 不可用时走 induced EMF 解析模型
#     - 从 NEC 输出解析 INPUT IMPEDANCE 和 MAX GAIN
#     - 从阻抗计算 S11（Γ = (Z-Z0)/(Z+Z0)）
# ============================================================

"""
NEC2 MoM solver adapter — complete implementation.

Generates NEC-2 input card deck, runs nec2c, and parses the output
into canonical SimulationResult.

NEC (Numerical Electromagnetics Code) is a MoM solver for wire and
surface structures, developed at LLNL.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from yaf_core.domain.geometry import Geometry, Mesh
from yaf_core.domain.simulation import (
    FarFieldResult,
    SimulationResult,
    SimulationSpec,
    SParamResult,
)
from yaf_solvers.base import BaseSolverAdapter, MeshError
from yaf_solvers.nec2_adapter.card_writer import NEC2CardWriter
from yaf_solvers.nec2_adapter.output_parser import (
    FrequencyBlock,
    NEC2ParseError,
    parse_nec2_output,
)


class NEC2Adapter(BaseSolverAdapter):
    """MoM solver adapter for NEC2.

    Wraps the nec2c command-line executable.
    """

    name = "nec2"
    version = "2.0"
    supports = {"mom"}

    def __init__(self, executable: str = "nec2c") -> None:
        super().__init__()
        self.executable = executable
        self._runner: list[str] | None = None
        self._runner_probed = False

    def _resolve_runner(self) -> list[str] | None:
        """Command prefix that reaches a real nec2c, or None.

        Tries the native binary on PATH first; on Windows falls back to
        nec2c inside WSL. The WSL route runs the same real MoM solver —
        only the process boundary and path syntax differ — so results
        keep ``solver_mode="subprocess"``.
        """
        if self._runner_probed:
            return self._runner
        self._runner_probed = True
        if shutil.which(self.executable):
            self._runner = [self.executable]
        elif os.name == "nt" and shutil.which("wsl"):
            try:
                # binary capture: wsl.exe emits its own error messages in
                # UTF-16, which text=True would decode with the console
                # codepage and blow up in the reader thread
                probe = subprocess.run(
                    ["wsl", "--", "which", self.executable],
                    capture_output=True, timeout=15,
                )
                stdout = probe.stdout.decode("utf-8", errors="replace")
                if probe.returncode == 0 and stdout.strip():
                    self._runner = ["wsl", "--", self.executable]
            except (OSError, subprocess.SubprocessError):
                self._runner = None
        return self._runner

    @staticmethod
    def _solver_path(path: Path, runner: list[str]) -> str:
        """Translate a host path into the solver process's view of it.

        WSL sees Windows drives under /mnt/<drive>/; native runs get the
        path unchanged.
        """
        if runner[0] != "wsl":
            return str(path)
        s = str(path.resolve())
        drive = s[0].lower()
        rest = s[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"

    async def capabilities(self) -> dict[str, Any]:
        caps = await super().capabilities()
        caps.update({
            "methods": ["mom"],
            "frequency_range": [1e3, 100e9],
            "max_cells": 50000,
            "gpu_support": False,
            "excitation_types": ["lumped", "plane_wave"],
            "structure_types": ["wire", "surface_patch"],
        })
        return caps

    async def mesh(self, geometry: Geometry, spec: SimulationSpec) -> Mesh:
        """Generate MoM wire segmentation.

        NEC2 models *wires*: each 2-node face becomes one wire. Surface
        meshes are rejected — truncating a triangle to its first edge
        (the previous behavior) produces overlapping bogus wires whose
        results look plausible but are physically meaningless.
        """
        job_id = str(uuid.uuid4())
        wire_edges = [[f[0], f[1]] for f in geometry.faces if len(f) == 2]
        if geometry.faces and not wire_edges:
            raise MeshError(
                "NEC2 is a wire-grid MoM solver but this geometry contains "
                "only surface faces (3+ nodes). Represent the antenna as "
                "wire edges (2-node faces), or use a surface/volume solver "
                "such as openEMS."
            )
        try:
            mesh = Mesh(
                geometry_id=geometry.id,
                solver_name=self.name,
                nodes=geometry.vertices,
                elements=wire_edges,
                element_type="wire",
                metadata={"job_id": job_id, **geometry.metadata},
            )
            return mesh
        except Exception as e:
            raise MeshError(f"NEC2 meshing failed: {e}") from e

    async def solve(
        self,
        mesh: Mesh,
        spec: SimulationSpec,
        progress_callback: Callable[[float], None] | None = None,
    ) -> SimulationResult:
        """Run NEC2 MoM simulation.

        Generates .nec input file, runs nec2c, and parses the output.
        """
        job_id = str(mesh.id)

        with tempfile.TemporaryDirectory(prefix="nec2_") as tmpdir:
            tmp = Path(tmpdir)

            # Build NEC input deck
            writer = self._build_nec_deck(mesh, spec)

            inp_path = tmp / "simulation.nec"
            out_path = tmp / "simulation.out"

            writer.write_file(str(inp_path))

            # Execute NEC2 (native, or through the WSL bridge on Windows)
            runner = self._resolve_runner()
            if runner is None:
                return self._compute_analytical(mesh, spec, job_id)
            timeout_seconds = self._timeout_seconds(spec)
            t0 = time.monotonic()
            try:
                result = subprocess.run(
                    [
                        *runner,
                        "-i", self._solver_path(inp_path, runner),
                        "-o", self._solver_path(out_path, runner),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
                if result.returncode != 0:
                    return self._compute_analytical(mesh, spec, job_id)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return self._compute_analytical(mesh, spec, job_id)
            elapsed = time.monotonic() - t0

            if not out_path.exists():
                return self._compute_analytical(mesh, spec, job_id)
            try:
                parsed = self._parse_nec_output(out_path, spec, job_id, elapsed)
            except NEC2ParseError:
                # Real solver produced unusable output — degrade explicitly
                # (or raise, under YAF_NO_FALLBACK), never patch with defaults.
                return self._compute_analytical(mesh, spec, job_id)
            parsed.solver_metadata["runner"] = " ".join(runner)
            return parsed

    @staticmethod
    def _timeout_seconds(spec: SimulationSpec) -> float:
        """Return the positive subprocess timeout, preserving the 300 s default."""

        timeout = float(spec.solver_settings.get("nec2_timeout_seconds", 300.0))
        if not math.isfinite(timeout) or timeout <= 0.0:
            raise ValueError("nec2_timeout_seconds must be finite and positive")
        return timeout

    def _build_nec_deck(self, mesh: Mesh, spec: SimulationSpec) -> NEC2CardWriter:
        """Build NEC2 card deck from mesh and spec."""
        writer = NEC2CardWriter(title=spec.name or "YAF NEC2 Simulation")

        # Add geometry from mesh as wires
        wire_class = str(mesh.metadata.get("antenna_class", ""))
        native_centerline = wire_class in {
            "meander_dipole",
            "box_straight_dipole",
            "freeform_wire_3d",
            "day6_ocfd",
            "day6_straight_dipole",
        }
        default_segments_per_wire = 11
        segments_per_wavelength = int(
            spec.solver_settings.get("nec2_segments_per_wavelength", 20)
        )
        if segments_per_wavelength < 1:
            raise ValueError("nec2_segments_per_wavelength must be positive")
        wire_radius = float(mesh.metadata.get("wire_radius_m", 0.001))
        feed_segments = default_segments_per_wire
        if mesh.nodes and mesh.elements:
            for ei, elem in enumerate(mesh.elements):
                if len(elem) >= 2:
                    i0, i1 = elem[0], elem[1]
                    if i0 < len(mesh.nodes) and i1 < len(mesh.nodes):
                        p0 = mesh.nodes[i0]
                        p1 = mesh.nodes[i1]
                        segments_per_wire = default_segments_per_wire
                        if native_centerline:
                            electrical_length = math.dist(p0, p1)
                            max_segment_length = (
                                299_792_458.0
                                / spec.frequency_range[1]
                                / segments_per_wavelength
                            )
                            segments_per_wire = max(
                                1,
                                math.ceil(electrical_length / max_segment_length),
                            )
                            if segments_per_wire % 2 == 0:
                                segments_per_wire += 1
                        if ei == 0:
                            feed_segments = segments_per_wire
                        writer.cards.append(writer.gw_card(
                            tag=ei + 1,
                            segments=segments_per_wire,
                            x1=p0[0], y1=p0[1], z1=p0[2],
                            x2=p1[0], y2=p1[1], z2=p1[2],
                            radius=wire_radius,
                        ))
        else:
            # Default: half-wave dipole at center frequency
            f_center = sum(spec.frequency_range) / 2
            wavelength = 3e8 / f_center
            length = wavelength / 2
            feed_segments = 21
            writer.add_dipole(
                length=length, radius=wavelength / 1000, tag=1,
                segments=feed_segments,
            )

        # Free space: GE 0 with no GN card. (GE 0 + GN would request a
        # ground plane the geometry flag says isn't there.)
        writer.cards.append(writer.ge_card(0))

        # Excitation at the center segment of the first wire — an odd
        # segment count puts a segment midpoint exactly at the feed.
        center_segment = feed_segments // 2 + 1
        writer.cards.append(
            writer.ex_card(excitation_type=0, tag=1, segment=center_segment)
        )

        # Frequency sweep
        f_min_mhz = spec.frequency_range[0] / 1e6
        f_max_mhz = spec.frequency_range[1] / 1e6
        writer.cards.append(
            writer.fr_card(frequency_range=(f_min_mhz, f_max_mhz, spec.frequency_points))
        )

        # Radiation pattern request: full theta sweep at 4 phi cuts by
        # default, so the peak-gain search sees the main lobe of endfire
        # arrays too (a single phi=0 cut misses broadside/backfire lobes).
        day6_s11_only = wire_class in {
            "freeform_wire_3d",
            "day6_ocfd",
            "day6_straight_dipole",
        }
        if spec.far_field_request is not None or not day6_s11_only:
            n_phi = 5
            if spec.far_field_request:
                n_phi = int(spec.far_field_request.get("n_phi", n_phi))
            dphi = 360.0 / max(n_phi - 1, 1)
            writer.cards.append(
                writer.rp_card(n_theta=37, n_phi=n_phi, dtheta=5.0, dphi=dphi)
            )
        else:
            writer.cards.append(writer.xq_card())

        return writer

    def _parse_nec_output(
        self, out_path: Path, spec: SimulationSpec, job_id: str,
        elapsed_sec: float = 0.0,
    ) -> SimulationResult:
        """Build a SimulationResult from real nec2c output.

        Every value comes from the solver output: S11(f) from the per-
        frequency input impedance, gain from the radiation-pattern table,
        efficiency from the power budget. Raises :class:`NEC2ParseError`
        if a required section is missing — no silent defaults.
        """
        return self._result_from_nec_text(
            out_path.read_text(errors="replace"), job_id, elapsed_sec,
            f_center=sum(spec.frequency_range) / 2,
        )

    def _result_from_nec_text(
        self, text: str, job_id: str, elapsed_sec: float = 0.0,
        f_center: float | None = None,
    ) -> SimulationResult:
        blocks = parse_nec2_output(text)

        z0 = 50.0
        freqs = [b.frequency_hz for b in blocks]
        s_matrix: list[list[list[complex]]] = []
        for b in blocks:
            assert b.impedance is not None  # guaranteed by the parser
            s_matrix.append([[(b.impedance - z0) / (b.impedance + z0)]])

        # Far field and scalar metrics from the block nearest center frequency
        if f_center is None:
            f_center = (freqs[0] + freqs[-1]) / 2
        center = min(blocks, key=lambda b: abs(b.frequency_hz - f_center))

        # Report gain at the operating (center) frequency; a max over the
        # whole sweep would quote e.g. a 0.58λ dipole's 2.33 dBi for a
        # design meant to run at λ/2.
        gain_dbi = center.max_gain_dbi()
        if gain_dbi is None:
            gains = [g for b in blocks if (g := b.max_gain_dbi()) is not None]
            gain_dbi = max(gains) if gains else None

        result = SimulationResult(
            job_id=uuid.UUID(job_id),
            solver_name=self.name,
            solver_version=self.version,
            status="success",
            s_params=SParamResult(frequency=freqs, s_matrix=s_matrix, z0=z0),
            far_field=self._far_field_from_block(center),
            gain_dbi=gain_dbi,
            efficiency=center.efficiency,
            vswr=self._compute_vswr_from_impedance(center.impedance or 0j, z0),
            simulation_time_sec=elapsed_sec,
        )
        result.solver_metadata["n_frequency_points"] = len(blocks)
        result.solver_metadata["executable"] = self.executable
        return self._mark_solver_mode(result, "subprocess")

    @staticmethod
    def _far_field_from_block(block: FrequencyBlock) -> FarFieldResult | None:
        """Reassemble the RP table rows into theta×phi field matrices."""
        if not block.pattern:
            return None
        thetas = sorted({p.theta_deg for p in block.pattern})
        phis = sorted({p.phi_deg for p in block.pattern})
        t_idx = {v: i for i, v in enumerate(thetas)}
        p_idx = {v: i for i, v in enumerate(phis)}
        e_theta = [[0j for _ in phis] for _ in thetas]
        e_phi = [[0j for _ in phis] for _ in thetas]
        for p in block.pattern:
            e_theta[t_idx[p.theta_deg]][p_idx[p.phi_deg]] = p.e_theta
            e_phi[t_idx[p.theta_deg]][p_idx[p.phi_deg]] = p.e_phi
        return FarFieldResult(
            theta=thetas, phi=phis, e_theta=e_theta, e_phi=e_phi,
            frequency=block.frequency_hz,
        )

    @staticmethod
    def dipole_impedance_induced_emf(
        frequency_hz: float, length_m: float, wire_radius_m: float = 0.001
    ) -> complex:
        """Input impedance of a center-fed thin-wire dipole (induced EMF method).

        Balanis, *Antenna Theory* 4th ed., eqs. (8-60a)/(8-61a). Exact within the
        sinusoidal-current assumption: a half-wave dipole evaluates to the
        textbook 73.1 + j42.5 Ω. Valid for L ≲ λ (breaks down past resonance of
        the sinusoidal current model).
        """
        from scipy.special import sici  # noqa: PLC0415

        eta = 376.730313668  # free-space impedance
        euler = 0.5772156649015329
        k = 2 * math.pi * frequency_hz / 299792458.0
        kl = k * length_m
        si_kl, ci_kl = (float(x) for x in sici(kl))
        si_2kl, ci_2kl = (float(x) for x in sici(2 * kl))
        ci_a = float(sici(2 * k * wire_radius_m**2 / length_m)[1])

        r_m = (eta / (2 * math.pi)) * (
            euler
            + math.log(kl)
            - ci_kl
            + 0.5 * math.sin(kl) * (si_2kl - 2 * si_kl)
            + 0.5 * math.cos(kl) * (euler + math.log(kl / 2) + ci_2kl - 2 * ci_kl)
        )
        x_m = (eta / (4 * math.pi)) * (
            2 * si_kl
            + math.cos(kl) * (2 * si_kl - si_2kl)
            - math.sin(kl) * (2 * ci_kl - ci_2kl - ci_a)
        )
        # Refer from current maximum to the input terminals
        sin_half = math.sin(kl / 2)
        if abs(sin_half) < 1e-6:
            return complex(r_m, x_m)
        scale = 1.0 / (sin_half**2)
        return complex(r_m * scale, x_m * scale)

    def _compute_analytical(
        self, mesh: Mesh, spec: SimulationSpec, job_id: str
    ) -> SimulationResult:
        """Compute results analytically when NEC2 is unavailable.

        Uses the induced EMF method (Balanis eq. 8-60/8-61) for a thin-wire
        dipole. This is a real closed-form model — correct for straight
        center-fed dipoles, WRONG for any other topology — and the result is
        explicitly labeled ``solver_mode="fallback_analytical"``.
        """
        self._require_fallback_allowed(job_id, f"'{self.executable}' not found or failed")

        f_min, f_max = spec.frequency_range
        f_center = (f_min + f_max) / 2
        wavelength = 3e8 / f_center

        # Estimate length from mesh
        half_len = wavelength / 4
        if mesh.nodes:
            v = np.array(mesh.nodes)
            extent = np.max(v, axis=0) - np.min(v, axis=0)
            half_len = float(np.max(extent)) / 2

        # Induced EMF method for center-fed dipole
        z0 = 50.0
        freqs = np.linspace(f_min, f_max, spec.frequency_points).tolist()

        s_matrix: list[list[list[complex]]] = []
        for f in freqs:
            imp = self.dipole_impedance_induced_emf(f, 2 * half_len)
            gamma = (imp - z0) / (imp + z0)
            s_matrix.append([[gamma]])

        # Far field (standard dipole pattern)
        theta = np.linspace(0, np.pi, 181).tolist()
        phi = [0.0]
        e_theta = []
        e_phi = []
        for t in theta:
            if math.sin(t) < 0.001:
                e_theta.append([complex(0, 0)])
            else:
                pattern = math.cos(math.pi / 2 * math.cos(t)) / math.sin(t)
                e_theta.append([complex(pattern, 0)])
            e_phi.append([complex(0, 0)])

        result = SimulationResult(
            job_id=uuid.UUID(job_id),
            solver_name=self.name,
            solver_version=self.version,
            status="success",
            s_params=SParamResult(frequency=freqs, s_matrix=s_matrix),
            far_field=FarFieldResult(
                theta=theta, phi=phi, e_theta=e_theta, e_phi=e_phi,
                frequency=f_center,
            ),
            gain_dbi=2.15,  # half-wave dipole directivity — only valid for the dipole model above
            efficiency=0.95,
            vswr=(1 + abs(s_matrix[len(s_matrix)//2][0][0])) / (1 - abs(s_matrix[len(s_matrix)//2][0][0])),
            simulation_time_sec=0.3,
        )
        return self._mark_solver_mode(result, "fallback_analytical")

    def to_native_format(self, geometry: Geometry) -> bytes:
        """Convert geometry to NEC2 .nec format."""
        writer = NEC2CardWriter()

        if geometry.vertices and geometry.faces:
            for ei, face in enumerate(geometry.faces):
                if len(face) >= 2:
                    i0, i1 = face[0], face[1]
                    if i0 < geometry.num_vertices and i1 < geometry.num_vertices:
                        p0 = geometry.vertices[i0]
                        p1 = geometry.vertices[i1]
                        writer.gw_card(ei + 1, 11, p0[0], p0[1], p0[2], p1[0], p1[1], p1[2], 0.001)
        else:
            writer.add_dipole(length=0.5, tag=1)

        writer.cards.append(writer.ge_card(0))
        writer.cards.append(writer.gn_card(0))
        writer.cards.append(writer.ex_card(0, 1, 6))
        writer.cards.append(writer.fr_card(1000.0))
        writer.cards.append(writer.rp_card())

        return writer.to_bytes()

    async def from_native_result(self, raw_output: bytes) -> SimulationResult:
        """Parse NEC2 output text."""
        return self._result_from_nec_text(
            raw_output.decode("utf-8", errors="replace"), str(uuid.uuid4())
        )

    @staticmethod
    def _compute_vswr_from_impedance(impedance: complex, z0: float) -> float:
        gamma = abs((impedance - z0) / (impedance + z0))
        if gamma >= 1:
            return float("inf")
        return (1 + gamma) / (1 - gamma)

    async def health_check(self) -> bool:
        """True only when a real nec2c is reachable (PATH or WSL bridge).

        Unreachable means every solve degrades to the analytical
        fallback — that must show up as unhealthy, not be papered over.
        """
        return self._resolve_runner() is not None
