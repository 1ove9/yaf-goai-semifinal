# ============================================================
# REFERENCE
#   仿造来源：openEMS python 接口 openEMS/ports.py::Port.CalcPort
#   对标输出：仿真目录下的 port_ut_<N> / port_it_<N> ASCII 时域探针
#   关键设计点：
#     - 探针文件：# 注释行以 % 开头，数据两列 [t/s, value]
#     - 单频 DFT：X(f) = 2·dt·Σ x(t_k)·exp(-j2πf t_k)（官方
#       DFT_time2freq 的单边谱约定；S11/Zin 是比值不受影响，
#       p_in 则必须用它才能与 nf2ff 的 Prad 同尺度）
#     - 入射/反射分解：u_inc = (u + Z_ref·i)/2，u_ref = u − u_inc
#       （电压探针 Weight=-1、电流探针 Weight=+1 的官方约定下成立，
#       已对照官方 python API 的 S11 输出逐点验证）
#     - 数据缺失/为空 → OpenEMSParseError，不给默认值
# ============================================================

"""
openEMS port-probe parser — turns port_ut/port_it time series into S11.

All quantities are computed from real solver output; the math mirrors
``openEMS.ports.Port.CalcPort`` and is locked against the official
Python API's S11 by fixture tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from yaf_solvers.base import YAFError


class OpenEMSParseError(YAFError):
    """Raised when openEMS output files are missing or unusable."""


@dataclass
class PortSpectra:
    """Frequency-domain port quantities derived from the time probes."""

    frequency: list[float]
    s11: list[complex]
    z_in: list[complex]
    p_in: list[float]  # accepted port power [W], official DFT scale


def read_probe(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read one openEMS time-domain probe file (% comments, 2 columns)."""
    if not path.exists():
        raise OpenEMSParseError(f"probe file missing: {path.name}")
    times: list[float] = []
    values: list[float] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("%"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        times.append(float(parts[0]))
        values.append(float(parts[1]))
    if len(times) < 2:
        raise OpenEMSParseError(f"probe file has no usable samples: {path.name}")
    return np.asarray(times), np.asarray(values)


def _dft(t: np.ndarray, x: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    dt = float(t[1] - t[0])
    # [n_freq, n_time] phase matrix; fine for the ~1e3-sample probe files
    phase = np.exp(-2j * np.pi * np.outer(freqs, t))
    # 2·dt: official single-sided pulse spectrum (utilities.DFT_time2freq);
    # cancels in the s11/z_in ratios but keeps p_in on the same power
    # scale as the Prad the nf2ff transform reports
    return np.asarray((phase @ x) * dt * 2.0)


def calc_port(
    sim_dir: Path,
    port_nr: int,
    frequencies: list[float],
    z_ref: float = 50.0,
) -> PortSpectra:
    """Compute S11 and input impedance for a lumped port.

    Mirrors openEMS ``Port.CalcPort``: DFT the voltage/current probes,
    split into incident/reflected waves against ``z_ref``.
    """
    t_u, u_t = read_probe(sim_dir / f"port_ut_{port_nr}")
    t_i, i_t = read_probe(sim_dir / f"port_it_{port_nr}")

    # an all-zero voltage probe means the excitation never coupled into
    # the grid (e.g. a port box off its mesh line) — that run is broken,
    # and must not masquerade as a perfectly matched antenna (S11=0)
    if not np.any(u_t):
        raise OpenEMSParseError(
            f"port_ut_{port_nr} is all zeros — excitation did not couple "
            "into the FDTD grid"
        )

    # the current probe is sampled half a timestep off the voltage probe;
    # interpolate onto the voltage time axis like the official API does
    if len(t_i) != len(t_u) or not np.allclose(t_i, t_u):
        i_t = np.interp(t_u, t_i, i_t)

    freqs = np.asarray(frequencies, dtype=float)
    uf = _dft(t_u, u_t, freqs)
    if_ = _dft(t_u, i_t, freqs)

    uf_inc = 0.5 * (uf + z_ref * if_)
    uf_ref = uf - uf_inc

    with np.errstate(divide="ignore", invalid="ignore"):
        s11 = np.where(np.abs(uf_inc) > 0, uf_ref / uf_inc, 0)
        z_in = np.where(np.abs(if_) > 0, uf / if_, np.inf)
    p_in = 0.5 * np.real(uf * np.conj(if_))

    return PortSpectra(
        frequency=[float(f) for f in freqs],
        s11=[complex(v) for v in s11],
        z_in=[complex(v) for v in z_in],
        p_in=[float(v) for v in p_in],
    )
