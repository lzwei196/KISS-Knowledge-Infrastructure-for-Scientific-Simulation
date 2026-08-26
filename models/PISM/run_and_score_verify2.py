#!/usr/bin/env python3
"""
PISM verifier (verify_2) — BedMachine Greenland v6 mask (ice extent / grounding line).

Pipeline (resumable):
  1. convert_geometry.py : BedMachine Greenland -> PISM bootstrap (topg, thk, smb, ice_temp)
  2. run_pism.py         : bootstrap SIA hold (1 yr, energy off) -> spatial mask/thk/usurf
  3. score               : PISM mask vs BedMachine mask -> CSI (dag determining_metric)
                           + binary ice-presence NSE/KGE/PBIAS over the Greenland landmask.

The /mnt PISM binary links miniconda MPI, so we prepend miniconda/bin to PATH
so run_pism.py's shutil.which("mpiexec") resolves the *matching* conda mpiexec
(orterun from ~/.local mismatches -> PMPIX_Comm_revoke crash; see verify_1).
"""
import os, sys, json, subprocess, traceback

BASE      = "KISSPATH_KI_ROOT/PISM"
KI        = f"{BASE}/knowledge_infrastructure"
TOOLS     = f"{KI}/tools"
STATE     = f"{BASE}/detached/verify_2"
OBS       = "KISSPATH_OBS/ice_sheets/bedmachine/BedMachineGreenland-v6.nc"
PISM_BIN  = f"{BASE}/build/pism"
PROJ      = "+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

BOOT      = f"{STATE}/greenland_bootstrap.nc"
OUT       = f"{STATE}/greenland_out.nc"
SPATIAL   = f"{STATE}/greenland_spatial.nc"
RESULT    = f"{STATE}/result.json"
COARSEN   = 50          # 150 m * 50 = 7.5 km whole-Greenland grid
GRID_DX   = 7.5

os.makedirs(STATE, exist_ok=True)
sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")

# conda MPI must be found first so it matches the /mnt binary's linkage
env = dict(os.environ)
env["PATH"] = "KISSPATH_HOME/miniconda3/bin:" + env.get("PATH", "")
PY = "/usr/bin/python3"


def log(*a):
    print(*a, flush=True)


def sh(cmd):
    log("EXEC:", " ".join(cmd))
    r = subprocess.run(cmd, env=env, cwd=STATE, capture_output=True, text=True)
    log(r.stdout[-3000:])
    if r.returncode != 0:
        log("STDERR:", r.stderr[-3000:])
    return r


def build_bootstrap():
    if os.path.exists(BOOT):
        log("resume: bootstrap exists"); return
    cmd = [PY, f"{TOOLS}/convert_geometry.py",
           "--input", OBS, "--output", BOOT,
           "--topg-var", "bed", "--thk-var", "thickness", "--thk-units", "m",
           "--coarsen", str(COARSEN),
           "--const-smb", "0", "--const-ice-temp", "248.15",
           "--projection", PROJ,
           "--output-json", f"{STATE}/convert_geometry_result.json"]
    r = sh(cmd)
    if r.returncode != 0 or not os.path.exists(BOOT):
        raise RuntimeError("convert_geometry failed")


def run_pism():
    if os.path.exists(SPATIAL):
        log("resume: spatial output exists"); return
    cmd = [PY, f"{TOOLS}/run_pism.py",
           "--input", BOOT, "--output", OUT, "--mode", "bootstrap",
           "--dynamics", "sia", "--grid-dx", str(GRID_DX),
           "--lz", "4000", "--grid-mz", "61", "--duration", "1",
           "--nprocs", "4", "--skip-max", "20", "--sia-e", "3.0",
           "--pism-bin", PISM_BIN,
           "--spatial-file", SPATIAL, "--spatial-times", "1",
           "--spatial-vars", "usurf,thk,topg,mask",
           "--extra-args",
           "-surface given -energy none "
           "-grid.recompute_longitude_and_latitude false "
           "-ocean constant -stress_balance.sia.max_diffusivity 5e5",
           "--output-json", f"{STATE}/run_pism_result.json"]
    r = sh(cmd)
    if not os.path.exists(SPATIAL):
        raise RuntimeError("run_pism produced no spatial file")


def score():
    import numpy as np, netCDF4 as nc
    from ki_tools_common.metrics import all_metrics

    # --- PISM output ---
    d = nc.Dataset(SPATIAL)
    pm = np.asarray(d.variables["mask"][:])
    if pm.ndim == 3:
        pm = pm[-1]
    px = np.asarray(d.variables["x"][:], float)
    py = np.asarray(d.variables["y"][:], float)
    mvar = d.variables["mask"]
    fv = getattr(mvar, "flag_values", None)
    fm = getattr(mvar, "flag_meanings", "")
    log("PISM mask flag_values:", fv, "| meanings:", fm)
    log("PISM mask uniques:", dict(zip(*[a.tolist() for a in np.unique(pm, return_counts=True)])))

    # PISM 2.x cell_type: 2=grounded ice, 3=floating ice are the ice classes.
    pism_ice = np.isin(pm, [2, 3])

    # --- BedMachine obs, nearest-sample onto PISM grid ---
    o = nc.Dataset(OBS)
    om = np.asarray(o.variables["mask"][:])          # 0 ocean,1 land,2 grounded,3 floating
    ox = np.asarray(o.variables["x"][:], float)
    oy = np.asarray(o.variables["y"][:], float)

    # obs axes: x increasing, y DECREASING -> flip y for searchsorted
    yflip = oy[0] > oy[-1]
    oy_s = oy[::-1] if yflip else oy
    xi = np.clip(np.searchsorted(ox, px), 0, len(ox) - 1)
    yi_s = np.clip(np.searchsorted(oy_s, py), 0, len(oy_s) - 1)
    yi = (len(oy) - 1 - yi_s) if yflip else yi_s

    OM = om[np.ix_(yi, xi)]                           # obs mask on PISM grid (ny,nx)
    obs_ice = np.isin(OM, [2, 3])
    obs_land_or_ice = OM != 0                         # everything except open ocean

    # --- CSI of ice extent (dag determining_metric) over full grid ---
    hits = int(np.sum(pism_ice & obs_ice))
    miss = int(np.sum(~pism_ice & obs_ice))
    fa   = int(np.sum(pism_ice & ~obs_ice))
    csi  = hits / (hits + miss + fa) if (hits + miss + fa) else float("nan")
    pod  = hits / (hits + miss) if (hits + miss) else float("nan")
    far  = fa / (hits + fa) if (hits + fa) else float("nan")
    # grounded-only CSI
    pg, og = (pm == 2), (OM == 2)
    gh, gm_, gf = int(np.sum(pg & og)), int(np.sum(~pg & og)), int(np.sum(pg & ~og))
    csi_g = gh / (gh + gm_ + gf) if (gh + gm_ + gf) else float("nan")

    # --- NSE/KGE/PBIAS on binary ice-presence over the Greenland landmask ---
    # (restrict to obs land-or-ice cells so vast ocean does not trivially inflate)
    sel = obs_land_or_ice
    obs_v = obs_ice[sel].astype(float)
    sim_v = pism_ice[sel].astype(float)
    m = all_metrics(obs_v, sim_v)
    n = int(sel.sum())
    log(f"n_landmask={n} obs_ice_frac={obs_v.mean():.3f} sim_ice_frac={sim_v.mean():.3f} "
        f"CSI={csi:.3f} POD={pod:.3f} FAR={far:.3f} CSI_grounded={csi_g:.3f}")

    cat_acc = float(np.mean(pism_ice == obs_ice))     # overall agreement incl ocean

    out = {
        "model_id": "PISM",
        "this_location": "BedMachine Greenland v6 (150m ice thickness & bed topography)",
        "obs_source": "BedMachine Greenland v6 (150m ice thickness & bed topography)",
        "status": "completed",
        "tools_used": ["convert_geometry.py", "run_pism.py",
                       "ki_tools_common.metrics.all_metrics"],
        "tools_failed": [],
        "metrics": {
            "nse": float(m["NSE"]), "kge": float(m["KGE"]),
            "pbias": float(m["PBIAS"]), "r": float(m["r"]),
            "period": "spatial_snapshot (BedMachine v6, no temporal split)",
            "csi_ice_extent": float(csi),
            "pod": float(pod), "far": float(far),
            "csi_grounded": float(csi_g),
            "categorical_accuracy": cat_acc,
            "n_landmask": n,
            "n_hits": hits, "n_miss": miss, "n_false_alarm": fa,
            "obs_ice_fraction": float(obs_v.mean()),
            "sim_ice_fraction": float(sim_v.mean()),
        },
        "water_balance": {"status": "N/A", "residual_pct": None},
        "notes": (
            f"PISM 2.x SIA bootstrap hold (1 yr, energy off) over whole Greenland at "
            f"{GRID_DX} km bootstrapped from BedMachine Greenland v6 (coarsen {COARSEN}). "
            f"Validated variable=mask (cell_type, dag validation_rank 6, "
            f"categorical_event_comparison, determining_metric=CSI). Ice extent CSI={csi:.3f} "
            f"(POD={pod:.3f}, FAR={far:.3f}, grounded-only CSI={csi_g:.3f}); binary ice-presence "
            f"over the Greenland landmask (n={n}) NSE={m['NSE']:.3f}/KGE={m['KGE']:.3f}/"
            f"PBIAS={m['PBIAS']:.2f}. Comparison is partly circular (geometry bootstrapped from "
            f"the same BedMachine thickness), so high CSI mainly confirms the flotation/extent "
            f"classification; the genuine signal is margin & grounding-line placement. conda "
            f"mpiexec used to match the /mnt binary's MPI linkage (fixes verify_1 code-127)."
        ),
    }
    with open(RESULT, "w") as f:
        json.dump(out, f, indent=2)
    log("WROTE", RESULT)
    log(json.dumps(out["metrics"], indent=2))


def main():
    try:
        build_bootstrap()
        run_pism()
        score()
    except Exception as e:
        traceback.print_exc()
        with open(RESULT, "w") as f:
            json.dump({
                "model_id": "PISM",
                "this_location": "BedMachine Greenland v6 (150m ice thickness & bed topography)",
                "obs_source": "BedMachine Greenland v6 (150m ice thickness & bed topography)",
                "status": "failed", "tools_used": [], "tools_failed": ["run_and_score_verify2"],
                "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
                "water_balance": {"status": "N/A", "residual_pct": None},
                "notes": f"verify_2 failed: {e}",
            }, f, indent=2)
        sys.exit(1)


if __name__ == "__main__":
    main()
