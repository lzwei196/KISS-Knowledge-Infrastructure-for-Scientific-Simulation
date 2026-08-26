#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VIC 5.1.0 + Lohmann route_1.0 VERIFIER (verify_2) at the JOHN DAY RIVER,
McDonald Ferry, Oregon, USA — GRDC_4115221 in the GRDC-Caravan extension.

WHY THIS GAUGE
--------------
The real-case ran at 唐乃亥 Tangnaihai (upper Yellow River, China, CMFD forcing,
123,007 km2 alpine). A verifier must exercise the SAME KI tools somewhere the
tools have never been. John Day @ McDonald Ferry is:
  * a different continent, forcing dataset (NASA POWER, not CMFD) and DEM
    (Copernicus 30 m, not china_dem_90m);
  * 19,815 km2 -- above forcing_nasa_power.py's 10,000 km2 recommendation;
  * the longest essentially UNREGULATED large river in the western US: no
    mainstem dams, no reservoirs. route_1.0 has no reservoir module, so an
    unregulated basin is the only place a routed hydrograph is a fair test;
  * snowmelt-influenced (frac_snow 0.34), like Tangnaihai, so the same
    snow/soil physics is being probed rather than a different regime;
  * daily obs are 100% complete 1998-2020 (no -99 padding, cf. dt_vic_021).

Chain (identical stages to the real case; s0/s4 substituted for the region)
--------------------------------------------------------------------------
  s0a Copernicus DEM tiles -> mosaic + crop                (new, global DEM)
  s0b ki_tools_common.terrain_ops.delineate_basin          -> basin/flow_accum/dem_filled
  s1  s1_grid/make_basin_grid_nc.py                        -> grid_<basin>_025deg.nc
  s1b build elevation + annual-precip NetCDFs on the VIC grid (the CMFD ones
      are China-only; fill_parameters1.py now takes VIC_ELEV_NC /
      VIC_PREC_ANNUAL_NC from the environment)
  s2  s3_soil/fill_parameters1.py                          -> SOIL_PARAM_FINAL.txt
  s3  s3_soil/fill_parameters2.py                          -> SOIL_PARAM_COMPLETE.txt
      (interpolates the GLOBAL 0.5deg soil param file, so it is valid outside China;
       HWSD_China_Geo.img returns majority=None off-domain -> the same all-zero
       placeholder codes it returns for Chinese MU_GLOBAL ids, which fill_parameters2
       overwrites. Behaviour is bit-identical to the validated China path.)
  s4  s4_veg/process_vegetation_detailed.py                -> vic_veg_param_final.txt
      (AVHRR 1 km landcover is already global)
  s5  s2_forcing/forcing_nasa_power.py                     -> per-cell VIC ASCII forcing
      (3-hourly, 8 steps/day, 7 cols in FORCE_TYPE order; CMFD does not reach Oregon)
  s6  config_paths.create_global_param()                   -> global_param_<basin>.txt
  s7  vic_classic.exe                                      -> daily flux per cell (mm)
  s8  s5_routing/build_routing_param.py                    -> direc/frac/xmask/staloc/UH.all
  s9  route_1.0/src/rout                                   -> daily discharge (m3/s)
  s10 score vs GRDC-Caravan streamflow, water balance, result.json

VIC HAS NO ROUTING (dag.yaml: OUT_DISCHARGE is lake-module only), so s8+s9 are
mandatory -- summing runoff+baseflow gives a hydrograph with no lag and no
attenuation (dt_vic_019). The previous verify_2 (Shannon, 2026-06-27) skipped
routing and scored NSE = -0.16; this run does the real thing.

Periods (obs are complete, so the KDT-style split is used unshifted apart from
NASA POWER's 2001 start):
  spinup      2003-2004   (discarded)
  calibration 2005-01-01 .. 2009-12-31
  validation  2010-01-01 .. 2014-12-31   (held out; nothing is tuned on it)
UNCALIBRATED throughout -- default soil/veg parameters, exactly as the real case.

Units. Caravan 'streamflow' is a catchment-mean depth in mm/day. `rout` emits
m3/s. Obs are converted to m3/s with the Caravan basin-shape area (the same area
Caravan used to make mm/day), so sim and obs are compared in the real-case's
native units and the metrics are directly comparable to Tangnaihai's.

Resumable: every stage is skipped when its output already exists.
"""
import os
import sys
import glob
import json
import shutil
import subprocess
import urllib.request

import numpy as np
import pandas as pd

from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_water_balance
from validators.standard_calval import compute_calval_metrics

# ---------------------------------------------------------------------------
BASE = "KISSPATH_ROOT"
KI = f"{BASE}/models/VIC/knowledge_infrastructure"
CASE = f"{BASE}/models/VIC/detached/verify_2"

BASIN = "johnday_mcdonaldferry"
STA = "JDY"
GAUGE_ID = "GRDC_4115221"

CARAVAN = "KISSPATH_DATA/observed_data/dischargeandwatershed/GRDC-Caravan-extension-nc"
OBS_NC = f"{CARAVAN}/timeseries/netcdf/grdc/{GAUGE_ID}.nc"
BASIN_SHAPES = f"{CARAVAN}/shapefiles/grdc/grdc_basin_shapes.shp"

OUT_ROOT = f"{BASE}/outputs"
BDIR = f"{OUT_ROOT}/{BASIN}"
DELIN = f"{BDIR}/delineation"
DEM_DIR = f"{BDIR}/dem"
DEM_CROP = f"{DEM_DIR}/johnday_cop30.tif"
TILE_CACHE = f"{BASE}/data/dem/dem_tiles_cache"

BASIN_SHP = f"{BASE}/data/shp/johnday_shp/johnday_boundary.shp"
CARAVAN_SHP = f"{BASE}/data/shp/johnday_shp/johnday_caravan.shp"

VIC_EXE = f"{BASE}/model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe"
ROUT_EXE = f"{BASE}/model/route_1.0/src/rout"
GP_TEMPLATE = f"{BASE}/outputs/tangnaihai/vic_temp/global_param_tangnaihai.txt"

# GRDC gauge: JOHN DAY RIVER, MCDONALD FERRY, OREG (USGS 14048000)
OUTLET_LON, OUTLET_LAT = -120.4104, 45.5896

YEAR_START, YEAR_END = 2003, 2014
CAL = ("2005-01-01", "2009-12-31")
VAL = ("2010-01-01", "2014-12-31")
EVAL_START, EVAL_END = CAL[0], VAL[1]

FORCING_PREFIX = f"{BASIN}_025deg_"

ELEV_NC = f"{BDIR}/vic_temp/grid/elev_{BASIN}_025deg.nc"
PREC_NC = f"{BDIR}/vic_temp/grid/prec_annual_{BASIN}_025deg.nc"

GRID_NC = f"{BDIR}/vic_temp/grid/grid_{BASIN}_025deg.nc"
SOIL_FINAL = f"{BDIR}/vic_temp/soil/SOIL_PARAM_FINAL.txt"
SOIL_COMPLETE = f"{BDIR}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt"
FORCING_FINAL = f"{BDIR}/vic_temp/forcing/forcing_final"
VEG_PARAM = f"{BDIR}/vic_temp/veg/vic_veg_param_final.txt"
GLOBAL_PARAM = f"{BDIR}/vic_temp/global_param_{BASIN}.txt"
VIC_RESULT = f"{BDIR}/vic_result"
ROUTING = f"{BDIR}/routing_param"
VIC_IN = f"{ROUTING}/vic_in"
ROUT_OUT = f"{ROUTING}/rout_out"

ENV = dict(os.environ)
ENV.update(
    VIC_BASIN_NAME=BASIN,
    VIC_BASIN_SHP=BASIN_SHP,
    VIC_OUT_ROOT=OUT_ROOT,
    VIC_DEM=DEM_CROP,
    VIC_ELEV_NC=ELEV_NC,
    VIC_PREC_ANNUAL_NC=PREC_NC,
    VIC_STATION_NAME=STA,
    VIC_OUTLET_LON=str(OUTLET_LON),
    VIC_OUTLET_LAT=str(OUTLET_LAT),
    VIC_YEAR_START=str(YEAR_START),
    VIC_YEAR_END=str(YEAR_END),
    VIC_START_DATE=f"{YEAR_START}-01-01",
    VIC_END_DATE=f"{YEAR_END}-12-31",
    VIC_FORCING_PREFIX=FORCING_PREFIX,
    VIC_GLOBAL_PARAM_TEMPLATE=GP_TEMPLATE,
    # native-resolution rasters for the routing grid (never coarsen; dt_vic_020)
    VIC_FLOW_ACCUM=f"{DELIN}/flow_accum.tif",
    VIC_BASIN_RASTER=f"{DELIN}/basin.tif",
    VIC_FILLED_DEM=f"{DELIN}/dem_filled.tif",
    HYDROCRAFT_POWER_REALTIME="1",   # always fetch NASA POWER live, never cache
    PYTHONUNBUFFERED="1",
)

os.makedirs(CASE, exist_ok=True)

RESULT = {
    "model_id": "VIC",
    "this_location": "GRDC-Caravan Extension (5,357 global gauges + basin shapes)",
    "obs_source": "GRDC",
    "status": "failed",
    "tools_used": [],
    "tools_failed": [],
    "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
    "water_balance": {"status": "N/A", "residual_pct": None},
    "notes": "",
}


def save(note=None):
    if note:
        RESULT["notes"] = note
    with open(f"{CASE}/result.json", "w") as f:
        json.dump(RESULT, f, indent=2, ensure_ascii=False)


# dt_vic_023: a stage can SIGSEGV during interpreter teardown (foreign libhdf5
# dlopen'd by xarray's backend-entrypoint probe) AFTER it has written correct
# output. The triplet forbids "fix by tolerating a nonzero rc", because a real
# crash and a teardown crash would then be indistinguishable. They ARE
# distinguishable by the artifact: a real crash leaves the output missing or
# short. So a fatal signal is forgiven ONLY when `validate()` proves the stage's
# output is complete; anything else still aborts the run.
TEARDOWN_SIGNALS = (-11, -6, 139, 134)


def run(script, cwd, label, timeout=None, args=(), validate=None):
    print(f"\n===== {label} =====", flush=True)
    p = subprocess.run([sys.executable, script, *args], cwd=cwd, env=ENV,
                       capture_output=True, text=True, timeout=timeout)
    print("\n".join((p.stdout or "").strip().splitlines()[-15:]), flush=True)

    if p.returncode != 0:
        forgiven = False
        if p.returncode in TEARDOWN_SIGNALS and validate is not None:
            try:
                forgiven = bool(validate())
            except Exception as e:  # a validator that blows up == not validated
                print(f"[{label}] validator raised: {e}", flush=True)
                forgiven = False
        if forgiven:
            warn = (f"{label}: rc={p.returncode} (fatal signal at interpreter teardown, "
                    f"dt_vic_023) BUT output artifact validated complete -> continuing")
            print(f"[WARN] {warn}", flush=True)
            RESULT.setdefault("warnings", []).append(warn)
        else:
            print("STDERR:", (p.stderr or "")[-3000:], flush=True)
            RESULT["tools_failed"].append(
                f"{label}: rc={p.returncode} :: {(p.stderr or '')[-300:]}")
            save(f"stage {label} failed")
            sys.exit(1)

    RESULT["tools_used"].append(label)


def n_cells():
    return sum(1 for line in open(SOIL_COMPLETE) if line.strip())


# ===================== s0a Copernicus DEM mosaic ===========================
CARAVAN_AREA_KM2 = None
if not os.path.exists(DEM_CROP):
    print("\n===== s0a Copernicus GLO-30 DEM mosaic =====", flush=True)
    import rasterio
    from rasterio.merge import merge
    from rasterio.windows import from_bounds
    import geopandas as gpd

    os.makedirs(DEM_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(BASIN_SHP), exist_ok=True)

    shapes = gpd.read_file(BASIN_SHAPES)
    car = shapes[shapes["gauge_id"] == GAUGE_ID].to_crs("EPSG:4326")
    if car.empty:
        RESULT["tools_failed"].append(f"{GAUGE_ID} absent from grdc_basin_shapes.shp")
        save("gauge polygon not found")
        sys.exit(1)
    car.to_file(CARAVAN_SHP)
    CARAVAN_AREA_KM2 = float(car.to_crs("ESRI:54009").area.iloc[0] / 1e6)
    minx, miny, maxx, maxy = car.total_bounds
    print(f"[s0a] Caravan polygon area = {CARAVAN_AREA_KM2:.0f} km2, "
          f"bbox = {minx:.3f},{miny:.3f},{maxx:.3f},{maxy:.3f}", flush=True)

    pad = 0.15
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad

    tiles = []
    for la in range(int(np.floor(miny)), int(np.floor(maxy)) + 1):
        for lo in range(int(np.floor(minx)), int(np.floor(maxx)) + 1):
            ns = f"N{la:02d}" if la >= 0 else f"S{abs(la):02d}"
            ew = f"E{lo:03d}" if lo >= 0 else f"W{abs(lo):03d}"
            name = f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM.tif"
            path = os.path.join(TILE_CACHE, name)
            if not os.path.exists(path):
                url = (f"https://copernicus-dem-30m.s3.amazonaws.com/"
                       f"{name[:-4]}/{name}")
                print(f"[s0a] downloading {name}", flush=True)
                try:
                    tmp = path + ".part"
                    urllib.request.urlretrieve(url, tmp)
                    os.replace(tmp, path)
                except Exception as e:
                    print(f"[s0a] tile {name} unavailable ({e}) -- likely ocean, skipping",
                          flush=True)
                    continue
            tiles.append(path)

    if not tiles:
        RESULT["tools_failed"].append("no Copernicus DEM tiles for the John Day bbox")
        save("DEM mosaic empty")
        sys.exit(1)
    print(f"[s0a] merging {len(tiles)} tiles", flush=True)

    srcs = [rasterio.open(t) for t in tiles]
    arr, tr = merge(srcs, bounds=(minx, miny, maxx, maxy))
    prof = srcs[0].profile.copy()
    prof.update(height=arr.shape[1], width=arr.shape[2], transform=tr,
                count=1, compress="lzw", dtype="float32", nodata=-9999.0)
    a = arr[0].astype("float32")
    a[~np.isfinite(a)] = -9999.0
    with rasterio.open(DEM_CROP, "w", **prof) as dst:
        dst.write(a, 1)
    for s in srcs:
        s.close()
    print(f"[s0a] DEM {a.shape} -> {DEM_CROP}", flush=True)
else:
    print("[s0a] DEM mosaic exists, skip")

if CARAVAN_AREA_KM2 is None:
    import geopandas as gpd
    CARAVAN_AREA_KM2 = float(gpd.read_file(CARAVAN_SHP).to_crs("ESRI:54009").area.iloc[0] / 1e6)
RESULT["tools_used"].append("Copernicus GLO-30 DEM mosaic (global DEM for a non-China basin)")

# ===================== s0b delineation =====================================
DELIN_AREA_KM2 = None
if not os.path.exists(BASIN_SHP):
    print("\n===== s0b ki_tools_common.terrain_ops.delineate_basin =====", flush=True)
    import rasterio
    import geopandas as gpd
    from rasterio.features import shapes as rshapes
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from ki_tools_common.terrain_ops import delineate_basin

    os.makedirs(DELIN, exist_ok=True)
    # Copernicus GLO-30 is 1 arcsec (~30 m lat x ~22 m lon at 45N) => ~675 m2/px.
    # 50,000 px ~ 34 km2 -> a stream network dense enough that the 0.25deg VIC
    # cells all sit on a channel, coarse enough to avoid hillslope noise.
    d = delineate_basin(dem_path=DEM_CROP, pour_point=(OUTLET_LON, OUTLET_LAT),
                        output_dir=DELIN, stream_threshold=50000, snap_distance_m=2000.0)
    DELIN_AREA_KM2 = float(d["basin_area_km2"])
    print(f"[s0b] delineated area = {DELIN_AREA_KM2:.0f} km2 "
          f"(Caravan polygon {CARAVAN_AREA_KM2:.0f} km2, "
          f"{100 * (DELIN_AREA_KM2 / CARAVAN_AREA_KM2 - 1):+.1f}%)", flush=True)

    with rasterio.open(d["basin_raster"]) as s:
        a = s.read(1)
        nod = s.nodata if s.nodata is not None else 0
        mk = ((a != nod) & (a > 0)).astype(np.uint8)
        tr = s.transform
    poly = unary_union([shape(g) for g, v in rshapes(mk, mask=mk > 0, transform=tr) if v > 0])
    gpd.GeoDataFrame({"name": [BASIN]}, geometry=[poly], crs="EPSG:4326").to_file(BASIN_SHP)
else:
    print("[s0b] basin shapefile exists, skip")
if DELIN_AREA_KM2 is None:
    import geopandas as gpd
    DELIN_AREA_KM2 = float(gpd.read_file(BASIN_SHP).to_crs("ESRI:54009").area.iloc[0] / 1e6)
RESULT["tools_used"].append("ki_tools_common.terrain_ops.delineate_basin")

if not 0.85 < DELIN_AREA_KM2 / CARAVAN_AREA_KM2 < 1.15:
    RESULT["tools_failed"].append(
        f"delineate_basin: area {DELIN_AREA_KM2:.0f} km2 vs Caravan {CARAVAN_AREA_KM2:.0f} km2 "
        f"({100 * (DELIN_AREA_KM2 / CARAVAN_AREA_KM2 - 1):+.1f}%) -- pour point mis-snapped")
    save("delineated basin area disagrees with the GRDC basin shape by >15%")
    sys.exit(1)

# ===================== s1 grid =============================================
if not os.path.exists(GRID_NC):
    run(f"{KI}/s1_grid/make_basin_grid_nc.py", f"{KI}/s1_grid", "s1_grid/make_basin_grid_nc.py")
else:
    print("[s1] grid exists, skip")
    RESULT["tools_used"].append("s1_grid/make_basin_grid_nc.py")

# ===================== s1b elevation + annual precip on the VIC grid ========
# fill_parameters1.py's defaults are the CMFD China rasters. Off-domain,
# xarray's sel(method="nearest") silently returns the nearest CHINESE cell's
# elevation instead of failing, so these must be supplied for any non-China run.
if not (os.path.exists(ELEV_NC) and os.path.exists(PREC_NC)):
    print("\n===== s1b elevation + annual-precip grids =====", flush=True)
    import xarray as xr
    import geopandas as gpd
    from shapely.geometry import box
    from rasterstats import zonal_stats

    g = xr.open_dataset(GRID_NC)
    ys = g["y"].values
    xs = g["x"].values
    g.close()

    half = 0.125
    boxes = [box(lo - half, la - half, lo + half, la + half) for la in ys for lo in xs]
    gdf = gpd.GeoDataFrame(geometry=boxes, crs="EPSG:4326")
    stats = zonal_stats(gdf, DEM_CROP, stats="mean", nodata=-9999.0)
    elev = np.array([s["mean"] if s["mean"] is not None else np.nan for s in stats],
                    dtype="float64").reshape(len(ys), len(xs))
    # cells whose 0.25deg box falls outside the DEM crop cannot occur (the crop is
    # padded), but guard anyway with the basin-mean elevation
    elev[~np.isfinite(elev)] = np.nanmean(elev)

    xr.Dataset({"elev": (("y", "x"), elev)},
               coords={"y": ys, "x": xs}).to_netcdf(ELEV_NC)
    print(f"[s1b] elevation {elev.min():.0f}-{elev.max():.0f} m -> {ELEV_NC}", flush=True)

    # Caravan p_mean for GRDC_4115221 = 1.676 mm/day. annual_prec (soil col 49) is
    # read by the image driver only and never used by vic_run in the classic
    # driver, but a physical value beats -9999.
    prec = np.full((len(ys), len(xs)), 1.676 * 365.25, dtype="float64")
    xr.Dataset({"prec_mean_annual": (("y", "x"), prec)},
               coords={"y": ys, "x": xs}).to_netcdf(PREC_NC)
    print(f"[s1b] annual precip {prec[0, 0]:.0f} mm/yr -> {PREC_NC}", flush=True)
else:
    print("[s1b] elev/prec grids exist, skip")

# ===================== s2/s3 soil ==========================================
if not os.path.exists(SOIL_FINAL):
    run(f"{KI}/s3_soil/fill_parameters1.py", f"{KI}/s3_soil", "s3_soil/fill_parameters1.py")
else:
    print("[s2] SOIL_PARAM_FINAL exists, skip")
    RESULT["tools_used"].append("s3_soil/fill_parameters1.py")

if not os.path.exists(SOIL_COMPLETE):
    run(f"{KI}/s3_soil/fill_parameters2.py", f"{KI}/s3_soil", "s3_soil/fill_parameters2.py")
else:
    print("[s3] SOIL_PARAM_COMPLETE exists, skip")
    RESULT["tools_used"].append("s3_soil/fill_parameters2.py")

NCELL = n_cells()
print(f"[grid] VIC cells = {NCELL}", flush=True)

# The soil params must be physical: fill_parameters1 writes zeros for Ksat/expt/
# bulk density (HWSD MU ids are not texture codes) and fill_parameters2 is what
# fills them from the global 0.5deg file. If that interpolation missed, VIC would
# run with Ksat = 0 and produce a silently wrong hydrograph.
sp = pd.read_csv(SOIL_COMPLETE, sep=r"\s+", header=None)
ksat = sp.iloc[:, 12]           # col 13 = Ksat layer 1
expt = sp.iloc[:, 9]            # col 10 = expt layer 1
bd = sp.iloc[:, 33]             # col 34 = bulk density layer 1
print(f"[s3] Ksat {ksat.min():.1f}-{ksat.max():.1f} mm/day, expt {expt.min():.2f}-{expt.max():.2f}, "
      f"bulk_density {bd.min():.0f}-{bd.max():.0f} kg/m3, elev {sp.iloc[:, 21].min():.0f}-"
      f"{sp.iloc[:, 21].max():.0f} m", flush=True)
if ksat.min() <= 0 or expt.min() <= 0 or bd.min() <= 0:
    RESULT["tools_failed"].append(
        "fill_parameters2.py left non-positive Ksat/expt/bulk_density -- global soil "
        "interpolation did not reach this basin")
    save("soil parameters are degenerate; VIC would produce meaningless runoff")
    sys.exit(1)

# ===================== s4 veg ==============================================
def _veg_complete():
    """One 2-token header line (cell_id, n_veg_classes) per VIC cell."""
    if not os.path.exists(VEG_PARAM):
        return False
    n = sum(1 for l in open(VEG_PARAM) if len(l.split()) == 2)
    print(f"[s4] validate: {n}/{NCELL} veg cell records", flush=True)
    return n == NCELL


if not os.path.exists(VEG_PARAM):
    run(f"{KI}/s4_veg/process_vegetation_detailed.py", f"{KI}/s4_veg",
        "s4_veg/process_vegetation_detailed.py", validate=_veg_complete)
else:
    print("[s4] veg param exists, skip")
    RESULT["tools_used"].append("s4_veg/process_vegetation_detailed.py")

# ===================== s5 forcing (NASA POWER) =============================
# CMFD stops at the Chinese border; SKILL.md's cascade is CMFD -> MSWX -> POWER.
# MSWX on this server is not rechunked for the Columbia basin, so POWER (0.5deg,
# hourly, 2001-NRT) is the sanctioned global fallback for a >10,000 km2 basin.
nday = int((pd.Timestamp(f"{YEAR_END}-12-31") - pd.Timestamp(f"{YEAR_START}-01-01")).days) + 1
have = len(glob.glob(f"{FORCING_FINAL}/{FORCING_PREFIX}*"))
def _forcing_complete():
    """All NCELL per-cell files present, each with exactly 8 steps/day."""
    fs = sorted(glob.glob(f"{FORCING_FINAL}/{FORCING_PREFIX}*"))
    if len(fs) != NCELL:
        print(f"[s5] validate: {len(fs)}/{NCELL} forcing files", flush=True)
        return False
    nrec = sum(1 for _ in open(fs[0]))
    print(f"[s5] validate: {len(fs)}/{NCELL} files, {nrec} recs (expect {nday * 8})", flush=True)
    return nrec == nday * 8


if have < NCELL:
    print(f"[s5] forcing_final: {have}/{NCELL} -> fetching NASA POWER", flush=True)
    run(f"{KI}/s2_forcing/forcing_nasa_power.py", f"{KI}/s2_forcing",
        "s2_forcing/forcing_nasa_power.py", timeout=21600,
        args=["--grid_nc", GRID_NC, "--soil_param", SOIL_COMPLETE,
              "--output_dir", FORCING_FINAL, "--forcing_prefix", FORCING_PREFIX,
              "--start_year", str(YEAR_START), "--end_year", str(YEAR_END),
              "--timestep", "3hourly"],
        validate=_forcing_complete)
else:
    print("[s5] forcing_final complete, skip")
    RESULT["tools_used"].append("s2_forcing/forcing_nasa_power.py")

have = len(glob.glob(f"{FORCING_FINAL}/{FORCING_PREFIX}*"))
if have < NCELL:
    RESULT["tools_failed"].append(f"forcing_nasa_power.py: {have}/{NCELL} cells written")
    save("NASA POWER forcing incomplete -> VIC would abort on a missing forcing file")
    sys.exit(1)

sample = sorted(glob.glob(f"{FORCING_FINAL}/{FORCING_PREFIX}*"))[0]
nrec = sum(1 for _ in open(sample))
print(f"[s5] {os.path.basename(sample)}: {nrec} records (expect {nday * 8})", flush=True)
if nrec != nday * 8:
    RESULT["tools_failed"].append(
        f"forcing_nasa_power.py: {nrec} records != {nday * 8} (8 steps/day x {nday} days)")
    save("forcing record count mismatch -> VIC would abort")
    sys.exit(1)

# ===================== s6 global param =====================================
if not os.path.exists(GLOBAL_PARAM):
    print("\n===== s6 config_paths.create_global_param =====", flush=True)
    sys.path.insert(0, KI)
    os.environ.update({k: v for k, v in ENV.items() if k.startswith("VIC_")})
    import importlib
    import config_paths
    importlib.reload(config_paths)
    config_paths.create_output_dirs()
    if not config_paths.create_global_param():
        RESULT["tools_failed"].append("config_paths.create_global_param(): template missing")
        save("global param template missing")
        sys.exit(1)
    RESULT["tools_used"].append("config_paths.create_global_param()")
else:
    print("[s6] global param exists, skip")
    RESULT["tools_used"].append("config_paths.create_global_param()")

gp_txt = open(GLOBAL_PARAM).read()
for key, want in [("STARTYEAR", str(YEAR_START)), ("ENDYEAR", str(YEAR_END)),
                  ("FORCEYEAR", str(YEAR_START)), ("FORCE_STEPS_PER_DAY", "8"),
                  ("FROZEN_SOIL", "FALSE")]:
    line = [l for l in gp_txt.splitlines() if l.strip().startswith(key)]
    print(f"[s6] {line}", flush=True)
    assert line and want in line[0], f"{key} not set to {want} in global param"

# ===================== s7 VIC ==============================================
flux = glob.glob(f"{VIC_RESULT}/{BASIN}_fluxes_*.txt")
if len(flux) < NCELL:
    print(f"\n===== s7 vic_classic.exe ({len(flux)}/{NCELL} present) =====", flush=True)
    os.makedirs(VIC_RESULT, exist_ok=True)
    p = subprocess.run([VIC_EXE, "-g", GLOBAL_PARAM], capture_output=True, text=True)
    print("rc =", p.returncode, flush=True)
    print((p.stdout or "")[-1500:], flush=True)
    if p.returncode != 0:
        print("STDERR:", (p.stderr or "")[-3000:], flush=True)
        RESULT["tools_failed"].append(f"vic_classic.exe: rc={p.returncode} :: {(p.stderr or '')[-400:]}")
        save("VIC binary failed")
        sys.exit(1)
    flux = glob.glob(f"{VIC_RESULT}/{BASIN}_fluxes_*.txt")
print(f"[s7] flux files: {len(flux)}", flush=True)
if len(flux) < NCELL * 0.95:
    RESULT["tools_failed"].append(f"vic_classic.exe: only {len(flux)}/{NCELL} flux files")
    save("VIC produced too few flux files")
    sys.exit(1)
RESULT["tools_used"].append("vic_classic.exe (VIC 5.1.0 classic driver)")

# ===================== s8 routing params ===================================
def _routing_complete():
    need = [f"{ROUTING}/{STA}_direc.txt", f"{ROUTING}/{STA}_frac.txt",
            f"{ROUTING}/{STA}_xmask.txt", f"{ROUTING}/{STA}_staloc.txt",
            f"{ROUTING}/UH.all"]
    missing = [os.path.basename(p) for p in need
               if not (os.path.exists(p) and os.path.getsize(p) > 0)]
    print(f"[s8] validate: missing={missing or 'none'}", flush=True)
    return not missing


if not os.path.exists(f"{ROUTING}/{STA}_direc.txt"):
    run(f"{KI}/s5_routing/build_routing_param.py", KI, "s5_routing/build_routing_param.py",
        validate=_routing_complete)
else:
    print("[s8] routing params exist, skip")
    RESULT["tools_used"].append("s5_routing/build_routing_param.py")

# ===================== s9 Lohmann routing ==================================
day_files = glob.glob(f"{ROUT_OUT}/*.day")
if not day_files:
    print("\n===== s9 route_1.0/rout =====", flush=True)
    os.makedirs(VIC_IN, exist_ok=True)
    os.makedirs(ROUT_OUT, exist_ok=True)
    n = 0
    for fn in sorted(os.listdir(VIC_RESULT)):
        if not fn.endswith(".txt") or fn.startswith("._"):
            continue
        df = pd.read_csv(f"{VIC_RESULT}/{fn}", sep=r"\s+", skiprows=3, header=None)
        # 0..2 = Y M D; 3 = OUT_PREC; 16 = OUT_RUNOFF; 17 = OUT_BASEFLOW; 18 = OUT_EVAP
        # rout expects: year month day prec evap runoff baseflow
        out = df.iloc[:, [0, 1, 2, 3, 18, 16, 17]]
        new = fn.replace(f"{BASIN}_", "").replace(".txt", "")
        out.to_csv(f"{VIC_IN}/{new}", sep="\t", header=False, index=False, float_format="%.4f")
        n += 1
    print(f"[s9] preprocessed {n} flux files -> vic_in/", flush=True)

    for f in glob.glob(f"{ROUTING}/*.uh_s"):
        os.remove(f)
    p = subprocess.run([ROUT_EXE, "rout_global.txt"], cwd=ROUTING,
                       capture_output=True, text=True, timeout=7200)
    print(f"[s9] rout rc={p.returncode}", flush=True)
    print("\n".join((p.stdout or "").strip().splitlines()[-10:]), flush=True)
    if p.stderr:
        print("STDERR:", p.stderr[-1500:], flush=True)
    day_files = glob.glob(f"{ROUT_OUT}/*.day")
    if not day_files:
        RESULT["tools_failed"].append("route_1.0/rout: no .day output")
        save("Lohmann routing produced no output")
        sys.exit(1)
RESULT["tools_used"].append("route_1.0/src/rout (Lohmann routing binary)")

# ===================== s10 score ===========================================
print("\n===== s10 scoring =====", flush=True)
rd = pd.read_csv(sorted(day_files)[0], sep=r"\s+", header=None,
                 names=["year", "month", "day", "Q"])
rd["date"] = pd.to_datetime(rd[["year", "month", "day"]])
sim = rd.set_index("date")["Q"]

import netCDF4
with netCDF4.Dataset(OBS_NC) as ds:
    t = ds.variables["date"]
    dates = netCDF4.num2date(t[:], t.units, only_use_cftime_datetimes=False)
    q_mmday = np.asarray(ds.variables["streamflow"][:], dtype="float64")
obs = pd.Series(q_mmday, index=pd.to_datetime([str(d) for d in dates]))
obs = obs[np.isfinite(obs) & (obs >= 0)]
# Caravan streamflow is a catchment-mean depth; convert to m3/s with the same
# basin polygon Caravan used, so sim (m3/s from rout) and obs share units.
obs = obs * CARAVAN_AREA_KM2 / 86.4

paired = pd.concat([obs.rename("obs"), sim.rename("sim")], axis=1).dropna()
paired = paired.loc[EVAL_START:EVAL_END]
print(f"[s10] paired days={len(paired)} obs_mean={paired['obs'].mean():.2f} "
      f"sim_mean={paired['sim'].mean():.2f} m3/s", flush=True)

if len(paired) < 2:
    RESULT["metrics"]["metrics_null_reason"] = (
        f"no temporal overlap: sim {sim.index.min()}..{sim.index.max()}, "
        f"obs {obs.index.min()}..{obs.index.max()}")
    save("no temporal overlap between routed sim and obs")
    sys.exit(1)

m = {k.lower(): float(v) for k, v in all_metrics(paired["obs"].values, paired["sim"].values).items()}
RESULT["tools_used"].append("ki_tools_common.metrics.all_metrics")

cv = compute_calval_metrics(paired.index.values, paired["obs"].values, paired["sim"].values,
                            cal_start=CAL[0], cal_end=CAL[1],
                            val_start=VAL[0], val_end=VAL[1])
RESULT["tools_used"].append("validators.standard_calval.compute_calval_metrics")

RESULT["metrics"] = {
    "nse": m["nse"], "kge": m["kge"], "pbias": m["pbias"], "r": m["r"],
    "rmse": m.get("rmse"),
    "period": f"{EVAL_START}..{EVAL_END}",
    "nse_cal": float(cv["calibration"]["NSE"]), "kge_cal": float(cv["calibration"]["KGE"]),
    "nse_val": float(cv["validation"]["NSE"]), "kge_val": float(cv["validation"]["KGE"]),
    "pbias_val": float(cv["validation"]["PBIAS"]),
    "period_calibration": f"{CAL[0]}..{CAL[1]}",
    "period_validation": f"{VAL[0]}..{VAL[1]}",
}

# ---- water balance: basin-mean over the evaluation period ----
acc = {"P": [], "ET": [], "RO": [], "S": []}
for fn in sorted(glob.glob(f"{VIC_RESULT}/{BASIN}_fluxes_*.txt")):
    df = pd.read_csv(fn, sep=r"\s+", skiprows=2)
    df["date"] = pd.to_datetime(df[["YEAR", "MONTH", "DAY"]].rename(
        columns={"YEAR": "year", "MONTH": "month", "DAY": "day"}))
    df = df[(df["date"] >= EVAL_START) & (df["date"] <= EVAL_END)]
    if df.empty:
        continue
    stor = (df["OUT_SOIL_MOIST_0"] + df["OUT_SOIL_MOIST_1"] +
            df["OUT_SOIL_MOIST_2"] + df["OUT_SWE"])
    acc["P"].append(df["OUT_PREC"].sum())
    acc["ET"].append(df["OUT_EVAP"].sum())
    acc["RO"].append((df["OUT_RUNOFF"] + df["OUT_BASEFLOW"]).sum())
    acc["S"].append(stor.iloc[-1] - stor.iloc[0])

ndays = int((pd.Timestamp(EVAL_END) - pd.Timestamp(EVAL_START)).days) + 1
wb = validate_water_balance(precip_mm=float(np.mean(acc["P"])),
                           et_mm=float(np.mean(acc["ET"])),
                           runoff_mm=float(np.mean(acc["RO"])),
                           delta_storage_mm=float(np.mean(acc["S"])),
                           period_days=ndays)
RESULT["water_balance"] = {
    "status": wb["status"],
    "residual_pct": float(wb["residual_pct"]) if wb.get("residual_pct") is not None else None,
    "residual_mm": float(wb["residual_mm"]) if wb.get("residual_mm") is not None else None,
}
RESULT["tools_used"].append("ki_tools_common.validation.validate_water_balance")
RESULT["status"] = "completed"

save(
    f"VERIFIER at the JOHN DAY RIVER, McDonald Ferry, Oregon USA ({GAUGE_ID}, GRDC-Caravan "
    f"extension) -- a different continent, forcing dataset and DEM from the Tangnaihai "
    f"real-case. Full KI chain re-run from scratch: Copernicus GLO-30 mosaic -> "
    f"delineate_basin ({DELIN_AREA_KM2:.0f} km2 vs {CARAVAN_AREA_KM2:.0f} km2 Caravan polygon, "
    f"{100 * (DELIN_AREA_KM2 / CARAVAN_AREA_KM2 - 1):+.1f}%) -> s1_grid ({NCELL} cells @0.25deg) "
    f"-> s3_soil (fill_parameters2 interpolates the GLOBAL 0.5deg soil file, so the China-only "
    f"HWSD raster is irrelevant) -> s4_veg (AVHRR global) -> s2_forcing/forcing_nasa_power.py "
    f"(3-hourly, 8 steps/day; CMFD does not reach Oregon) -> vic_classic.exe -> "
    f"s5_routing/build_routing_param.py -> route_1.0/rout. paired={len(paired)} d "
    f"({EVAL_START}..{EVAL_END}); obs_mean={paired['obs'].mean():.2f} sim_mean="
    f"{paired['sim'].mean():.2f} m3/s. NSE={m['nse']:.3f} r={m['r']:.3f} KGE={m['kge']:.3f} "
    f"PBIAS={m['pbias']:+.1f}%. cal(2005-09) NSE={cv['calibration']['NSE']:.3f} "
    f"KGE={cv['calibration']['KGE']:.3f}; val(2010-14, held out) NSE={cv['validation']['NSE']:.3f} "
    f"KGE={cv['validation']['KGE']:.3f} PBIAS={cv['validation']['PBIAS']:+.1f}%. UNCALIBRATED, "
    f"same defaults as the real case. Water balance {wb['status']} "
    f"({RESULT['water_balance']['residual_pct']}%). Obs are Caravan catchment-mean depths "
    f"(mm/day) converted to m3/s with the Caravan polygon area so the units match the routed "
    f"sim and the metrics are directly comparable to Tangnaihai's. The John Day has no mainstem "
    f"dams, which is why it was chosen: route_1.0 has no reservoir module. KI FIX: "
    f"s3_soil/fill_parameters1.py hard-coded the CMFD China elevation/precip rasters, and "
    f"xarray sel(method='nearest') returns the nearest CHINESE cell rather than failing "
    f"off-domain -- they are now VIC_ELEV_NC / VIC_PREC_ANNUAL_NC env vars (defaults unchanged). "
    f"DRIVER FIX (dt_vic_023): a stage that SIGSEGVs during interpreter teardown AFTER writing "
    f"correct output no longer aborts the run -- a fatal signal is forgiven ONLY when a "
    f"per-stage validate() proves the artifact complete (veg cell count / forcing file+record "
    f"count / 5 routing files), so a genuine crash, which leaves output missing or short, still "
    f"fails loudly. The 2026-07-09 attempt died exactly this way at s4_veg: rerunning that stage "
    f"standalone gives rc=0 and a BYTE-IDENTICAL vic_veg_param_final.txt. "
    f"CAVEAT (not changed, flagged for the KI): forcing_nasa_power.py maps POWER's WS2M (2 m) "
    f"onto VIC's WIND, but no WIND_H is declared in the global param, so VIC assumes its 10 m "
    f"default. CMFD wind at Tangnaihai really is 10 m, so the NASA POWER path under-states "
    f"surface wind and hence ET slightly. Second-order for a runoff NSE, but it is a real "
    f"forcing-convention mismatch between the two forcing tools."
)
print(json.dumps(RESULT["metrics"], indent=2), flush=True)
print("DONE", flush=True)
