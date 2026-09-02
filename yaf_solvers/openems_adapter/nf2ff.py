# ============================================================
# REFERENCE
#   仿造来源：openEMS matlab 接口 CalcNF2FF.m + nf2ff/nf2ff.cpp (v0.0.36)
#             + python 接口 openEMS/nf2ff.py::nf2ff_results
#   关键设计点：
#     - nf2ff.exe 控制文件：根元素 <nf2ff>，属性 freq/Outfile/Radius/
#       Center（数值列表逗号分隔，SplitString2Float 默认 ","），
#       子元素 <theta>/<phi>（弧度文本）+ <Planes E_Field= H_Field=>
#     - dump 文件命名：openEMS 对多 box 的 DumpBox 产出
#       <name>_<box#>.h5（0..5 对应 xn/xp/yn/yp/zn/zp 六面）
#     - 结果 HDF5：/Mesh/{theta,phi,r}、/nf2ff attrs {Frequency,Dmax,
#       Prad}、/nf2ff/E_theta|E_phi/FD/f<n>_real|imag（存储轴序
#       [phi,theta]，读出后 swapaxes 成 [theta,phi]，与官方一致）
#   验证：同一批面 dump 上，本模块驱动 nf2ff.exe 的输出与官方
#         python API (_nf2ff Cython) 逐点一致（tests/fixtures/openems/
#         patch_nf2ff.h5 + patch_farfield.csv）
# ============================================================

"""
NF2FF post-processing — drives the openEMS ``nf2ff`` binary.

Writes the transformation control file, runs the binary on the recorded
near-field dumps, and parses the far-field HDF5 result.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from yaf_solvers.openems_adapter.port_parser import OpenEMSParseError


@dataclass
class Nf2ffResult:
    """Far field at one frequency on a theta/phi grid (radius 1 m)."""

    frequency: float
    theta_deg: list[float]
    phi_deg: list[float]
    e_theta: np.ndarray  # [theta, phi], complex V/m
    e_phi: np.ndarray  # [theta, phi], complex V/m
    dmax: float  # max directivity, linear
    prad: float  # radiated power [W], official DFT scale


def resolve_nf2ff_executable(openems_executable: str | None) -> str | None:
    """Locate the nf2ff binary: env var, next to openEMS, then PATH."""
    candidates: list[str] = []
    env = os.environ.get("YAF_NF2FF_EXE", "").strip()
    if env:
        candidates.append(env)
    if openems_executable:
        sibling = Path(openems_executable).parent
        candidates += [str(sibling / "nf2ff.exe"), str(sibling / "nf2ff")]
    candidates += ["nf2ff", "nf2ff.exe"]
    for c in candidates:
        resolved = shutil.which(c) or (c if Path(c).is_file() else None)
        if resolved:
            return resolved
    return None


def write_control_xml(
    sim_dir: Path,
    frequency: float,
    theta_deg: list[float],
    phi_deg: list[float],
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    name: str = "nf2ff",
    outfile: str = "yaf_nf2ff.h5",
) -> Path:
    """Write the nf2ff.exe control file next to the recorded dumps."""
    root = ET.Element(
        "nf2ff",
        Outfile=outfile,
        freq=f"{frequency:.9g}",
        Center=",".join(f"{v:.9g}" for v in center),
        Radius="1",
        Verbose="0",
    )
    theta = ET.SubElement(root, "theta")
    theta.text = ",".join(f"{np.deg2rad(v):.9g}" for v in theta_deg)
    phi = ET.SubElement(root, "phi")
    phi.text = ",".join(f"{np.deg2rad(v):.9g}" for v in phi_deg)

    n_planes = 0
    for n in range(6):
        e_file = sim_dir / f"{name}_E_{n}.h5"
        h_file = sim_dir / f"{name}_H_{n}.h5"
        if e_file.exists() and h_file.exists():
            ET.SubElement(root, "Planes",
                          E_Field=e_file.name, H_Field=h_file.name)
            n_planes += 1
    if n_planes == 0:
        raise OpenEMSParseError(
            f"no NF2FF dump planes ({name}_E_*.h5) found in {sim_dir}"
        )

    ET.indent(root)
    control = sim_dir / f"{name}.xml"
    control.write_bytes(
        ET.tostring(root, encoding="utf-8", xml_declaration=True)
    )
    return control


def run_nf2ff(executable: str, sim_dir: Path, control: Path) -> None:
    """Run the nf2ff binary on a control file (cwd = dump directory)."""
    proc = subprocess.run(
        [executable, control.name],
        cwd=sim_dir, capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        raise OpenEMSParseError(
            f"nf2ff exited with {proc.returncode}: {proc.stdout[-400:]}"
        )


def read_result(path: Path) -> Nf2ffResult:
    """Parse the nf2ff result HDF5 (first frequency)."""
    import h5py  # noqa: PLC0415  — heavy optional dep, import on use

    if not path.exists():
        raise OpenEMSParseError(f"nf2ff result missing: {path.name}")
    with h5py.File(path, "r") as f:
        theta = np.rad2deg(np.asarray(f["Mesh"]["theta"], dtype=float))
        phi = np.rad2deg(np.asarray(f["Mesh"]["phi"], dtype=float))
        data = f["nf2ff"]
        freq = float(np.atleast_1d(np.asarray(data.attrs["Frequency"]))[0])
        dmax = float(np.atleast_1d(np.asarray(data.attrs["Dmax"]))[0])
        prad = float(np.atleast_1d(np.asarray(data.attrs["Prad"]))[0])
        # stored [phi, theta] → transpose to [theta, phi] like the
        # official nf2ff_results reader
        e_theta = np.swapaxes(
            np.asarray(f["nf2ff"]["E_theta"]["FD"]["f0_real"])
            + 1j * np.asarray(f["nf2ff"]["E_theta"]["FD"]["f0_imag"]), 0, 1,
        )
        e_phi = np.swapaxes(
            np.asarray(f["nf2ff"]["E_phi"]["FD"]["f0_real"])
            + 1j * np.asarray(f["nf2ff"]["E_phi"]["FD"]["f0_imag"]), 0, 1,
        )
    return Nf2ffResult(
        frequency=freq,
        theta_deg=[float(v) for v in theta],
        phi_deg=[float(v) for v in phi],
        e_theta=e_theta,
        e_phi=e_phi,
        dmax=dmax,
        prad=prad,
    )
