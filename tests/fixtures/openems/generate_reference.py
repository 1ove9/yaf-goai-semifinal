# ruff: noqa: E402  — the DLL directory must be registered before imports
# ============================================================
# REFERENCE
#   仿造来源：openEMS 官方 python Tutorials/Simple_Patch_Antenna.py
#   用途：用官方 openEMS Python API 生成参考仿真 —— 产出
#     1. dipole_csx.xml       官方 Write2XML 的 CSX 几何+网格格式样例
#     2. port_ut1 / port_it1  端口电压/电流探针时域输出（解析器 fixture）
#     3. dipole_s11.csv       官方后处理算出的 S11(f) 参考曲线
#   天线与 tests/fixtures/nec2/dipole_sweep.nec 同款：0.5 m 线偶极子，
#   自由空间 —— 用于将来 FDTD(openEMS) vs MoM(NEC2) 交叉验证。
#   运行（需要装了官方 wheels 的 py311 环境）：
#     D:\miniconda3\envs\oems311\python.exe generate_reference.py
# ============================================================

import os
import shutil
import sys

os.add_dll_directory(r"C:\opt\openEMS")

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS

HERE = os.path.dirname(os.path.abspath(__file__))
SIM_PATH = os.path.join(HERE, "_sim_dipole")

F0 = 300e6  # Gauss pulse center
FC = 200e6  # 20 dB corner -> excites 100..500 MHz
ARM_TIP = 0.25       # dipole tip |z|  (total length 0.5 m)
GAP_HALF = 0.0125    # feed gap half-height (one cell each side)
RES_FINE = 0.0125    # fine mesh step along the wire [m]
BOX = 1.5            # simulation box half-size [m]

fdtd = openEMS(NrTS=40000, EndCriteria=1e-4)
fdtd.SetGaussExcite(F0, FC)
fdtd.SetBoundaryCond(["MUR"] * 6)

csx = ContinuousStructure()
fdtd.SetCSX(csx)
mesh = csx.GetGrid()
mesh.SetDeltaUnit(1.0)  # coordinates in meters

# z: fine lines over the dipole (grid-aligned arms), coarse to the box edge
mesh.AddLine("z", np.arange(-ARM_TIP, ARM_TIP + RES_FINE / 2, RES_FINE))
mesh.AddLine("z", [-BOX, BOX])
# x/y: fine around the wire, coarse outward
for d in "xy":
    mesh.AddLine(d, [-RES_FINE, 0, RES_FINE])
    mesh.AddLine(d, [-BOX, BOX])
for d in "xyz":
    mesh.SmoothMeshLines(d, 0.1, 1.4)  # max step lambda/10 @ 300 MHz

# dipole arms: thin PEC line-boxes along z
pec = csx.AddMetal("dipole")
pec.AddBox(start=[0, 0, GAP_HALF], stop=[0, 0, ARM_TIP], priority=10)
pec.AddBox(start=[0, 0, -ARM_TIP], stop=[0, 0, -GAP_HALF], priority=10)

port = fdtd.AddLumpedPort(
    1, 50.0, [0, 0, -GAP_HALF], [0, 0, GAP_HALF], "z", excite=1.0, priority=5
)

if os.path.exists(SIM_PATH):
    shutil.rmtree(SIM_PATH)
os.mkdir(SIM_PATH)

# official CSX serialization sample (geometry + grid format reference)
csx.Write2XML(os.path.join(HERE, "dipole_csx.xml"))

print("running FDTD ...", flush=True)
fdtd.Run(SIM_PATH, cleanup=False, verbose=1)

freq = np.linspace(100e6, 500e6, 81)
port.CalcPort(SIM_PATH, freq)
s11 = port.uf_ref / port.uf_inc
zin = port.uf_tot / port.if_tot

with open(os.path.join(HERE, "dipole_s11.csv"), "w") as f:
    f.write("# official openEMS python API reference: 0.5 m wire dipole, free space\n")
    f.write("frequency_hz,s11_re,s11_im,zin_re,zin_im\n")
    for i, fr in enumerate(freq):
        f.write(f"{fr:.6e},{s11[i].real:.6e},{s11[i].imag:.6e},"
                f"{zin[i].real:.6e},{zin[i].imag:.6e}\n")

s11_db = 20 * np.log10(np.abs(s11))
i_min = int(np.argmin(s11_db))
print(f"S11 min: {s11_db[i_min]:.2f} dB @ {freq[i_min]/1e6:.0f} MHz")
i_res = int(np.argmin(np.abs(zin.imag)))
print(f"resonance (X=0): {freq[i_res]/1e6:.0f} MHz, R = {zin[i_res].real:.1f} ohm")
print("sim dir files:", sorted(os.listdir(SIM_PATH)))
sys.exit(0)
