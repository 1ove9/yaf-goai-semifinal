# ruff: noqa: E402  — the DLL directory must be registered before imports
# ============================================================
# REFERENCE
#   仿造来源：openEMS 官方 python Tutorials/Simple_Patch_Antenna.py
#   用途：官方 API 跑教科书贴片天线 + NF2FF 远场变换，产出参考基准 ——
#   用于验证 YAF 自研路径（nf2ff dump box XML + nf2ff.exe 控制文件 +
#   结果 HDF5 解析 + 增益/效率推导）。
#   天线：与 generate_patch_reference.py 逐参数一致（教程贴片，米制）。
#   产出：patch_farfield.csv（谐振点全球面 E_theta/E_phi + Dmax/Prad/
#         P_in/效率）、patch_nf2ff.h5（官方 nf2ff 结果文件，供解析器
#         fixture 测试）
#   运行：D:\miniconda3\envs\oems311\python.exe generate_patch_nf2ff_reference.py
# ============================================================

import os
import shutil

os.add_dll_directory(r"C:\opt\openEMS")

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.physical_constants import C0, EPS0

HERE = os.path.dirname(os.path.abspath(__file__))
SIM_PATH = os.path.join(HERE, "_sim_patch_nf2ff")

# --- geometry (meters; identical to generate_patch_reference.py) ---
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

nf2ff = fdtd.CreateNF2FFBox()

if os.path.exists(SIM_PATH):
    shutil.rmtree(SIM_PATH)
os.mkdir(SIM_PATH)

print("running FDTD ...", flush=True)
fdtd.Run(SIM_PATH, cleanup=False, verbose=1)

freq = np.linspace(1e9, 3e9, 101)
port.CalcPort(SIM_PATH, freq)
s11 = port.uf_ref / port.uf_inc
i_res = int(np.argmin(np.abs(s11)))
f_res = float(freq[i_res])
p_in = 0.5 * float(np.real(port.uf_tot[i_res] * np.conj(port.if_tot[i_res])))
print(f"resonance: {20*np.log10(np.abs(s11[i_res])):.2f} dB @ {f_res/1e9:.3f} GHz",
      flush=True)

theta = np.arange(0.0, 181.0, 2.0)
phi = np.arange(0.0, 360.0, 10.0)
print("running NF2FF ...", flush=True)
ff = nf2ff.CalcNF2FF(SIM_PATH, f_res, theta, phi, read_cached=False)

dmax = float(ff.Dmax[0])
prad = float(ff.Prad[0])
eff = prad / p_in
gain_dbi = 10 * np.log10(dmax * eff)
print(f"Dmax={10*np.log10(dmax):.2f} dBi  Prad={prad:.4e} W  "
      f"P_in={p_in:.4e} W  eff={eff:.3f}  gain={gain_dbi:.2f} dBi", flush=True)

e_t = ff.E_theta[0]  # [theta, phi], complex, r=1 m
e_p = ff.E_phi[0]
with open(os.path.join(HERE, "patch_farfield.csv"), "w") as f:
    f.write("# official openEMS python API NF2FF reference: tutorial patch antenna\n")
    f.write(f"# f_res_hz={f_res:.6e},Dmax={dmax:.6e},Prad={prad:.6e},"
            f"P_in={p_in:.6e},efficiency={eff:.6e},radius_m=1\n")
    f.write("theta_deg,phi_deg,e_theta_re,e_theta_im,e_phi_re,e_phi_im\n")
    for it, th in enumerate(theta):
        for ip, ph in enumerate(phi):
            f.write(f"{th:.1f},{ph:.1f},"
                    f"{e_t[it, ip].real:.6e},{e_t[it, ip].imag:.6e},"
                    f"{e_p[it, ip].real:.6e},{e_p[it, ip].imag:.6e}\n")

shutil.copy(os.path.join(SIM_PATH, "nf2ff.h5"),
            os.path.join(HERE, "patch_nf2ff.h5"))
print("fixtures written: patch_farfield.csv, patch_nf2ff.h5", flush=True)
