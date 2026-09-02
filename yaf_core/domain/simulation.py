# ============================================================
# REFERENCE
#   仿造来源：Tidy3D @ https://github.com/flexcompute/tidy3d
#   对标文件：tidy3d/components/simulation.py
#   对标类/函数：td.Simulation, td.Job, td.Monitor, td.Source
#   关键设计点：
#     - Pydantic v2 驱动所有仿真对象（不可变、可序列化、自校验）
#     - 声明式 simulation 描述（size/grid_spec/structures/sources/monitors/run_time/boundary_spec）
#     - 分层：Geometry → Structure → Simulation → Job
#     - FieldMonitor/FluxMonitor/ModeMonitor 分离监控类型
#   YAF 的差异化改造：
#     - 多求解器通用：SimulationSpec 不绑定单一求解器
#     - Port 激励体系（lumped/waveguide/plane_wave）映射到多求解器
#     - SimulationResult 内嵌 SParamResult + FarFieldResult（非外部引用）
#     - 直接集成 skrf.Network 解析 Touchstone
# ============================================================

"""
Simulation domain model — jobs, results, metrics.

Defines the contract between the orchestrator and solver adapters.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class PortType(str, enum.Enum):
    """Excitation port type."""

    LUMPED = "lumped"
    WAVEGUIDE = "waveguide"
    PLANE_WAVE = "plane_wave"
    DIFFERENTIAL = "differential"
    NEAR_FIELD = "near_field"


class Port(BaseModel):
    """Simulation port / excitation definition."""

    id: str = "port1"
    type: PortType = PortType.LUMPED
    impedance: float = 50.0  # ohms
    location: tuple[float, float, float] = (0.0, 0.0, 0.0)
    direction: tuple[float, float, float] = (0.0, 0.0, 1.0)
    amplitude: float = 1.0
    phase_deg: float = 0.0


class SimulationSpec(BaseModel):
    """Solver-independent simulation specification.

    Translates a DesignSpec into concrete simulation parameters.
    """

    name: str = ""
    frequency_range: tuple[float, float]  # Hz
    frequency_points: int = 101
    ports: list[Port] = Field(default_factory=list)
    boundary_conditions: dict[str, str] = Field(default_factory=dict)
    max_delta_s: float = 0.1  # max S-parameter change for convergence
    max_iterations: int = 1000
    solver_settings: dict[str, Any] = Field(default_factory=dict)
    far_field_request: dict[str, Any] | None = None


class SimulationJob(BaseModel):
    """A single solver run — dispatched to a Celery worker."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    design_id: uuid.UUID
    design_version: int
    spec: SimulationSpec
    solver_name: str
    state: str = "pending"  # pending, running, completed, failed, cancelled
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    priority: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class SParamResult(BaseModel):
    """S-parameter result matrix for N-port network."""

    frequency: list[float]
    s_matrix: list[list[list[complex]]]  # [freq][i][j]
    z0: float = 50.0
    unit: str = "dB"

    @classmethod
    def from_touchstone(cls, path: str) -> SParamResult:
        """Parse a Touchstone (.sNp) file."""
        import skrf  # noqa: PLC0415

        net = skrf.Network(path)
        freq = net.frequency.f.tolist()
        s_mat = net.s.tolist()
        return cls(frequency=freq, s_matrix=s_mat, z0=net.z0[0].real)


class FarFieldResult(BaseModel):
    """Far-field radiation pattern result."""

    theta: list[float]  # degrees
    phi: list[float]  # degrees
    e_theta: list[list[complex]]  # [theta_idx][phi_idx]
    e_phi: list[list[complex]]
    frequency: float  # Hz

    def gain_dbi(self) -> list[list[float]]:
        """Directivity pattern in dBi (equals gain for a lossless antenna).

        D(θ,φ) = 4π·U(θ,φ) / P_rad, with P_rad integrated numerically
        over the stored grid. Self-normalizing, so the arbitrary scale of
        pattern E-fields (e.g. nec2c's r-compensated V/m) cancels out.
        A single-φ cut is integrated assuming azimuthal symmetry — exact
        for bodies of revolution (dipoles), approximate otherwise; a
        partial θ range overestimates directivity by the missing solid
        angle's power.
        """
        import numpy as np

        e_t = np.asarray(self.e_theta, dtype=complex)
        e_p = np.asarray(self.e_phi, dtype=complex)
        u = np.abs(e_t) ** 2 + np.abs(e_p) ** 2  # ∝ radiation intensity
        theta = np.radians(np.asarray(self.theta, dtype=float))
        phi = np.radians(np.asarray(self.phi, dtype=float))

        # numpy ≥2.0 renamed trapz → trapezoid
        trapezoid = (
            np.trapezoid if hasattr(np, "trapezoid")
            else np.trapz  # type: ignore[attr-defined, unused-ignore]
        )
        integrand = u * np.sin(theta)[:, None]
        if len(phi) > 1:
            per_theta = trapezoid(integrand, phi, axis=1)
        else:
            per_theta = integrand[:, 0] * 2.0 * np.pi
        if len(theta) > 1:
            p_rad = float(trapezoid(per_theta, theta))
        else:
            p_rad = float(per_theta[0]) * np.pi
        if p_rad <= 0.0:
            return [[-300.0] * len(self.phi) for _ in self.theta]

        with np.errstate(divide="ignore"):
            d_db = 10.0 * np.log10(np.maximum(4.0 * np.pi * u / p_rad, 1e-30))
        return [[float(v) for v in row] for row in d_db]


class SimulationResult(BaseModel):
    """Complete simulation result — what every solver adapter must return."""

    job_id: uuid.UUID
    solver_name: str
    solver_version: str
    status: str  # "success", "failed", "partial"

    # S-parameters
    s_params: SParamResult | None = None

    # Far field
    far_field: FarFieldResult | None = None

    # Near field (optional)
    near_field: dict[str, Any] | None = None

    # Derived metrics
    gain_dbi: float | None = None
    efficiency: float | None = None
    vswr: float | None = None
    bandwidth_hz: float | None = None

    # Raw data
    raw_data_uri: str | None = None  # MinIO URI
    mesh_stats: dict[str, Any] = Field(default_factory=dict)
    solver_metadata: dict[str, Any] = Field(default_factory=dict)

    # Timing
    simulation_time_sec: float = 0.0
    cpu_time_sec: float = 0.0
    memory_mb: float = 0.0
