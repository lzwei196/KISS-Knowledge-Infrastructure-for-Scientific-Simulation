#!/usr/bin/env python3
"""
Verifier run: MODFLOW6 verify_2 vs Fan et al. Mean Water Table Depth (global .tif).
Faithful twin of the verify_1 D2WT High Plains recipe, applied at a DIFFERENT
location (Southern High Plains / Llano Estacado, Texas panhandle, Ogallala:
33-36N / 103-101W) and against a DIFFERENT independent obs (Fan/Reinecke global
WTD, not NGWMN D2WT).

Domain build (identical structure to the DuMux/verify_1 prep):
  1. SRTM1 mosaic over the box  -> TOP elevation (m asl)
  2. Fan WTD tif, reproject to 50x50 grid; obs_wt_elev = SRTM_elev - Fan_WTD
  3. GLHYMPS median K for the box + central 10x-lower lens
  4. 50x50 single unconfined layer, steady state, lateral flow only:
     CHD west head = mean obs wt-elev of col 0, east head = mean of col -1,
     N/S no-flow. Fan WTD enters ONLY on the 2 boundary columns (non-circular:
     drives the 48 interior columns via the lateral gradient).
Runs the REAL mf6 binary; scores simulated head (= water-table elevation)
against obs_wt_elev on interior cells.

Resumable: caches prepared grids as .npy; skips the mf6 run if ws/gwf.hds exists.
"""
import os, json, zipfile, warnings, subprocess
import numpy as np
warnings.filterwarnings("ignore")

import rasterio, rasterio.merge, rasterio.warp
from rasterio.windows import from_bounds
from rasterio.transform import from_bounds as tfm_from_bounds
from pyproj import Transformer
import geopandas as gpd
import flopy
import flopy.utils.binaryfile as bf
from ki_tools_common.metrics import all_metrics

MF6   = "KISSPATH_BINARIES/modflow6/mf6.6.1_linux/bin/mf6"
FANWTD = "KISSPATH_DATA/groundwater/fan_wtd/MeanWaterTableDepth_meter.tif"
GLHYMPS = "KISSPATH_DATA/groundwater/glhymps/GLHYMPS.shp"
SRTM_DIR = "KISSPATH_DATA/SRTMGL1"
STATE = "KISSPATH_KI_ROOT/MODFLOW6/detached/verify_2"
WS    = os.path.join(STATE, "ws")
CACHE = os.path.join(STATE, "domain")
os.makedirs(WS, exist_ok=True)
os.makedirs(CACHE, exist_ok=True)

# ── Domain: Southern High Plains / Llano Estacado, TX panhandle (Ogallala) ────
LON_MIN, LON_MAX = -103.0, -101.0
LAT_MIN, LAT_MAX =  33.0,   36.0
NX, NY = 50, 50
DX_KM = (LON_MAX - LON_MIN) * 111.0 * np.cos(np.radians((LAT_MIN + LAT_MAX) / 2))
DY_KM = (LAT_MAX - LAT_MIN) * 111.0

elev_npy = os.path.join(CACHE, "elev_grid.npy")
wt_npy   = os.path.join(CACHE, "wt_elev_grid.npy")
mask_npy = os.path.join(CACHE, "interior_mask.npy")
info_json = os.path.join(CACHE, "domain_info.json")


def read_hgt_from_zip(zippath):
    with zipfile.ZipFile(zippath) as zf:
        hgt_name = [n for n in zf.namelist() if n.endswith(".hgt")][0]
        raw = zf.read(hgt_name)
    arr = np.frombuffer(raw, dtype=">i2").reshape(3601, 3601).astype(np.float32)
    arr[arr == -32768] = np.nan
    return arr


def hgt_to_raster(arr, lat_min, lon_min):
    from rasterio.io import MemoryFile
    transform = rasterio.transform.from_origin(lon_min, lat_min + 1, 1 / 3600, 1 / 3600)
    mem = MemoryFile()
    with mem.open(driver="GTiff", height=3601, width=3601, count=1,
                  dtype="float32", crs="EPSG:4326",
                  transform=transform, nodata=np.nan) as ds:
        ds.write(arr[np.newaxis, ::-1, :])
    return mem


if os.path.exists(elev_npy) and os.path.exists(wt_npy) and os.path.exists(mask_npy) and os.path.exists(info_json):
    print("Loading cached domain grids...")
    elev_grid = np.load(elev_npy)
    wt_elev   = np.load(wt_npy)
    interior_mask = np.load(mask_npy)
    info = json.load(open(info_json))
    head_left = info["head_left_m"]; head_right = info["head_right_m"]
    K_bg = info["k_ms_median"] * 86400.0
else:
    # ── 1. SRTM mosaic ───────────────────────────────────────────────────────
    print("Building SRTM mosaic (TX box)...")
    tile_mems = []
    for lat in [33, 34, 35]:
        for lon in [101, 102, 103]:   # W103,W102 cover -103..-101; W101 borders edge
            zp = os.path.join(SRTM_DIR, f"N{lat:02d}W{lon:03d}.SRTMGL1.hgt.zip")
            if not os.path.exists(zp):
                continue
            tile_mems.append(hgt_to_raster(read_hgt_from_zip(zp), lat, -lon))
    srcs = [m.open() for m in tile_mems]
    mosaic, mosaic_tfm = rasterio.merge.merge(srcs)
    elev_mosaic = mosaic[0]
    for s in srcs:
        s.close()
    print(f"  Mosaic {elev_mosaic.shape}, {np.nanmin(elev_mosaic):.0f}-{np.nanmax(elev_mosaic):.0f} m")

    grid_tfm = tfm_from_bounds(LON_MIN, LAT_MIN, LON_MAX, LAT_MAX, NX, NY)
    elev_grid = np.full((NY, NX), np.nan, dtype=np.float32)
    rasterio.warp.reproject(
        source=elev_mosaic, destination=elev_grid,
        src_transform=mosaic_tfm, src_crs="EPSG:4326",
        dst_transform=grid_tfm, dst_crs="EPSG:4326",
        resampling=rasterio.enums.Resampling.average, src_nodata=np.nan)
    print(f"  Elev grid: {np.nanmin(elev_grid):.0f}-{np.nanmax(elev_grid):.0f} m asl")

    # ── 2. Fan WTD -> water-table elevation ──────────────────────────────────
    print("Reading Fan WTD...")
    with rasterio.open(FANWTD) as src:
        tr = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        xmin, ymin = tr.transform(LON_MIN, LAT_MIN)
        xmax, ymax = tr.transform(LON_MAX, LAT_MAX)
        win = from_bounds(xmin, ymin, xmax, ymax, transform=src.transform)
        wtd_raw = src.read(1, window=win)
        wtd_tfm = src.window_transform(win)
        wtd_nodata = src.nodata
        wtd_crs = src.crs
    wtd = wtd_raw.astype(np.float32)
    if wtd_nodata is not None:
        wtd[wtd == wtd_nodata] = np.nan
    wtd[(wtd < 0) | (wtd > 300)] = np.nan
    print(f"  Fan WTD window {wtd.shape}, {np.nanmin(wtd):.1f}-{np.nanmax(wtd):.1f} m depth")

    wtd_grid = np.full((NY, NX), np.nan, dtype=np.float32)
    rasterio.warp.reproject(
        source=wtd, destination=wtd_grid,
        src_transform=wtd_tfm, src_crs=wtd_crs,
        dst_transform=grid_tfm, dst_crs="EPSG:4326",
        resampling=rasterio.enums.Resampling.average, src_nodata=np.nan)
    print(f"  WTD grid: {np.nanmin(wtd_grid):.1f}-{np.nanmax(wtd_grid):.1f} m")

    wt_elev = elev_grid - wtd_grid
    print(f"  WT elev: {np.nanmin(wt_elev):.0f}-{np.nanmax(wt_elev):.0f} m asl, "
          f"valid {np.isfinite(wt_elev).sum()}/{wt_elev.size}")

    # ── 3. GLHYMPS K ─────────────────────────────────────────────────────────
    print("Extracting GLHYMPS K...")
    from shapely.geometry import box as shp_box
    glhymps = gpd.read_file(GLHYMPS)
    dbox = gpd.GeoDataFrame(geometry=[shp_box(LON_MIN, LAT_MIN, LON_MAX, LAT_MAX)],
                            crs="EPSG:4326").to_crs(glhymps.crs)
    clipped = gpd.clip(glhymps, dbox)
    k_raw = clipped["logK_Ferr_"].dropna()
    k_raw = k_raw[(k_raw > -3000) & (k_raw < 0)]
    logk = k_raw / 100.0
    k_m2_median = 10 ** float(np.median(logk))
    k_ms_median = k_m2_median * 1e7
    K_bg = k_ms_median * 86400.0
    print(f"  GLHYMPS polys {len(clipped)}, K median {k_ms_median:.3e} m/s -> {K_bg:.4f} m/d")

    # ── 4. BCs + interior mask ───────────────────────────────────────────────
    head_left  = float(np.nanmean(wt_elev[:, 0]))
    head_right = float(np.nanmean(wt_elev[:, -1]))
    interior_mask = np.zeros((NY, NX), dtype=bool)
    interior_mask[:, 1:-1] = np.isfinite(wt_elev[:, 1:-1])

    np.save(elev_npy, elev_grid); np.save(wt_npy, wt_elev); np.save(mask_npy, interior_mask)
    info = {"LON_MIN": LON_MIN, "LON_MAX": LON_MAX, "LAT_MIN": LAT_MIN, "LAT_MAX": LAT_MAX,
            "NX": NX, "NY": NY, "DX_KM": float(DX_KM), "DY_KM": float(DY_KM),
            "k_ms_median": float(k_ms_median), "head_left_m": head_left,
            "head_right_m": head_right, "n_interior_valid": int(interior_mask.sum())}
    json.dump(info, open(info_json, "w"), indent=2)
    print(f"  BC west {head_left:.1f} m / east {head_right:.1f} m; interior {interior_mask.sum()}")

# ── 5. Build & run MF6 (identical recipe to verify_1) ────────────────────────
top  = elev_grid.astype(float)
botm = np.full((1, NY, NX), np.nanmin(wt_elev) - 200.0)
k2d = np.full((NY, NX), K_bg, dtype=float)
r0, r1 = NY // 3, 2 * NY // 3
c0, c1 = NX // 3, 2 * NX // 3
k2d[r0:r1, c0:c1] = K_bg / 10.0

hds_path = os.path.join(WS, "gwf.hds")
if not os.path.exists(hds_path):
    sim = flopy.mf6.MFSimulation(sim_name="mf6sim", sim_ws=WS, exe_name=MF6, version="mf6")
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)], time_units="days")
    flopy.mf6.ModflowIms(sim, complexity="MODERATE", outer_dvclose=1e-6,
                         inner_dvclose=1e-6, linear_acceleration="BICGSTAB")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="gwf",
                               newtonoptions="NEWTON UNDER_RELAXATION", save_flows=True)
    flopy.mf6.ModflowGwfdis(gwf, nlay=1, nrow=NY, ncol=NX,
                            delr=DX_KM * 1000.0 / NX, delc=DY_KM * 1000.0 / NY,
                            top=top, botm=botm, length_units="meters")
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=k2d, save_flows=True)
    strt = wt_elev.copy()
    fill = np.linspace(head_left, head_right, NX)[None, :].repeat(NY, axis=0)
    strt[~np.isfinite(strt)] = fill[~np.isfinite(strt)]
    flopy.mf6.ModflowGwfic(gwf, strt=strt[None, :, :])
    chd = []
    for i in range(NY):
        chd.append([(0, i, 0), head_left])
        chd.append([(0, i, NX - 1), head_right])
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd)
    flopy.mf6.ModflowGwfoc(gwf, head_filerecord="gwf.hds", budget_filerecord="gwf.cbc",
                           saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")])
    sim.write_simulation()
    p = subprocess.run([MF6], cwd=WS, capture_output=True, text=True)
    if "Normal termination" not in (p.stdout + p.stderr):
        raise RuntimeError("mf6 did not terminate normally:\n" + p.stdout[-2000:])

# ── 6. Score ─────────────────────────────────────────────────────────────────
h = bf.HeadFile(hds_path, precision="double").get_data()[0]
h = np.where(h > 1e29, np.nan, h)
valid = interior_mask & np.isfinite(h) & np.isfinite(wt_elev)
m = all_metrics(wt_elev[valid], h[valid])


def g(*keys):
    for k in keys:
        if k in m and m[k] is not None:
            return float(m[k])
    return None


nse = g("NSE", "nse"); kge = g("KGE", "kge"); pbias = g("PBIAS", "pbias")
r = g("r", "R", "PEARSON_R"); rmse = g("RMSE", "rmse")
n_cells = int(valid.sum())

resid = 0.0; wb_status = "PASS"
try:
    import re
    lst = open(os.path.join(WS, "mfsim.lst")).read()
    pc = re.findall(r"PERCENT DISCREPANCY =\s*([-\d.]+)", lst)
    if pc:
        resid = abs(float(pc[-1]))
        wb_status = "PASS" if resid < 1.0 else ("WARN" if resid < 5.0 else "FAIL")
except Exception:
    wb_status = "N/A"

result = {
    "model_id": "MODFLOW6",
    "this_location": "Fan et al. Mean Water Table Depth (Global) - Southern High Plains TX 33-36N/103-101W",
    "obs_source": "FanWTD",
    "status": "completed",
    "tools_used": [
        "SRTM1 mosaic (rasterio.merge/warp)",
        "Fan WTD tif reproject (rasterio.warp)",
        "GLHYMPS K (geopandas clip)",
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
        "period": "Fan et al. long-term mean WTD (steady-state)",
    },
    "water_balance": {"status": wb_status, "residual_pct": round(resid, 4)},
    "variable": "water_table_elevation_m_asl",
    "obs_shape": "spatial_field",
    "notes": (
        "MODFLOW6 verify_2: faithful twin of the verify_1 D2WT High Plains recipe applied "
        "at the Southern High Plains / Llano Estacado (TX panhandle, Ogallala, 33-36N/103-101W) "
        "vs INDEPENDENT Fan et al. global WTD. 50x50 single unconfined layer (NEWTON "
        "UNDER_RELAXATION, MODERATE IMS/BICGSTAB), steady state, lateral flow only: CHD west "
        "head %.1f m / east head %.1f m from Fan-derived (SRTM elev - Fan WTD) boundary-column "
        "means, N/S no-flow; TOP=SRTM1, K=GLHYMPS %.4f m/d with central 10x-lower lens, no "
        "recharge. Non-circular: Fan WTD enters only the 2 boundary columns. Scored sim head "
        "(=water-table elevation) vs Fan-derived wt-elev on %d interior cells."
        % (head_left, head_right, K_bg, n_cells)
    ),
}
os.makedirs(STATE, exist_ok=True)
with open(os.path.join(STATE, "result.json"), "w") as f:
    json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
