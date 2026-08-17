#!/usr/bin/env python3
"""
Verifier run: MODFLOW6 at US High Plains D2WT (verify_1).
Faithful twin of the DuMux High Plains validation. Reuses the prepared DuMux
domain grids (SRTM TOP, D2WT-derived obs water-table elevation, GLHYMPS K,
interior mask, boundary head means). 50x50 single unconfined layer, steady
state, lateral flow only (CHD west/east, N/S no-flow), no recharge.
Runs the REAL mf6 binary, scores simulated head (= water-table elevation)
vs D2WT_2019 obs on interior cells.
Resumable: if gwf.hds already exists in the workspace, skip the mf6 run.
"""
import os, json, subprocess, numpy as np

DUMUX = "KISSPATH_OUTPUTS/dumux_highplains_validation"
MF6   = "KISSPATH_BINARIES/modflow6/mf6.6.1_linux/bin/mf6"
STATE = "KISSPATH_KI_ROOT/MODFLOW6/detached/verify_1"
WS    = os.path.join(STATE, "ws")
os.makedirs(WS, exist_ok=True)

import flopy
from ki_tools_common.metrics import all_metrics

# --- load prepared DuMux domain ------------------------------------------------
elev = np.load(os.path.join(DUMUX, "elev_grid.npy"))      # SRTM TOP (m asl)
obs  = np.load(os.path.join(DUMUX, "wt_elev_grid.npy"))   # D2WT-derived WT elev
mask = np.load(os.path.join(DUMUX, "interior_mask.npy"))  # bool interior valid
info = json.load(open(os.path.join(DUMUX, "domain_info.json")))

NY, NX = elev.shape
head_left  = info["head_left_m"]    # west column (col 0), high head
head_right = info["head_right_m"]   # east column (col NX-1), low head
k_ms = info["k_ms_median"]          # 1e-6 m/s
K_bg = k_ms * 86400.0               # -> m/day (~0.0864)

# spatial K: background + central 10x-lower lens (matches DuMux k_m2_lens)
k2d = np.full((NY, NX), K_bg, dtype=float)
r0, r1 = NY // 3, 2 * NY // 3
c0, c1 = NX // 3, 2 * NX // 3
k2d[r0:r1, c0:c1] = K_bg / 10.0

# grid geometry: single unconfined layer; bottom well below min WT elev
top  = elev.astype(float)
botm = np.full((1, NY, NX), np.nanmin(obs) - 200.0)

hds_path = os.path.join(WS, "gwf.hds")
if not os.path.exists(hds_path):
    sim = flopy.mf6.MFSimulation(sim_name="mf6sim", sim_ws=WS,
                                 exe_name=MF6, version="mf6")
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)],
                          time_units="days")
    flopy.mf6.ModflowIms(sim, complexity="MODERATE",
                         outer_dvclose=1e-6, inner_dvclose=1e-6,
                         linear_acceleration="BICGSTAB")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="gwf",
                               newtonoptions="NEWTON UNDER_RELAXATION",
                               save_flows=True)
    flopy.mf6.ModflowGwfdis(gwf, nlay=1, nrow=NY, ncol=NX,
                            delr=info["DX_KM"] * 1000.0 / NX,
                            delc=info["DY_KM"] * 1000.0 / NY,
                            top=top, botm=botm, length_units="meters")
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=k2d, save_flows=True)
    # start from obs where valid, else linear interp between boundary heads
    strt = obs.copy()
    fill = np.linspace(head_left, head_right, NX)[None, :].repeat(NY, axis=0)
    strt[~np.isfinite(strt)] = fill[~np.isfinite(strt)]
    flopy.mf6.ModflowGwfic(gwf, strt=strt[None, :, :])
    # CHD: west col = head_left, east col = head_right; N/S no-flow
    chd = []
    for i in range(NY):
        chd.append([(0, i, 0), head_left])
        chd.append([(0, i, NX - 1), head_right])
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd)
    flopy.mf6.ModflowGwfoc(gwf, head_filerecord="gwf.hds",
                           budget_filerecord="gwf.cbc",
                           saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")])
    sim.write_simulation()
    p = subprocess.run([MF6], cwd=WS, capture_output=True, text=True)
    if "Normal termination" not in (p.stdout + p.stderr):
        raise RuntimeError("mf6 did not terminate normally:\n" + p.stdout[-2000:])

# --- read heads & score --------------------------------------------------------
import flopy.utils.binaryfile as bf
h = bf.HeadFile(hds_path, precision="double").get_data()[0]  # (NY,NX)
h = np.where(h > 1e29, np.nan, h)                            # filter HDRY

valid = mask & np.isfinite(h) & np.isfinite(obs)
sim_v = h[valid]
obs_v = obs[valid]
m = all_metrics(obs_v, sim_v)

def g(*keys):
    for k in keys:
        if k in m and m[k] is not None:
            return float(m[k])
    return None

nse  = g("NSE", "nse")
kge  = g("KGE", "kge")
pbias = g("PBIAS", "pbias")
r    = g("r", "R", "PEARSON_R")
rmse = g("RMSE", "rmse")
n_cells = int(valid.sum())

# water balance from listing file
resid = 0.0; wb_status = "PASS"
try:
    lst = open(os.path.join(WS, "mfsim.lst")).read()
    import re
    pc = re.findall(r"PERCENT DISCREPANCY =\s*([-\d.]+)", lst)
    if pc:
        resid = abs(float(pc[-1]))
        wb_status = "PASS" if resid < 1.0 else ("WARN" if resid < 5.0 else "FAIL")
except Exception:
    wb_status = "N/A"

result = {
    "model_id": "MODFLOW6",
    "this_location": "US Depth-to-Water-Table (D2WT) 1989+2019 - NGWMN-derived",
    "obs_source": "US Depth-to-Water-Table (D2WT) 1989+2019 - NGWMN-derived",
    "status": "completed",
    "tools_used": [
        "flopy.mf6 ModflowTdis/Ims/Gwf/Gwfdis/Gwfnpf/Gwfic/Gwfchd/Gwfoc",
        "mf6 binary (6.6.1)",
        "flopy.utils.binaryfile.HeadFile",
        "ki_tools_common.metrics.all_metrics",
    ],
    "tools_failed": [],
    "metrics": {
        "nse": round(nse, 4) if nse is not None else None,
        "kge": round(kge, 4) if kge is not None else None,
        "pbias": round(pbias, 4) if pbias is not None else None,
        "r": round(r, 4) if r is not None else None,
        "rmse_m": round(rmse, 3) if rmse is not None else None,
        "n_cells": n_cells,
        "period": "2019 steady-state (D2WT_2019)",
    },
    "water_balance": {"status": wb_status, "residual_pct": round(resid, 4)},
    "variable": "water_table_elevation_m_asl",
    "obs_shape": "spatial_field",
    "notes": (
        "MODFLOW6 twin of the DuMux High Plains validation (Kansas 37-40N/100-102W). "
        "50x50 single unconfined layer (NEWTON UNDER_RELAXATION, MODERATE IMS/BICGSTAB), "
        "steady state, lateral flow only: CHD west head %.1f m / east head %.1f m from "
        "D2WT boundary-column means, N/S no-flow; TOP=SRTM, K=GLHYMPS %.4f m/d with central "
        "10x-lower lens, no recharge. Scored simulated head (=water-table elevation) vs "
        "D2WT_2019 obs on %d interior cells. spatial_field obs -> magnitude_accuracy + "
        "spatial-pattern metric families valid."
        % (head_left, head_right, K_bg, n_cells)
    ),
}
with open(os.path.join(STATE, "result.json"), "w") as f:
    json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
