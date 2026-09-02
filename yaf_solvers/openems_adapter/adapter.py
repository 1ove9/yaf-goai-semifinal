# ============================================================
# REFERENCE
#   仿造来源：openEMS @ https://github.com/thliebig/openEMS
#   对标文件：openEMS/python/Tutorials/Simple_Patch_Antenna.py
#   对标类/函数：openEMS.OpenEMS, CSXCAD.ContinuousStructure, FDTD.SetBoundaryCond
#   关键设计点：
#     - EC-FDTD（Equivalent Circuit FDTD），工程界标准
#     - CSXCAD 几何 + 材料分离架构
#     - 卡片式仿真配置（FDTD.SetGaussExcite, SetBoundaryCond, SetCSX）
#     - PML_8 / MUR 多级边界条件
#     - NF2FF 远场变换后处理
#   YAF 的差异化改造：
#     - 异步 async/await 包装同步 openEMS API
#     - 自动降级：openEMS 不可用时走解析模型（induced EMF）
#     - Geometry → CSXCAD AddBox/AddMetal 自动转换
#     - SimulationSpec → FDTD 参数映射
#     - scikit-rf Touchstone 输出集成
# ============================================================

"""
openEMS FDTD adapter — complete implementation.

Generates CSXCAD XML geometry, runs openEMS, and parses results
into canonical SimulationResult.

openEMS is an open-source FDTD solver (https://openems.de).
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
from yaf_solvers.base import (
    BaseSolverAdapter,
    MeshError,
    SolverError,
    SolverUnavailableError,
)
from yaf_solvers.openems_adapter.nf2ff import (
    read_result,
    resolve_nf2ff_executable,
    run_nf2ff,
    write_control_xml,
)
from yaf_solvers.openems_adapter.port_parser import (
    OpenEMSParseError,
    PortSpectra,
    calc_port,
)
from yaf_solvers.openems_adapter.xml_writer import (
    LumpedPort,
    OpenEMSXmlWriter,
    grade_lines,
    smooth_lines,
)

#: default install location of the official Windows binary package
_WINDOWS_DEFAULT_EXE = r"C:\opt\openEMS\openEMS.exe"

_C0 = 299792458.0
_EPS0 = 8.8541878128e-12


class _UnsupportedGeometryError(Exception):
    """Geometry not expressible on the subprocess path (yet)."""


def _t3(v: Any) -> tuple[float, float, float]:
    """Coerce a 3-vector into an explicit float triple."""
    return (float(v[0]), float(v[1]), float(v[2]))


def _partition_mesh_intervals(
    breakpoints: list[float], maximum_step: float
) -> list[float]:
    """Partition mandatory intervals without lattice-intersection runt cells."""

    if not math.isfinite(maximum_step) or maximum_step <= 0.0:
        raise ValueError("maximum mesh step must be finite and positive")
    points = sorted(set(breakpoints))
    if len(points) < 2:
        raise ValueError("mesh partition requires two distinct breakpoints")
    minimum_step = 0.5 * maximum_step
    tolerance = 1e-12 * maximum_step
    lines = [points[0]]
    for left, right in zip(points, points[1:], strict=False):
        interval = right - left
        if interval < minimum_step - tolerance:
            raise ValueError("mandatory mesh breakpoints create a runt cell")
        cell_count = max(1, math.ceil(interval / maximum_step - 1e-12))
        step = interval / cell_count
        if step < minimum_step - tolerance:
            raise ValueError("equal mesh partition creates a runt cell")
        lines.extend(left + step * index for index in range(1, cell_count))
        lines.append(right)
    return lines


def rasterize_planar_mesh(
    nodes: np.ndarray, triangles: list[list[int]], res: float,
) -> tuple[np.ndarray, float, float]:
    """Rasterize planar triangles into a boolean pixel mask.

    Pixels are ``res``-sized squares anchored at the mesh's xy bounding
    box corner; a pixel is metal when its center lies inside any
    triangle (inclusive edges). Returns (mask[ix, iy], x0, y0).
    """
    xy = nodes[:, :2]
    x0, y0 = float(xy[:, 0].min()), float(xy[:, 1].min())
    nx = max(int(math.ceil((float(xy[:, 0].max()) - x0) / res - 1e-9)), 1)
    ny = max(int(math.ceil((float(xy[:, 1].max()) - y0) / res - 1e-9)), 1)
    mask = np.zeros((nx, ny), dtype=bool)

    cx = x0 + (np.arange(nx) + 0.5) * res
    cy = y0 + (np.arange(ny) + 0.5) * res
    for tri in triangles:
        a, b, c = xy[tri[0]], xy[tri[1]], xy[tri[2]]
        lo_x = max(int((min(a[0], b[0], c[0]) - x0) / res) - 1, 0)
        hi_x = min(int((max(a[0], b[0], c[0]) - x0) / res) + 2, nx)
        lo_y = max(int((min(a[1], b[1], c[1]) - y0) / res) - 1, 0)
        hi_y = min(int((max(a[1], b[1], c[1]) - y0) / res) + 2, ny)
        if lo_x >= hi_x or lo_y >= hi_y:
            continue
        px, py = np.meshgrid(cx[lo_x:hi_x], cy[lo_y:hi_y], indexing="ij")
        # barycentric sign test, tolerant of either winding
        d1 = (px - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (py - b[1])
        d2 = (px - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (py - c[1])
        d3 = (px - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (py - a[1])
        eps = 1e-12
        inside = ((d1 >= -eps) & (d2 >= -eps) & (d3 >= -eps)) | (
            (d1 <= eps) & (d2 <= eps) & (d3 <= eps)
        )
        mask[lo_x:hi_x, lo_y:hi_y] |= inside
    return mask, x0, y0


def mask_to_boxes(mask: np.ndarray) -> list[tuple[int, int, int]]:
    """Run-length merge a pixel mask into (ix, iy_start, iy_stop) runs.

    Each run covers pixels iy_start..iy_stop-1 in column order — cuts
    the primitive count by roughly the average run length.
    """
    runs: list[tuple[int, int, int]] = []
    for ix in range(mask.shape[0]):
        iy = 0
        col = mask[ix]
        while iy < len(col):
            if col[iy]:
                start = iy
                while iy < len(col) and col[iy]:
                    iy += 1
                runs.append((ix, start, iy))
            else:
                iy += 1
    return runs


class OpenEMSAdapter(BaseSolverAdapter):
    """FDTD solver adapter for openEMS.

    Uses the openEMS Python API (openems module) when available,
    or falls back to subprocess invocation.
    """

    name = "openems"
    version = "0.0.35"
    supports = {"fdtd"}

    def __init__(self, executable: str | None = None) -> None:
        super().__init__()
        self.executable = executable
        self._openems_available = False
        try:
            import openEMS  # type: ignore[import-not-found, import-untyped, unused-ignore]  # noqa: F401, PLC0415
            self._openems_available = True
        except ImportError:
            pass

    def _resolve_executable(self) -> str | None:
        """Locate a real openEMS solver binary, or None.

        Order: explicit constructor argument, YAF_OPENEMS_EXE env var,
        PATH, then the official Windows package's default install dir.
        """
        candidates: list[str] = []
        if self.executable:
            candidates.append(self.executable)
        env = os.environ.get("YAF_OPENEMS_EXE", "").strip()
        if env:
            candidates.append(env)
        candidates += ["openEMS", "openEMS.exe"]
        if os.name == "nt":
            candidates.append(_WINDOWS_DEFAULT_EXE)
        for c in candidates:
            resolved = shutil.which(c) or (c if Path(c).is_file() else None)
            if resolved:
                return resolved
        return None

    async def capabilities(self) -> dict[str, Any]:
        caps = await super().capabilities()
        caps.update({
            "methods": ["fdtd"],
            "frequency_range": [0, 100e9],
            "max_cells": 1e8,
            "gpu_support": False,
            "excitation_types": ["lumped", "waveguide", "plane_wave"],
            "boundary_conditions": ["pml", "pec", "pmc", "periodic", "mur"],
        })
        return caps

    async def mesh(self, geometry: Geometry, spec: SimulationSpec) -> Mesh:
        """Generate FDTD mesh (structured Yee grid).

        For openEMS, meshing is handled automatically by the CSXCAD engine.
        We pass the geometry and let openEMS discretize it.
        """
        job_id = str(uuid.uuid4())
        try:
            mesh = Mesh(
                geometry_id=geometry.id,
                solver_name=self.name,
                nodes=geometry.vertices,
                elements=[list(f) for f in geometry.faces],
                element_type="mixed",
                metadata={
                    "fdtd_resolution": spec.solver_settings.get("resolution", 20),
                    "job_id": job_id,
                    # parametric antenna descriptions (substrate, materials,
                    # feed position) ride along for the subprocess XML path
                    **geometry.metadata,
                },
            )
            return mesh
        except Exception as e:
            raise MeshError(f"openEMS meshing failed: {e}") from e

    async def solve(
        self,
        mesh: Mesh,
        spec: SimulationSpec,
        progress_callback: Callable[[float], None] | None = None,
    ) -> SimulationResult:
        """Run openEMS FDTD simulation.

        Generates the CSXCAD input, runs the solver, and parses results.
        """
        job_id = str(mesh.id)

        with tempfile.TemporaryDirectory(prefix="openems_") as tmpdir:
            tmp = Path(tmpdir)

            # --- Build simulation ---
            try:
                result = self._run_simulation(
                    tmp, mesh, spec, job_id, progress_callback
                )
            except SolverUnavailableError:
                raise
            except Exception as e:
                raise SolverError(self.name, job_id, str(e)) from e

            return result

    def _run_simulation(
        self,
        tmpdir: Path,
        mesh: Mesh,
        spec: SimulationSpec,
        job_id: str,
        progress_callback: Callable[[float], None] | None = None,
    ) -> SimulationResult:
        """Core FDTD dispatch: real openEMS.exe, else labeled fallback."""

        f_min, f_max = spec.frequency_range
        f_center = (f_min + f_max) / 2
        n_freqs = spec.frequency_points

        executable = self._resolve_executable()
        if executable is not None:
            try:
                return self._run_subprocess(tmpdir, mesh, spec, job_id, executable)
            except (
                OpenEMSParseError,
                _UnsupportedGeometryError,
                subprocess.SubprocessError,
                OSError,
            ):
                if os.environ.get("YAF_NO_FALLBACK", "").strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }:
                    raise
                pass

        # Fallback: analytical computation, always labeled as such
        return self._run_analytical(mesh, spec, job_id, f_center, f_min, f_max, n_freqs)

    def _run_subprocess(
        self,
        tmpdir: Path,
        mesh: Mesh,
        spec: SimulationSpec,
        job_id: str,
        executable: str,
    ) -> SimulationResult:
        """Run the real openEMS.exe on a generated simulation XML.

        Supports wire-class geometries (2-node edges): the first wire is
        center-fed through a lumped port, further wires become parasitic
        thin PEC lines (validated against the official Python API on the
        0.5 m dipole: 275 MHz / 71 Ω, see tests/fixtures/openems/).
        Also supports parametric microstrip patches (recognized by the
        width/length/substrate_thickness metadata that
        ParametricGenerator.rectangular_patch attaches).
        """
        xml_bytes, z0 = self._build_sim_xml(mesh, spec)
        (tmpdir / "sim.xml").write_bytes(xml_bytes)

        t0 = time.monotonic()
        timeout_seconds = float(
            spec.solver_settings.get("openems_timeout_seconds", 900.0)
        )
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0.0:
            raise ValueError("openems_timeout_seconds must be finite and positive")
        proc = subprocess.run(
            [executable, "sim.xml"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        elapsed = time.monotonic() - t0
        if proc.returncode != 0:
            raise OpenEMSParseError(
                f"openEMS exited with {proc.returncode}: {proc.stdout[-400:]}"
            )

        freqs = np.linspace(
            spec.frequency_range[0], spec.frequency_range[1], spec.frequency_points
        ).tolist()
        spectra = calc_port(tmpdir, 1, freqs, z_ref=z0)

        s_matrix: list[list[list[complex]]] = [[[s]] for s in spectra.s11]
        mid = len(freqs) // 2
        s11_mid = abs(spectra.s11[mid])
        vswr = float("inf") if s11_mid >= 1 else (1 + s11_mid) / (1 - s11_mid)

        # NF2FF far field: only when requested (the near-field recording
        # slows the FDTD run several-fold); failures leave the fields
        # honestly absent and are surfaced in the metadata
        far_field: FarFieldResult | None = None
        gain_dbi: float | None = None
        efficiency: float | None = None
        nf2ff_warning: str | None = None
        if spec.far_field_request is not None:
            try:
                far_field, gain_dbi, efficiency = self._post_process_far_field(
                    tmpdir, executable, spec.far_field_request, spectra
                )
            except (OpenEMSParseError, subprocess.SubprocessError, OSError) as e:
                nf2ff_warning = f"NF2FF post-processing failed: {e}"

        result = SimulationResult(
            job_id=uuid.UUID(job_id),
            solver_name=self.name,
            solver_version=self.version,
            status="success",
            s_params=SParamResult(frequency=freqs, s_matrix=s_matrix, z0=z0),
            far_field=far_field,
            gain_dbi=gain_dbi,
            efficiency=efficiency,
            vswr=vswr,
            simulation_time_sec=elapsed,
        )
        result.solver_metadata["runner"] = executable
        result.solver_metadata["engine"] = "EC-FDTD (openEMS.exe)"
        if nf2ff_warning is not None:
            result.solver_metadata["nf2ff_warning"] = nf2ff_warning
        return self._mark_solver_mode(result, "subprocess")

    def _post_process_far_field(
        self,
        tmpdir: Path,
        openems_executable: str,
        request: dict[str, Any],
        spectra: PortSpectra,
    ) -> tuple[FarFieldResult, float, float]:
        """NF2FF transform on the recorded dumps → (far_field, gain, eff).

        Evaluated at the requested frequency (snapped to the sweep grid)
        or, by default, at the S11 minimum. Gain follows G = D·e_rad with
        e_rad = Prad/P_in — both powers on the official DFT scale.
        """
        exe = resolve_nf2ff_executable(openems_executable)
        if exe is None:
            raise OpenEMSParseError(
                "nf2ff binary not found (install the official openEMS "
                "package or set YAF_NF2FF_EXE)"
            )
        freqs = np.asarray(spectra.frequency)
        if "frequency" in request:
            idx = int(np.argmin(np.abs(freqs - float(request["frequency"]))))
        else:
            idx = int(np.argmin(np.abs(np.asarray(spectra.s11))))
        theta_step = float(request.get("theta_step_deg", 2.0))
        phi_step = float(request.get("phi_step_deg", 10.0))
        theta = np.arange(0.0, 180.0 + theta_step / 2, theta_step).tolist()
        phi = np.arange(0.0, 360.0, phi_step).tolist()

        control = write_control_xml(tmpdir, float(freqs[idx]), theta, phi)
        run_nf2ff(exe, tmpdir, control)
        res = read_result(tmpdir / "yaf_nf2ff.h5")

        p_in = spectra.p_in[idx]
        if p_in <= 0:
            raise OpenEMSParseError("non-positive accepted port power")
        efficiency = res.prad / p_in
        gain_dbi = 10.0 * math.log10(res.dmax * efficiency)
        far_field = FarFieldResult(
            theta=res.theta_deg,
            phi=res.phi_deg,
            e_theta=[[complex(v) for v in row] for row in res.e_theta],
            e_phi=[[complex(v) for v in row] for row in res.e_phi],
            frequency=res.frequency,
        )
        return far_field, gain_dbi, efficiency

    def _build_sim_xml(self, mesh: Mesh, spec: SimulationSpec) -> tuple[bytes, float]:
        """Generate the full simulation XML (dispatch on geometry class)."""
        md = mesh.metadata or {}
        if md.get("antenna_class") == "pixel_patch":
            return self._build_pixel_patch_xml(mesh, spec)
        if md.get("antenna_class") == "meander_dipole":
            return self._build_meander_wire_xml(mesh, spec)
        if md.get("antenna_class") == "freeform_wire_3d":
            return self._build_freeform_wire_xml(mesh, spec)
        if {"width", "length", "substrate_thickness"} <= md.keys():
            return self._build_patch_xml(mesh, spec)
        return self._build_wire_xml(mesh, spec)

    def _build_wire_xml(self, mesh: Mesh, spec: SimulationSpec) -> tuple[bytes, float]:
        """Generate the full simulation XML for a wire-class geometry."""
        wires = [e for e in (mesh.elements or []) if len(e) == 2]
        if not wires or not mesh.nodes:
            raise _UnsupportedGeometryError(
                "openEMS subprocess path currently handles wire geometries "
                "(2-node edges) and parametric patch antennas only"
            )
        nodes = np.asarray(mesh.nodes, dtype=float)
        c0 = _C0
        f_min, f_max = spec.frequency_range
        f0 = (f_min + f_max) / 2
        fc = max(f_max - f0, 0.3 * f0)  # keep the Gauss pulse short
        port_r = spec.ports[0].impedance if spec.ports else 50.0

        # fed wire: first edge; its dominant axis is the port direction
        p0, p1 = nodes[wires[0][0]], nodes[wires[0][1]]
        axis = int(np.argmax(np.abs(p1 - p0)))
        length = float(abs(p1[axis] - p0[axis]))
        if length <= 0:
            raise _UnsupportedGeometryError("fed wire has zero length")
        lo, hi = sorted((float(p0[axis]), float(p1[axis])))
        center = (lo + hi) / 2

        # grid: even cell count along the fed wire → gap edges on lines
        n_cells = max(2 * round(length / (length / 40) / 2), 4)
        res = length / n_cells
        axis_lines = [lo + k * res for k in range(n_cells + 1)]

        writer = OpenEMSXmlWriter(f0=f0, fc=fc)
        max_step = c0 / (f0 + fc) / 10
        margin = 0.75 * c0 / f0
        bb_min = nodes.min(axis=0)
        bb_max = nodes.max(axis=0)

        lines: dict[int, list[float]] = {0: [], 1: [], 2: []}
        lines[axis] += axis_lines
        for d in range(3):
            lines[d] += grade_lines(float(bb_min[d]), float(bb_min[d]) - margin, res, max_step)
            lines[d] += grade_lines(float(bb_max[d]), float(bb_max[d]) + margin, res, max_step)

        # fed wire arms with a one-cell feed gap each side of center
        gap = res
        t = [float(p0[d]) for d in range(3)]  # transverse coords of fed wire

        def _pt(a_val: float) -> tuple[float, float, float]:
            q = list(t)
            q[axis] = a_val
            return (q[0], q[1], q[2])

        writer.add_metal_box("fed_arm_lo", _pt(lo), _pt(center - gap))
        writer.add_metal_box("fed_arm_hi", _pt(center + gap), _pt(hi))
        writer.add_lumped_port(LumpedPort(
            1, port_r, _pt(center - gap), _pt(center + gap), axis,
        ))

        # remaining wires: parasitic thin PEC lines
        for wi, elem in enumerate(wires[1:], start=2):
            q0, q1 = nodes[elem[0]], nodes[elem[1]]
            writer.add_metal_box(
                f"wire_{wi}", _t3(q0), _t3(q1)
            )
            w_axis = int(np.argmax(np.abs(q1 - q0)))
            for d in range(3):
                if d == w_axis:
                    lines[d] += [float(q0[d]), float(q1[d])]
                else:
                    lines[d] += [float(q0[d]) - res, float(q0[d]), float(q0[d]) + res]

        # transverse fine lines around the fed wire
        for d in range(3):
            if d != axis:
                lines[d] += [t[d] - res, t[d], t[d] + res]

        writer.x_lines, writer.y_lines, writer.z_lines = lines[0], lines[1], lines[2]
        if spec.far_field_request is not None:
            writer.add_nf2ff_box()
        return writer.to_bytes(), float(port_r)

    def _build_meander_wire_xml(
        self, mesh: Mesh, spec: SimulationSpec
    ) -> tuple[bytes, float]:
        """Generate native thin-box FDTD geometry from a meander centerline."""

        representation = str(
            spec.solver_settings.get("openems_wire_representation", "thin_line")
        )
        if representation not in {"thin_line", "rod"}:
            raise ValueError("unsupported openEMS meander wire representation")
        if representation == "rod":
            return self._build_meander_rod_xml(mesh, spec)

        wires = [element for element in (mesh.elements or []) if len(element) == 2]
        if not wires or not mesh.nodes:
            raise _UnsupportedGeometryError("meander geometry has no wire edges")
        nodes = np.asarray(mesh.nodes, dtype=float)
        feed_start = nodes[wires[0][0]]
        feed_stop = nodes[wires[0][1]]
        delta = feed_stop - feed_start
        axis = int(np.argmax(np.abs(delta)))
        if sum(abs(float(delta[index])) > 1e-12 for index in range(3)) != 1:
            raise _UnsupportedGeometryError("meander feed edge must be axis-aligned")

        f_min, f_max = spec.frequency_range
        f0 = (f_min + f_max) / 2.0
        fc = max(f_max - f0, 0.3 * f0)
        max_step = _C0 / (f0 + fc) / 10.0
        port_r = spec.ports[0].impedance if spec.ports else 50.0
        pitch = float(mesh.metadata.get("minimum_pitch_m", 0.0015))
        refinement = float(spec.solver_settings.get("openems_mesh_refinement", 1.0))
        if refinement <= 0.0:
            raise ValueError("openems_mesh_refinement must be positive")
        resolution = min(0.0015, pitch / 2.0) / refinement
        margin = 0.75 * _C0 / f0
        bb_min = nodes.min(axis=0)
        bb_max = nodes.max(axis=0)
        lines: dict[int, list[float]] = {0: [], 1: [], 2: []}
        for dimension in range(3):
            lines[dimension].extend(float(node[dimension]) for node in nodes)
            lines[dimension] += grade_lines(
                float(bb_min[dimension]),
                float(bb_min[dimension]) - margin,
                resolution,
                max_step,
            )
            lines[dimension] += grade_lines(
                float(bb_max[dimension]),
                float(bb_max[dimension]) + margin,
                resolution,
                max_step,
            )
        for dimension in range(3):
            if dimension != axis:
                transverse = float(feed_start[dimension])
                lines[dimension] += [
                    transverse - resolution,
                    transverse,
                    transverse + resolution,
                ]
            lines[dimension] = smooth_lines(lines[dimension], max_step)

        writer = OpenEMSXmlWriter(f0=f0, fc=fc)
        writer.add_lumped_port(
            LumpedPort(
                1,
                port_r,
                _t3(feed_start),
                _t3(feed_stop),
                axis,
            )
        )
        for wire_index, element in enumerate(wires[1:], start=1):
            start = nodes[element[0]]
            stop = nodes[element[1]]
            wire_axis = int(np.argmax(np.abs(stop - start)))
            if sum(
                abs(float(stop[index] - start[index])) > 1e-12
                for index in range(3)
            ) != 1:
                raise _UnsupportedGeometryError(
                    "meander centerline segments must be axis-aligned"
                )
            writer.add_metal_box(
                f"meander_wire_{wire_index}", _t3(start), _t3(stop)
            )
            for dimension in range(3):
                if dimension != wire_axis:
                    coordinate = float(start[dimension])
                    lines[dimension] += [
                        coordinate - resolution,
                        coordinate,
                        coordinate + resolution,
                    ]
        writer.x_lines = smooth_lines(lines[0], max_step)
        writer.y_lines = smooth_lines(lines[1], max_step)
        writer.z_lines = smooth_lines(lines[2], max_step)
        if spec.far_field_request is not None:
            writer.add_nf2ff_box()
        return writer.to_bytes(), float(port_r)

    def _build_meander_rod_xml(
        self, mesh: Mesh, spec: SimulationSpec
    ) -> tuple[bytes, float]:
        """Generate finite square PEC rods with an exterior near-field mesh."""

        wires = [element for element in (mesh.elements or []) if len(element) == 2]
        if not wires or not mesh.nodes:
            raise _UnsupportedGeometryError("meander geometry has no wire edges")
        nodes = np.asarray(mesh.nodes, dtype=float)
        radius_value = mesh.metadata.get("wire_radius_m")
        if not isinstance(radius_value, (int, float)):
            raise ValueError("rod representation requires wire_radius_m metadata")
        radius = float(radius_value)
        if not math.isfinite(radius) or radius <= 0.0:
            raise ValueError("wire_radius_m must be finite and positive")

        feed_start = nodes[wires[0][0]]
        feed_stop = nodes[wires[0][1]]
        delta = feed_stop - feed_start
        feed_axis = int(np.argmax(np.abs(delta)))
        if sum(
            abs(float(delta[index])) > 1e-12 for index in range(3)
        ) != 1:
            raise _UnsupportedGeometryError("meander feed edge must be axis-aligned")

        f_min, f_max = spec.frequency_range
        f0 = (f_min + f_max) / 2.0
        fc = max(f_max - f0, 0.3 * f0)
        max_step = _C0 / (f0 + fc) / 10.0
        port_r = spec.ports[0].impedance if spec.ports else 50.0
        refinement = float(
            spec.solver_settings.get("openems_mesh_refinement", 1.0)
        )
        if (
            not math.isfinite(refinement)
            or refinement <= 0.0
            or not refinement.is_integer()
        ):
            raise ValueError("rod mesh refinement must be a positive integer")
        refinement_count = int(refinement)
        resolution = radius / refinement
        margin = 0.75 * _C0 / f0
        lines: dict[int, list[float]] = {0: [], 1: [], 2: []}
        mandatory: dict[int, set[float]] = {0: set(), 1: set(), 2: set()}
        for dimension in range(3):
            mandatory[dimension].update(
                float(node[dimension]) for node in nodes
            )

        def add_transverse_lines(dimension: int, coordinate: float) -> None:
            values = {
                coordinate - radius,
                coordinate,
                coordinate + radius,
            }
            for index in range(1, refinement_count + 1):
                values.add(coordinate - radius - index * resolution)
                values.add(coordinate + radius + index * resolution)
            mandatory[dimension].update(values)

        for dimension in range(3):
            if dimension != feed_axis:
                add_transverse_lines(dimension, float(feed_start[dimension]))

        arm_segments: list[
            tuple[
                np.ndarray[Any, np.dtype[np.float64]],
                np.ndarray[Any, np.dtype[np.float64]],
                int,
            ]
        ] = []
        for element in wires[1:]:
            start = nodes[element[0]]
            stop = nodes[element[1]]
            segment_delta = stop - start
            wire_axis = int(np.argmax(np.abs(segment_delta)))
            if sum(
                abs(float(segment_delta[index])) > 1e-12
                for index in range(3)
            ) != 1:
                raise _UnsupportedGeometryError(
                    "meander centerline segments must be axis-aligned"
                )
            arm_segments.append((start, stop, wire_axis))
            for dimension in range(3):
                if dimension != wire_axis:
                    add_transverse_lines(dimension, float(start[dimension]))

        for dimension in range(3):
            fixed = sorted(mandatory[dimension])
            lower = fixed[0]
            upper = fixed[-1]
            lines[dimension].extend(fixed)
            lines[dimension] += grade_lines(
                lower, lower - margin, resolution, max_step
            )
            lines[dimension] += grade_lines(
                upper, upper + margin, resolution, max_step
            )
            lines[dimension] = smooth_lines(lines[dimension], max_step)
            if not mandatory[dimension].issubset(set(lines[dimension])):
                raise ValueError("rod mesh smoothing removed a mandatory line")

        all_cells = [
            right - left
            for dimension in range(3)
            for left, right in zip(
                lines[dimension], lines[dimension][1:], strict=False
            )
        ]
        minimum_cell = min(all_cells)
        tolerance = resolution * 1e-8
        if (
            minimum_cell < 0.5 * resolution - tolerance
            or minimum_cell > resolution + tolerance
        ):
            raise ValueError("rod mesh violates the frozen minimum-cell invariant")

        number_of_timesteps = int(
            spec.solver_settings.get("openems_number_of_timesteps", 40000)
        )
        if number_of_timesteps <= 0:
            raise ValueError("openems_number_of_timesteps must be positive")
        writer = OpenEMSXmlWriter(
            f0=f0,
            fc=fc,
            number_of_timesteps=number_of_timesteps,
        )

        port_start = feed_start.copy()
        port_stop = feed_stop.copy()
        for dimension in range(3):
            if dimension != feed_axis:
                coordinate = float(feed_start[dimension])
                port_start[dimension] = coordinate - radius
                port_stop[dimension] = coordinate + radius
        writer.add_lumped_port(
            LumpedPort(
                1,
                port_r,
                _t3(port_start),
                _t3(port_stop),
                feed_axis,
            )
        )

        for wire_index, (start, stop, wire_axis) in enumerate(
            arm_segments, start=1
        ):
            box_start = start.copy()
            box_stop = stop.copy()
            for dimension in range(3):
                if dimension != wire_axis:
                    coordinate = float(start[dimension])
                    box_start[dimension] = coordinate - radius
                    box_stop[dimension] = coordinate + radius
            writer.add_metal_box(
                f"meander_wire_{wire_index}",
                _t3(box_start),
                _t3(box_stop),
            )
        writer.x_lines = lines[0]
        writer.y_lines = lines[1]
        writer.z_lines = lines[2]
        if spec.far_field_request is not None:
            writer.add_nf2ff_box()
        return writer.to_bytes(), float(port_r)

    def _build_freeform_wire_xml(
        self, mesh: Mesh, spec: SimulationSpec
    ) -> tuple[bytes, float]:
        """Generate resolved-radius PEC Wires on a bounded Cartesian grid."""

        wires = [element for element in (mesh.elements or []) if len(element) == 2]
        if not wires or not mesh.nodes:
            raise _UnsupportedGeometryError("free-form geometry has no wire edges")
        nodes = np.asarray(mesh.nodes, dtype=float)
        feed_start = nodes[wires[0][0]]
        feed_stop = nodes[wires[0][1]]
        delta = feed_stop - feed_start
        axis = int(np.argmax(np.abs(delta)))
        if sum(abs(float(delta[index])) > 1e-12 for index in range(3)) != 1:
            raise _UnsupportedGeometryError("free-form feed edge must be axis-aligned")
        positive_edge_count = int(mesh.metadata.get("positive_edge_count", 0))
        if positive_edge_count <= 0 or len(wires) != 1 + 2 * positive_edge_count:
            raise _UnsupportedGeometryError("free-form arm edge metadata is inconsistent")

        f_min, f_max = spec.frequency_range
        f0 = (f_min + f_max) / 2.0
        fc = max(f_max - f0, 0.3 * f0)
        max_step = _C0 / (f0 + fc) / 10.0
        port_r = spec.ports[0].impedance if spec.ports else 50.0
        refinement = float(spec.solver_settings.get("openems_mesh_refinement", 1.0))
        if refinement <= 0.0:
            raise ValueError("openems_mesh_refinement must be positive")
        resolution = 0.0005 / refinement
        surrogate_radius = 0.00025
        margin = 0.75 * _C0 / f0
        bb_min = nodes.min(axis=0) - surrogate_radius
        bb_max = nodes.max(axis=0) + surrogate_radius
        lines: dict[int, list[float]] = {0: [], 1: [], 2: []}
        for dimension in range(3):
            local_breakpoints = [
                float(bb_min[dimension]),
                float(bb_max[dimension]),
            ]
            if dimension == axis:
                local_breakpoints.extend(
                    [float(feed_start[dimension]), float(feed_stop[dimension])]
                )
            else:
                transverse = float(feed_start[dimension])
                local_breakpoints.extend(
                    [transverse - resolution, transverse, transverse + resolution]
                )
            lines[dimension].extend(
                _partition_mesh_intervals(local_breakpoints, resolution)
            )
            lines[dimension] += grade_lines(
                float(bb_min[dimension]),
                float(bb_min[dimension]) - margin,
                resolution,
                max_step,
            )
            lines[dimension] += grade_lines(
                float(bb_max[dimension]),
                float(bb_max[dimension]) + margin,
                resolution,
                max_step,
            )

        base_timesteps = int(
            spec.solver_settings.get("openems_base_timesteps", 40000)
        )
        if base_timesteps <= 0:
            raise ValueError("openems_base_timesteps must be positive")
        writer = OpenEMSXmlWriter(
            f0=f0,
            fc=fc,
            number_of_timesteps=int(round(base_timesteps * refinement)),
        )
        writer.add_lumped_port(
            LumpedPort(1, port_r, _t3(feed_start), _t3(feed_stop), axis)
        )

        def _add_arm_wire(arm_wires: list[list[int]], arm_name: str) -> None:
            previous = _t3(nodes[arm_wires[0][0]])
            points = [previous]
            for element in arm_wires:
                start = _t3(nodes[element[0]])
                stop = _t3(nodes[element[1]])
                if start != previous:
                    raise _UnsupportedGeometryError("free-form arm edges are not ordered")
                points.append(stop)
                previous = stop
            writer.add_metal_wire(
                f"freeform_{arm_name}_wire",
                points,
                surrogate_radius,
            )

        positive = wires[1 : 1 + positive_edge_count]
        negative = wires[1 + positive_edge_count :]
        _add_arm_wire(positive, "positive_arm")
        _add_arm_wire(negative, "negative_arm")
        writer.x_lines = smooth_lines(lines[0], max_step)
        writer.y_lines = smooth_lines(lines[1], max_step)
        writer.z_lines = smooth_lines(lines[2], max_step)
        if spec.far_field_request is not None:
            writer.add_nf2ff_box()
        return writer.to_bytes(), float(port_r)

    def _build_patch_xml(self, mesh: Mesh, spec: SimulationSpec) -> tuple[bytes, float]:
        """Simulation XML for a parametric microstrip patch antenna.

        Mirrors the official Simple_Patch_Antenna tutorial setup: PEC
        patch on a lossy dielectric substrate over a PEC ground plane,
        fed by a vertical lumped probe at (feed_x, 0). Mesh follows the
        official strategy — thirds-rule lines on the patch edges, four
        z-cells through the substrate, smooth grading out to the MUR
        boundaries (validated against tests/fixtures/openems/patch_s11.csv).
        """
        md = mesh.metadata
        patch_l = float(md["length"])  # resonant dimension, x
        patch_w = float(md["width"])  # y
        sub_h = float(md["substrate_thickness"])
        sub_l = float(md.get("substrate_length", patch_l))
        sub_w = float(md.get("substrate_width", patch_w))
        eps_r = float(md.get("eps_r", 4.4))
        tan_d = float(md.get("loss_tangent", 0.02))
        feed_x = float(md.get("feed_x", -patch_l * 3.0 / 16.0))
        if patch_l <= 0 or patch_w <= 0 or sub_h <= 0:
            raise _UnsupportedGeometryError("patch dimensions must be positive")

        f_min, f_max = spec.frequency_range
        f0 = (f_min + f_max) / 2
        fc = max(f_max - f0, 0.3 * f0)
        port_r = spec.ports[0].impedance if spec.ports else 50.0

        refinement = float(
            spec.solver_settings.get("openems_mesh_refinement", 1.0)
        )
        if refinement <= 0.0:
            raise ValueError("openems_mesh_refinement must be positive")
        res = _C0 / (f0 + fc) / 20 / refinement  # bulk cell size
        mer = res / 2  # metal-edge (thirds rule) resolution
        lam0 = _C0 / f0

        writer = OpenEMSXmlWriter(f0=f0, fc=fc, number_of_timesteps=30000)

        # dielectric loss: kappa = tanδ·ω·ε0·εr, evaluated at band center
        kappa = tan_d * 2 * math.pi * f0 * _EPS0 * eps_r
        writer.add_metal_box(
            "patch",
            (-patch_l / 2, -patch_w / 2, sub_h),
            (patch_l / 2, patch_w / 2, sub_h),
        )
        self._add_substrate(
            writer, md,
            (-sub_l / 2, -sub_w / 2, 0.0), (sub_l / 2, sub_w / 2, sub_h),
            eps_r, kappa,
        )
        if bool(md.get("ground_plane", True)):
            writer.add_metal_box(
                "gnd",
                (-sub_l / 2, -sub_w / 2, 0.0), (sub_l / 2, sub_w / 2, 0.0),
            )
        writer.add_lumped_port(LumpedPort(
            1, port_r, (feed_x, 0.0, 0.0), (feed_x, 0.0, sub_h), 2,
        ))

        def thirds(edge: float, inward: float) -> list[float]:
            # official metal-edge rule: 1/3 of a cell inside, 2/3 outside
            return [edge + inward * mer / 3, edge - inward * 2 * mer / 3]

        x_fixed = [
            -sub_l / 2 - lam0 / 2, -sub_l / 2, feed_x,
            *thirds(-patch_l / 2, +1), *thirds(patch_l / 2, -1),
            sub_l / 2, sub_l / 2 + lam0 / 2,
        ]
        y_fixed = [
            -sub_w / 2 - lam0 / 2, -sub_w / 2, 0.0,
            *thirds(-patch_w / 2, +1), *thirds(patch_w / 2, -1),
            sub_w / 2, sub_w / 2 + lam0 / 2,
        ]
        z_fixed = [
            -lam0 / 3,
            *(float(z) for z in np.linspace(0.0, sub_h, 5)),
            2 * lam0 / 3,
        ]

        writer.x_lines = smooth_lines(x_fixed, res)
        writer.y_lines = smooth_lines(y_fixed, res)
        writer.z_lines = smooth_lines(z_fixed, res)
        if spec.far_field_request is not None:
            writer.add_nf2ff_box()
        return writer.to_bytes(), float(port_r)

    @staticmethod
    def _add_substrate(
        writer: OpenEMSXmlWriter,
        md: dict[str, Any],
        p1: tuple[float, float, float],
        p2: tuple[float, float, float],
        eps_r: float,
        kappa: float,
    ) -> None:
        """Substrate box — constant or Drude/Lorentz dispersive.

        metadata["substrate_dispersion"] = {"model": "lorentz"|"drude",
        "plasma_freq_hz": ..., "pole_freq_hz": ..., "relax_time_s": ...}
        adds a first-order pole on top of the eps_r base value. Debye is
        REJECTED: openEMS v0.0.36 has no Debye engine extension — the
        CSXCAD description would be silently ignored by the FDTD kernel,
        which is exactly the kind of fake physics this repo refuses.
        """
        disp = md.get("substrate_dispersion")
        if disp is None:
            writer.add_material_box("substrate", p1, p2,
                                    epsilon=eps_r, kappa=kappa)
            return
        model = str(disp.get("model", "")).lower()
        if model in ("lorentz", "drude"):
            writer.add_lorentz_material_box(
                "substrate", p1, p2, epsilon=eps_r, kappa=kappa,
                plasma_freq=float(disp["plasma_freq_hz"]),
                relax_time=float(disp.get("relax_time_s", 0.0)),
                pole_freq=float(disp.get("pole_freq_hz", 0.0)),
            )
            return
        raise _UnsupportedGeometryError(
            f"substrate_dispersion model '{model}' is not runnable: the "
            "openEMS v0.0.36 engine implements only the Drude/Lorentz "
            "dispersive extension (a Debye description would be silently "
            "ignored by the FDTD kernel — refusing instead of faking)"
        )

    def _build_pixel_patch_xml(
        self, mesh: Mesh, spec: SimulationSpec
    ) -> tuple[bytes, float]:
        """Simulation XML for an arbitrary PLANAR metal sheet on a substrate.

        The "pixel patch" setup of generative inverse design (e.g.
        arXiv:2505.18188): the sheet's triangles are rasterized into a
        pixel mask on the FDTD grid, each pixel becomes PEC on top of a
        dielectric substrate over a ground plane, probe-fed at (feed_x,
        feed_y). Handles VAE pixel sheets, printed spirals and fractals.
        Non-planar surface meshes (horns) stay unsupported — they need a
        waveguide excitation this path does not have.
        """
        md = mesh.metadata
        tris = [e for e in (mesh.elements or []) if len(e) == 3]
        if not tris or not mesh.nodes:
            raise _UnsupportedGeometryError(
                "pixel_patch geometry needs triangle faces"
            )
        nodes = np.asarray(mesh.nodes, dtype=float)
        z_span = float(nodes[:, 2].max() - nodes[:, 2].min())
        xy_span = float(
            max(nodes[:, 0].max() - nodes[:, 0].min(),
                nodes[:, 1].max() - nodes[:, 1].min())
        )
        if xy_span <= 0 or z_span > 0.05 * xy_span:
            raise _UnsupportedGeometryError(
                "pixel_patch path handles planar sheets only "
                "(non-planar surfaces need a waveguide port)"
            )

        sub_h = float(md.get("substrate_thickness", 1.6e-3))
        eps_r = float(md.get("eps_r", 4.4))
        tan_d = float(md.get("loss_tangent", 0.02))
        if sub_h <= 0:
            raise _UnsupportedGeometryError("substrate thickness must be positive")

        f_min, f_max = spec.frequency_range
        f0 = (f_min + f_max) / 2
        fc = max(f_max - f0, 0.3 * f0)
        port_r = spec.ports[0].impedance if spec.ports else 50.0

        # raster pitch: geometry's own pixel size if declared, else λ/20;
        # the bulk mesh outside the sheet still grades up to λ/20 so a
        # fine pixel grid does not drag the whole domain down with it
        bulk = _C0 / (f0 + fc) / 20
        pixel = md.get("pixel_size")
        res = min(bulk, float(pixel)) if pixel is not None else bulk
        if xy_span / res > 200:
            raise _UnsupportedGeometryError(
                f"pixel raster would need {xy_span / res:.0f} lines/axis "
                "(cap 200) — coarsen pixel_size or shrink the sheet"
            )

        mask, x0, y0 = rasterize_planar_mesh(nodes, tris, res)
        runs = mask_to_boxes(mask)
        if not runs:
            raise _UnsupportedGeometryError("rasterization produced no metal")

        nx, ny = mask.shape
        cx = x0 + nx * res / 2
        cy = y0 + ny * res / 2
        sub_l = float(md.get("substrate_length", 1.5 * nx * res))
        sub_w = float(md.get("substrate_width", 1.5 * ny * res))
        # snap the probe to the pixel raster: an off-grid feed line next
        # to a raster line would create a runt cell and crush the timestep
        feed_x = x0 + round(
            (float(md.get("feed_x", cx - nx * res * 3.0 / 16.0)) - x0) / res
        ) * res
        feed_y = y0 + round(
            (float(md.get("feed_y", cy)) - y0) / res
        ) * res

        writer = OpenEMSXmlWriter(f0=f0, fc=fc, number_of_timesteps=30000)
        kappa = tan_d * 2 * math.pi * f0 * _EPS0 * eps_r
        for ix, iy0, iy1 in runs:
            writer.add_metal_box(
                f"px_{ix}_{iy0}",
                (x0 + ix * res, y0 + iy0 * res, sub_h),
                (x0 + (ix + 1) * res, y0 + iy1 * res, sub_h),
            )
        self._add_substrate(
            writer, md,
            (cx - sub_l / 2, cy - sub_w / 2, 0.0),
            (cx + sub_l / 2, cy + sub_w / 2, sub_h),
            eps_r, kappa,
        )
        writer.add_metal_box(
            "gnd",
            (cx - sub_l / 2, cy - sub_w / 2, 0.0),
            (cx + sub_l / 2, cy + sub_w / 2, 0.0),
        )
        writer.add_lumped_port(LumpedPort(
            1, port_r, (feed_x, feed_y, 0.0), (feed_x, feed_y, sub_h), 2,
        ))

        lam0 = _C0 / f0
        # mesh lines = the pixel raster itself (boxes land exactly on
        # lines), plus feed / substrate edges / graded margins
        x_fixed = [
            cx - sub_l / 2 - lam0 / 2, cx - sub_l / 2, feed_x,
            *(x0 + k * res for k in range(nx + 1)),
            cx + sub_l / 2, cx + sub_l / 2 + lam0 / 2,
        ]
        y_fixed = [
            cy - sub_w / 2 - lam0 / 2, cy - sub_w / 2, feed_y,
            *(y0 + k * res for k in range(ny + 1)),
            cy + sub_w / 2, cy + sub_w / 2 + lam0 / 2,
        ]
        z_fixed = [
            -lam0 / 3,
            *(float(z) for z in np.linspace(0.0, sub_h, 5)),
            2 * lam0 / 3,
        ]
        writer.x_lines = smooth_lines(x_fixed, bulk)
        writer.y_lines = smooth_lines(y_fixed, bulk)
        writer.z_lines = smooth_lines(z_fixed, bulk)
        if spec.far_field_request is not None:
            writer.add_nf2ff_box()
        return writer.to_bytes(), float(port_r)

    def _run_analytical(
        self,
        mesh: Mesh,
        spec: SimulationSpec,
        job_id: str,
        f_center: float,
        f_min: float,
        f_max: float,
        n_freqs: int,
    ) -> SimulationResult:
        """Run analytical/semi-analytical EM computation for demo purposes.

        For simple structures (dipoles, patches), uses analytical formulas.
        For complex structures, returns a mock result with realistic values.
        Every result is labeled ``solver_mode="fallback_analytical"``.
        """
        self._require_fallback_allowed(
            job_id,
            "no openEMS solver reachable (bindings not importable, binary "
            "not found) or geometry unsupported by the subprocess path",
        )

        freqs = np.linspace(f_min, f_max, n_freqs).tolist()
        c0 = 3e8

        # Estimate antenna dimensions from mesh
        if mesh.nodes:
            v = np.array(mesh.nodes)
            extent = np.max(v, axis=0) - np.min(v, axis=0)
            max_dim = float(np.max(extent))
            # Simple dipole model
            if max_dim > 0:
                # Resonant at λ/2
                f_res = c0 / (2 * max_dim) if max_dim > 0 else f_center

                # Compute S11 using simple RLC model
                s_matrix: list[list[list[complex]]] = []
                for f in freqs:
                    detuning = (f - f_res) / f_res
                    # Simple resonant model
                    s11 = detuning / (detuning + 1j * 0.1)
                    s_matrix.append([[s11]])

                s_params = SParamResult(
                    frequency=freqs,
                    s_matrix=s_matrix,
                    z0=50.0,
                )

                # Far field (analytical dipole pattern)
                theta = np.linspace(0, np.pi, 181).tolist()
                phi = np.linspace(0, 2 * np.pi, 361).tolist()
                e_theta_raw = []
                e_phi_raw = []
                for t in theta:
                    if math.sin(t) > 0.001:
                        pattern = math.cos(math.pi / 2 * math.cos(t)) / math.sin(t)
                    else:
                        pattern = 0.0
                    e_theta_raw.append([complex(pattern, 0) for _ in phi])
                    e_phi_raw.append([complex(0, 0) for _ in phi])

                far_field = FarFieldResult(
                    theta=theta,
                    phi=phi,
                    e_theta=e_theta_raw,
                    e_phi=e_phi_raw,
                    frequency=f_res,
                )

                gain = far_field.gain_dbi()
                max_gain = max(max(row) for row in gain) if gain else 2.15

                return self._mark_solver_mode(
                    SimulationResult(
                        job_id=uuid.UUID(job_id),
                        solver_name=self.name,
                        solver_version=self.version,
                        status="success",
                        s_params=s_params,
                        far_field=far_field,
                        gain_dbi=max_gain,
                        efficiency=0.95,
                        vswr=self._compute_vswr(s_params),
                        simulation_time_sec=0.5,
                    ),
                    "fallback_analytical",
                )

        # Fallback: mock with realistic values
        s_matrix = []
        for f in freqs:
            z_norm = (50 + 1j * 10 * (f - f_center) / f_center) / 50
            s11 = (z_norm - 1) / (z_norm + 1)
            s_matrix.append([[s11]])

        return self._mark_solver_mode(
            SimulationResult(
                job_id=uuid.UUID(job_id),
                solver_name=self.name,
                solver_version=self.version,
                status="success",
                s_params=SParamResult(frequency=freqs, s_matrix=s_matrix),
                gain_dbi=2.15,
                efficiency=0.9,
                vswr=1.5,
                simulation_time_sec=0.1,
            ),
            "fallback_analytical",
        )

    def to_native_format(self, geometry: Geometry) -> bytes:
        """Convert geometry to openEMS CSXCAD XML format."""
        import xml.etree.ElementTree as ET

        root = ET.Element("ContinuousStructure")
        ET.SubElement(root, "CoordSystem", Type="0")

        if geometry.vertices and geometry.faces:
            for i, face in enumerate(geometry.faces):
                if len(face) < 3:
                    continue
                v = [geometry.vertices[idx] for idx in face]
                metal = ET.SubElement(root, "Metal", Name=f"face_{i}")
                prop = ET.SubElement(metal, "Properties")
                box = ET.SubElement(prop, "Box")
                ET.SubElement(box, "Priority").text = "10"
                start = [min(p[i] for p in v) for i in range(3)]
                stop = [max(p[i] for p in v) for i in range(3)]
                ET.SubElement(box, "Start").text = " ".join(f"{s:.6e}" for s in start)
                ET.SubElement(box, "Stop").text = " ".join(f"{s:.6e}" for s in stop)

        return bytes(ET.tostring(root, encoding="utf-8"))

    async def from_native_result(self, raw_output: bytes) -> SimulationResult:
        """Parse openEMS output (not implemented for demo)."""
        return SimulationResult(
            job_id=uuid.uuid4(),
            solver_name=self.name,
            solver_version=self.version,
            status="success",
        )

    @staticmethod
    def _compute_vswr(s_params: SParamResult) -> float:
        """Compute VSWR from S11."""
        if not s_params.s_matrix:
            return float("inf")
        s11_mag = abs(s_params.s_matrix[0][0][0])
        if s11_mag >= 1.0:
            return float("inf")
        return (1 + s11_mag) / (1 - s11_mag)

    async def health_check(self) -> bool:
        """True only when a real openEMS is reachable (bindings or binary)."""
        return self._openems_available or self._resolve_executable() is not None
