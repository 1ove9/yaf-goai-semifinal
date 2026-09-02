# ruff: noqa: E402  — the DLL directory must be registered before imports
# ============================================================
# REFERENCE
#   仿造来源：openEMS 官方 python Tutorials/Simple_Patch_Antenna.py
#   用途：官方 API 跑教科书贴片天线，产出参考基准 —— 用于验证
#   YAF 自研 XML 路径的贴片支持（几何/基板/探针馈电/网格策略）。
#   天线：32×40 mm 贴片，εr=3.38 基板 60×60×1.524 mm，
#         x=-6 mm 处 50 Ω 垂直探针馈电（与官方教程逐参数一致，
#         仅把单位从 mm 换成 m —— YAF 全库用米）。
#   产出：patch_port_ut_1 / patch_port_it_1（探针 fixture）、
#         patch_s11.csv（官方后处理 S11/Zin 参考曲线）
#   运行：D:\miniconda3\envs\oems311\python.exe generate_patch_reference.py
# ============================================================

import os
import shutil

os.add_dll_directory(r"C:\opt\openEMS")

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.physical_constants import C0, EPS0

HERE = os.path.dirname(os.path.abspath(__file__))
SIM_PATH = os.path.join(HERE, "_sim_patch")

# --- geometry (meters; tutorial values are mm) ---
patch_w = 32e-3   # resonant length, x
patch_l = 40e-3   # y
sub_w = 60e-3
sub_l = 60e-3
sub_h = 1.524e-3
eps_r = 3.38
kappa = 1e-3 * 2 * np.pi * 2.45e9 * EPS0 * eps_r
feed_x = -6e-3
feed_r = 50.0
box = np.array([200e-3, 200e-3, 150e-3])

f0, fc = 2e9, 1e9

fdtd = openEMS(NrTS=30000, EndCriteria=1e-4)
fdtd.SetGaussExcite(f0, fc)
fdtd.SetBoundaryCond(["MUR"] * 6)

csx = ContinuousStructure()
fdtd.SetCSX(csx)
mesh = csx.GetGrid()
mesh.SetDeltaUnit(1.0)
mesh_res = C0 / (f0 + fc) / 20

mesh.AddLine("x", [-box[0] / 2, box[0] / 2])
mesh.AddLine("y", [-box[1] / 2, box[1] / 2])
mesh.AddLine("z", [-box[2] / 3, box[2] * 2 / 3])

patch = csx.AddMetal("patch")
patch.AddBox(priority=10, start=[-patch_w / 2, -patch_l / 2, sub_h],
             stop=[patch_w / 2, patch_l / 2, sub_h])
fdtd.AddEdges2Grid(dirs="xy", properties=patch, metal_edge_res=mesh_res / 2)

substrate = csx.AddMaterial("substrate", epsilon=eps_r, kappa=kappa)
substrate.AddBox(priority=0, start=[-sub_w / 2, -sub_l / 2, 0],
                 stop=[sub_w / 2, sub_l / 2, sub_h])
mesh.AddLine("z", np.linspace(0, sub_h, 5))

gnd = csx.AddMetal("gnd")
gnd.AddBox(priority=10, start=[-sub_w / 2, -sub_l / 2, 0],
           stop=[sub_w / 2, sub_l / 2, 0])
fdtd.AddEdges2Grid(dirs="xy", properties=gnd)

port = fdtd.AddLumpedPort(1, feed_r, [feed_x, 0, 0], [feed_x, 0, sub_h],
                          "z", excite=1.0, priority=5, edges2grid="xy")

mesh.SmoothMeshLines("all", mesh_res, 1.4)

if os.path.exists(SIM_PATH):
    shutil.rmtree(SIM_PATH)
os.mkdir(SIM_PATH)

print("running FDTD ...", flush=True)
fdtd.Run(SIM_PATH, cleanup=False, verbose=1)

freq = np.linspace(1e9, 3e9, 101)
port.CalcPort(SIM_PATH, freq)
s11 = port.uf_ref / port.uf_inc
zin = port.uf_tot / port.if_tot

with open(os.path.join(HERE, "patch_s11.csv"), "w") as f:
    f.write("# official openEMS python API reference: tutorial patch antenna (meters)\n")
    f.write("frequency_hz,s11_re,s11_im,zin_re,zin_im\n")
    for i, fr in enumerate(freq):
        f.write(f"{fr:.6e},{s11[i].real:.6e},{s11[i].imag:.6e},"
                f"{zin[i].real:.6e},{zin[i].imag:.6e}\n")

for name in ("port_ut_1", "port_it_1"):
    shutil.copy(os.path.join(SIM_PATH, name),
                os.path.join(HERE, "patch_" + name))

s11_db = 20 * np.log10(np.abs(s11))
i_min = int(np.argmin(s11_db))
print(f"S11 min: {s11_db[i_min]:.2f} dB @ {freq[i_min]/1e9:.3f} GHz")
