#!/usr/bin/env python3
"""
CWatM verifier runner — daily discharge at JAMES RIVER, CARTERSVILLE, VA,
GRDC 4147330 (Caravan / GRDC-Caravan Extension), 37.6729N -78.0854W,
drainage area 16,228 km2.

THIRD consistency-check location for CWatM. The real-case was 九江 / Jiujiang
(1.5 M km2 monsoon lowland Yangtze main stem); verify_2 #1 was Zhimenda / upper
Yangtze alpine headwater. This one is the temperate-maritime opposite drawn from
the GLOBAL Caravan-Extension pool: a humid, forested (79% forest by ESA-CCI-LC)
Appalachian-Piedmont rainfall-runoff basin with ~0 snow and minimal regulation.

Because no China-only CMFD covers the US, forcing here is built from NASA POWER
daily (global, 1981+, 0.5deg), fetched per active grid cell through the KI's own
`ki_tools_common.load_forcing.load_daily_forcing('nasa_power', ...)` loader and
written into the exact CWatM NetCDF layout that convert_forcing_to_cwatm emits.
Everything else is the SAME KI tool chain:

  s2  tools/build_cwatm_static.py     MERIT-Hydro + ESA-CCI-LC(global) -> static grid
      tools/convert_soil_to_cwatm.py  HWSD -> van Genuchten stack
      tools/build_cwatm_ancillary.py  crop coefficients, intercept caps, dzRel
  s1  NASA POWER daily -> CWatM forcing NetCDFs (this file; resumable per cell)
  s3  tools/run_cwatm_wrapper.py       run the real CWatM (source/repo/run_cwatm.py)
  s4  parse the TSS csv               -> sim series
      ki_tools_common.metrics.all_metrics NSE / KGE / R / PBIAS / RMSE

Resumable: every stage checks for its own outputs and skips if present; NASA
POWER cells are cached to forcing/nasa_cache/*.npz. Writes the KDT verifier
result object to detached/verify_2/result.json.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/ki_tools_common")

ROOT = "/mnt/disk1/Hydrocraft_server/models/CWatM"
KI = f"{ROOT}/knowledge_infrastructure"
TOOLS = f"{KI}/tools"
CASE = f"{ROOT}/cwatm_james_cartersville"
CWATM_DIR = f"{ROOT}/source/repo"
PY = "/mnt/disk1/Hydrocraft_server/python_env/bin/python"
STATE = f"{ROOT}/detached/verify_2"

OBS_NC = ("/mnt/datasets/observed_data/dischargeandwatershed/"
          "GRDC-Caravan-extension-nc/timeseries/netcdf/grdc/GRDC_4147330.nc")
LOCATION = ("James River at Cartersville, VA (Appalachian Piedmont, humid temperate) "
            "— GRDC 4147330, GRDC-Caravan Extension")
OBS_SOURCE = ("GRDC-Caravan Extension (5,357 global gauges + basin shapes); "
              "station GRDC_4147330 JAMES RIVER, CARTERSVILLE, VA, 16,228 km2; "
              "variable discharge (Caravan `streamflow`, mm/day -> m3/s via drainage area)")

GAUGE_LON, GAUGE_LAT = -78.0854, 37.6729
EXPECTED_AREA_KM2 = 16228.45
OBS_AREA_KM2 = 16228.45
BBOX = ["37.0", "39.0", "-81.0", "-77.5"]
RES = 0.5
SNAP_WINDOW_PX = 60          # validated inline: MERIT upa at outlet 16,294 km2 (+0.41%)
GAUGE_CELL_CENTRE = (-78.25, 37.75)   # from static_meta.json (Gauges pit cell)

SPINUP_START, RUN_START, RUN_END = "1990-01-01", "1993-01-01", "2012-12-31"
CAL = ("1993-01-01", "2002-12-31")
VAL = ("2003-01-01", "2012-12-31")

MERIT_DIR = f"{CASE}/merit_tiles"    # pre-extracted n35w080/n35w085 dir,upa,elv,wth
ESA_LC = "/mnt/datasets/vegetation/ESA_CCI_LC_global/ESA_CCI_LC_global_2010_01deg.tif"
HWSD_DIR = "/mnt/disk1/Hydrocraft_server/data/soil/HWSD_RASTER"

ENV = dict(os.environ, LD_PRELOAD="/lib/x86_64-linux-gnu/libstdc++.so.6")

MAX_ITER = int(os.environ.get("CWATM_MAX_ITER", "3"))
PBIAS_TOL = 12.0

FORCING_VARS = ["precipitation", "tavg", "qair", "psurf", "wind", "rsds", "rsdl", "tmin", "tmax"]
N_DAYS = (pd.Timestamp(RUN_END) - pd.Timestamp(SPINUP_START)).days + 1

TOOLS_USED, TOOLS_FAILED = [], []


def log(*a):
    print(f"[{datetime.now():%H:%M:%S}]", *a, flush=True)


def sh(cmd, tool):
    log("RUN", " ".join(str(c) for c in cmd))
    p = subprocess.run([str(c) for c in cmd], env=ENV, text=True, capture_output=True)
    if p.returncode != 0:
        log("STDOUT tail:", p.stdout[-3000:])
        log("STDERR tail:", p.stderr[-3000:])
        if tool not in TOOLS_FAILED:
            TOOLS_FAILED.append(tool)
        raise SystemExit(f"command failed ({p.returncode}): {cmd[0]}")
    if tool not in TOOLS_USED:
        TOOLS_USED.append(tool)
    return p.stdout


# ------------------------------------------------------------------ s2 static
def stage_static():
    if os.path.exists(f"{CASE}/static/static_meta.json"):
        log("s2 static: complete, skipping")
        TOOLS_USED.append("build_cwatm_static.py")
        return
    sh([PY, f"{TOOLS}/build_cwatm_static.py",
        "--gauge_lon", GAUGE_LON, "--gauge_lat", GAUGE_LAT,
        "--bbox", *BBOX, "--res", RES,
        "--merit_dir", MERIT_DIR, "--esa_lc", ESA_LC,
        "--expected_area_km2", EXPECTED_AREA_KM2,
        "--snap_window_px", SNAP_WINDOW_PX,
        "--out_dir", f"{CASE}/static"], "build_cwatm_static.py")


def stage_soil():
    if os.path.exists(f"{CASE}/soil/percolationImp.nc"):
        log("s2 soil: complete, skipping")
        TOOLS_USED.append("convert_soil_to_cwatm.py")
        return
    sh([PY, f"{TOOLS}/convert_soil_to_cwatm.py", "--source", "hwsd",
        "--input_dir", HWSD_DIR,
        "--bbox", *BBOX, "--resolution", RES, "--output_dir", f"{CASE}/soil"],
       "convert_soil_to_cwatm.py")


def stage_ancillary():
    if os.path.exists(f"{CASE}/ancillary/relativeElevation.nc"):
        log("s2 ancillary: complete, skipping")
        TOOLS_USED.append("build_cwatm_ancillary.py")
        return
    sh([PY, f"{TOOLS}/build_cwatm_ancillary.py",
        "--static_dir", f"{CASE}/static", "--output_dir", f"{CASE}/ancillary"],
       "build_cwatm_ancillary.py")


# ---------------------------------------------------------------- s1 forcing (NASA POWER)
import netCDF4 as nc  # noqa: E402


def _write_cwatm_nc(path, var, data, times, lats, lons, units, long_name):
    """Mirror tools/convert_forcing_to_cwatm.write_cwatm_netcdf exactly."""
    ds = nc.Dataset(path, "w", format="NETCDF4")
    ds.createDimension("time", None)
    ds.createDimension("lat", len(lats))
    ds.createDimension("lon", len(lons))
    tv = ds.createVariable("time", "f8", ("time",))
    tv.units = f"days since {pd.Timestamp(times[0]).strftime('%Y-%m-%d')}"
    tv.calendar = "standard"
    tv.standard_name = "time"
    la = ds.createVariable("lat", "f8", ("lat",)); la.units = "degrees_north"
    la.standard_name = "latitude"; la[:] = lats
    lo = ds.createVariable("lon", "f8", ("lon",)); lo.units = "degrees_east"
    lo.standard_name = "longitude"; lo[:] = lons
    ref = pd.Timestamp(times[0])
    tv[:] = np.array([(pd.Timestamp(t) - ref).total_seconds() / 86400.0 for t in times])
    dv = ds.createVariable(var, "f4", ("time", "lat", "lon"),
                           fill_value=-9999.0, zlib=True, complevel=4)
    dv.units = units
    dv.long_name = long_name
    dv[:] = np.asarray(data, dtype=np.float32)
    ds.Conventions = "CF-1.6"
    ds.title = f"CWatM forcing: {var} (NASA POWER daily)"
    ds.close()


def _drop_truncated_forcing(out):
    for v in FORCING_VARS:
        p = f"{out}/{v}.nc"
        if not os.path.exists(p):
            continue
        try:
            ds = nc.Dataset(p)
            n = ds.dimensions["time"].size
            ok = v in ds.variables and n == N_DAYS
            ds.close()
        except Exception:
            ok = False
        if not ok:
            log(f"s1 forcing: {v}.nc truncated/unreadable ({n if 'n' in dir() else '?'} vs {N_DAYS}) -> removing")
            os.remove(p)


def _fetch_cell(lat, lon, y0, y1, cache):
    """NASA POWER daily for one cell, cached to npz; reindexed to master days."""
    key = f"cell_{lat:+.3f}_{lon:+.3f}.npz".replace(" ", "")
    cpath = os.path.join(cache, key)
    master = pd.date_range(SPINUP_START, RUN_END, freq="D")
    if os.path.exists(cpath):
        z = np.load(cpath, allow_pickle=True)
        return {k: z[k] for k in z.files}
    from ki_tools_common.load_forcing import load_daily_forcing
    d = load_daily_forcing("nasa_power", float(lat), float(lon), y0, y1)
    idx = pd.to_datetime(d["dates"])
    out = {}
    src = {
        "precipitation": np.maximum(np.asarray(d["precip_mm"], float), 0.0) / 86400.0,  # mm/day->kg/m2/s
        "tavg": np.asarray(d["temp_mean_c"], float) + 273.15,
        "tmin": np.asarray(d["temp_min_c"], float) + 273.15,
        "tmax": np.asarray(d["temp_max_c"], float) + 273.15,
        "psurf": np.asarray(d["pres_pa"], float),
        "qair": np.asarray(d["shum_kgkg"], float),
        "wind": np.asarray(d["wind_ms"], float),
        "rsds": np.maximum(np.asarray(d["srad_wm2"], float), 0.0),
        "rsdl": np.asarray(d["lrad_wm2"], float),
    }
    for v, arr in src.items():
        s = pd.Series(arr, index=idx).reindex(master)
        s = s.interpolate("time").ffill().bfill()
        out[v] = s.to_numpy(dtype=np.float32)
    np.savez_compressed(cpath, **out)
    return out


def stage_forcing():
    out = f"{CASE}/forcing"
    cache = f"{out}/nasa_cache"
    os.makedirs(cache, exist_ok=True)
    _drop_truncated_forcing(out)
    if all(os.path.exists(f"{out}/{v}.nc") for v in FORCING_VARS):
        log("s1 forcing: complete, skipping")
        TOOLS_USED.append("nasa_power_forcing_builder (ki_tools_common.load_forcing)")
        return

    m = nc.Dataset(f"{CASE}/static/MaskMap.nc")
    lats = np.array(m["lat"][:]); lons = np.array(m["lon"][:])
    mask = np.array(m["MaskMap"][:]) == 1
    m.close()
    nt = len(pd.date_range(SPINUP_START, RUN_END, freq="D"))
    times = pd.date_range(SPINUP_START, RUN_END, freq="D")
    y0, y1 = pd.Timestamp(SPINUP_START).year, pd.Timestamp(RUN_END).year

    active = [(i, j) for i in range(len(lats)) for j in range(len(lons)) if mask[i, j]]
    log(f"s1 forcing: {len(active)} active cells, NASA POWER daily {y0}-{y1} ({nt} days each)")

    cells = {}
    for n, (i, j) in enumerate(active):
        log(f"  cell {n+1}/{len(active)} (lat {lats[i]:.2f}, lon {lons[j]:.2f})")
        cells[(i, j)] = _fetch_cell(lats[i], lons[j], y0, y1, cache)

    # basin-mean default for the (masked-out) inactive cells
    default = {v: np.mean([cells[k][v] for k in active], axis=0) for v in FORCING_VARS}

    meta = {
        "precipitation": ("kg m-2 s-1", "Precipitation flux"),
        "tavg": ("K", "Average air temperature"),
        "tmin": ("K", "Minimum air temperature"),
        "tmax": ("K", "Maximum air temperature"),
        "psurf": ("Pa", "Surface air pressure"),
        "qair": ("kg kg-1", "Specific humidity"),
        "wind": ("m s-1", "Wind speed at 10 m"),
        "rsds": ("W m-2", "Surface downwelling shortwave radiation"),
        "rsdl": ("W m-2", "Surface downwelling longwave radiation"),
    }
    for v in FORCING_VARS:
        arr = np.empty((nt, len(lats), len(lons)), dtype=np.float32)
        arr[:] = default[v][:, None, None]
        for (i, j) in active:
            arr[:, i, j] = cells[(i, j)][v]
        _write_cwatm_nc(f"{out}/{v}.nc", v, arr, times, lats, lons, *meta[v])
        log(f"  wrote {v}.nc  mean={float(np.nanmean(arr)):.4g} {meta[v][0]}")
    TOOLS_USED.append("nasa_power_forcing_builder (ki_tools_common.load_forcing)")
    missing = [v for v in FORCING_VARS if not os.path.exists(f"{out}/{v}.nc")]
    if missing:
        raise SystemExit(f"forcing incomplete: {missing}")


# ------------------------------------------------------- grid sanity preflight
def check_grids():
    ref = nc.Dataset(f"{CASE}/static/MaskMap.nc")
    rlat, rlon = np.array(ref["lat"][:]), np.array(ref["lon"][:])
    ref.close()
    for d, files in ((f"{CASE}/forcing", [f"{v}.nc" for v in FORCING_VARS]),
                     (f"{CASE}/soil", ["KSat1.nc", "thetas1.nc", "percolationImp.nc"]),
                     (f"{CASE}/ancillary", ["relativeElevation.nc"])):
        for f in files:
            ds = nc.Dataset(f"{d}/{f}")
            la, lo = np.array(ds["lat"][:]), np.array(ds["lon"][:])
            ds.close()
            if la.shape != rlat.shape or lo.shape != rlon.shape:
                raise SystemExit(f"grid mismatch {f}: {la.shape},{lo.shape} vs {rlat.shape},{rlon.shape}")
            if not (np.allclose(la, rlat, atol=1e-3) and np.allclose(lo, rlon, atol=1e-3)):
                raise SystemExit(f"grid coords differ for {f}")
    log("grid preflight: all inputs share the static grid")


def forcing_preflight():
    fails, warns = [], []
    try:
        mask = np.array(nc.Dataset(f"{CASE}/static/MaskMap.nc")["MaskMap"][:]) == 1
        def bmean(var, name):
            a = np.array(nc.Dataset(f"{CASE}/forcing/{var}.nc")[var][:])
            return float(np.nanmean(a[:, mask]))
        pm = bmean("precipitation", "p")
        p_mmyr = pm * 86400 * 365.25
        if not (200 < p_mmyr < 3000):
            fails.append(f"precip {p_mmyr:.0f} mm/yr outside 200-3000")
        tm = bmean("tavg", "t")
        if tm < 150:
            fails.append(f"tavg {tm:.1f} looks like Celsius but TemperatureInKelvin=True")
        psm = bmean("psurf", "ps")
        if psm < 10000:
            fails.append(f"psurf {psm:.0f} looks like hPa/kPa not Pa")
        sw = bmean("rsds", "sw"); lw = bmean("rsdl", "lw"); wd = bmean("wind", "w")
        warns.append(f"basin-mean precip {p_mmyr:.0f} mm/yr, tavg {tm:.1f} K, psurf {psm:.0f} Pa, "
                     f"SWdown {sw:.0f} W/m2, LWdown {lw:.0f} W/m2, wind {wd:.2f} m/s")
    except Exception as e:
        warns.append(f"forcing preflight incomplete: {e}")
    return {"all_pass": not fails, "source": "NASA POWER daily 0.5deg (per active cell)",
            "failures": fails, "warnings": warns}


# ------------------------------------------------------------------- settings
SETTINGS_TEMPLATE = f"""# CWatM Settings — James River at Cartersville, VA (GRDC 4147330), 1990-2012
# GRDC-Caravan Extension; 37.6729N -78.0854W; catchment 16,228 km2
# build_cwatm_static.py snapped to MERIT upa 16,294 km2 (+0.41%); coarse mask 7 cells
# Grid: 4 x 7 cells, 0.5deg, 37.0-39.0N, 81.0-77.5W ; 7 active cells
# Forcing: NASA POWER daily 0.5deg per cell (global); Penman-Monteith
# Humid temperate Appalachian-Piedmont, 79% forest, ~0 snow, minimal regulation.

[OPTIONS]
TemperatureInKelvin = True
gridSizeUserDefined = True
calc_evaporation = True
includeIrrigation = True
includeWaterDemand = False
usingAllocSegments = False
limitAbstraction = False
calc_environflow = False
preferentialFlow = False
CapillarRise = True
includeRunoffConcentration = True
includeWaterBodies = False
includeRouting = True
inflow = False
writeNetcdfStack = True
reportMap = True
reportTss = True
calcWaterBalance = False
sumWaterBalance = False
PCRaster = False
staticLandCoverMaps = True

[FILE_PATHS]
PathRoot  = {CASE}
PathOut   = $(PathRoot)/output
PathMaps  = $(PathRoot)/static
PathSoil  = $(PathRoot)/soil
PathMeteo = $(PathRoot)/forcing
PathAnc   = $(PathRoot)/ancillary

[NETCDF_ATTRIBUTES]
institution = HydroCraft / IIASA
title       = CWatM James Cartersville 1990-2012 (NASA POWER, 0.5deg)
metaNetcdfFile = {CWATM_DIR}/cwatm/metaNetcdf.xml

[MASK_OUTLET]
MaskMap = $(FILE_PATHS:PathMaps)/MaskMap.nc
Gauges = {GAUGE_CELL_CENTRE[0]} {GAUGE_CELL_CENTRE[1]}
GaugesLocal = True

[TIME-RELATED_CONSTANTS]
StepStart = 1/1/1990
SpinUp    = 1/1/1993
StepEnd   = 31/12/2012

[INITITIAL CONDITIONS]
load_initial = False
save_initial = False

[CALIBRATION]
SnowMeltCoef          = 0.0040
crop_correct          = 1.00
soildepth_factor      = 1.00
preferentialFlowConstant = 4.0
arnoBeta_add          = 0.10
factor_interflow      = 1.0
recessionCoeff_factor = 1.0
runoffConc_factor     = 1.0
manningsN             = 1.0
lakeEvaFactor         = 1.0
lakeAFactor           = 0.33
normalStorageLimit    = 0.44

[TOPOP]
Ldd          = $(FILE_PATHS:PathMaps)/Ldd.nc
ElevationStD = $(FILE_PATHS:PathMaps)/ElevationStD.nc
CellArea     = $(FILE_PATHS:PathMaps)/CellArea.nc

[METEO]
PrecipitationMaps = $(FILE_PATHS:PathMeteo)/precipitation.nc
TavgMaps          = $(FILE_PATHS:PathMeteo)/tavg.nc
precipitation_coversion = 86.4
evaporation_coversion   = 1.00

[EVAPORATION]
useHuss = True
TminMaps  = $(FILE_PATHS:PathMeteo)/tmin.nc
TmaxMaps  = $(FILE_PATHS:PathMeteo)/tmax.nc
PSurfMaps = $(FILE_PATHS:PathMeteo)/psurf.nc
QAirMaps  = $(FILE_PATHS:PathMeteo)/qair.nc
WindMaps  = $(FILE_PATHS:PathMeteo)/wind.nc
RSDSMaps  = $(FILE_PATHS:PathMeteo)/rsds.nc
RSDLMaps  = $(FILE_PATHS:PathMeteo)/rsdl.nc
albedo = False
AlbedoSoil   = 0.15
AlbedoWater  = 0.05
AlbedoCanopy = 0.23

[SNOW]
NumberSnowLayers  = 1
GlacierTransportZone = 1
TemperatureLapseRate = 0.0065
SnowFactor       = 1.0
SnowSeasonAdj    = 0.001
TempMelt         = 1.0
TempSnow         = 1.0
IceMeltCoef      = 0.007

[FROST]
SnowWaterEquivalent = 0.45
Afrost              = 0.97
Kfrost              = 0.57
FrostIndexThreshold = 56

[VEGETATION]
cropgroupnumber = 4

[SOIL]
PathTopo = $(FILE_PATHS:PathMaps)
PathSoil = $(FILE_PATHS:PathSoil)
tanslope = 0.01
relativeElevation = $(FILE_PATHS:PathAnc)/relativeElevation.nc
KSat1      = $(PathSoil)/KSat1.nc
KSat2      = $(PathSoil)/KSat2.nc
KSat3      = $(PathSoil)/KSat3.nc
alpha1     = $(PathSoil)/alpha1.nc
alpha2     = $(PathSoil)/alpha2.nc
alpha3     = $(PathSoil)/alpha3.nc
lambda1    = $(PathSoil)/lambda1.nc
lambda2    = $(PathSoil)/lambda2.nc
lambda3    = $(PathSoil)/lambda3.nc
thetas1    = $(PathSoil)/thetas1.nc
thetas2    = $(PathSoil)/thetas2.nc
thetas3    = $(PathSoil)/thetas3.nc
thetar1    = $(PathSoil)/thetar1.nc
thetar2    = $(PathSoil)/thetar2.nc
thetar3    = $(PathSoil)/thetar3.nc
percolationImp = $(PathSoil)/percolationImp.nc
maxGWCapRise     = 5.0
minCropKC        = 0.2
minTopWaterLayer = 0.0
StorDepth1 = 0.30
StorDepth2 = 1.00

[LANDCOVER]
coverTypes      = forest, grassland, irrPaddy, irrNonPaddy, sealed, water
coverTypesShort = f, g, i, n, s, w
dynamicLandcover  = False
fixLandcoverYear  = 2010
forest_fracVegCover      = $(FILE_PATHS:PathMaps)/fractionForest.nc
irrPaddy_fracVegCover    = $(FILE_PATHS:PathMaps)/fractionIrrPaddy.nc
irrNonPaddy_fracVegCover = $(FILE_PATHS:PathMaps)/fractionIrrNonPaddy.nc
sealed_fracVegCover      = $(FILE_PATHS:PathMaps)/fractionSealed.nc
water_fracVegCover       = $(FILE_PATHS:PathMaps)/fractionWater.nc

[__forest]
PathForest = $(FILE_PATHS:PathAnc)
forest_arnoBeta = 0.2
forest_KSat1   = $(FILE_PATHS:PathSoil)/KSat1.nc
forest_KSat2   = $(FILE_PATHS:PathSoil)/KSat2.nc
forest_KSat3   = $(FILE_PATHS:PathSoil)/KSat3.nc
forest_alpha1  = $(FILE_PATHS:PathSoil)/alpha1.nc
forest_alpha2  = $(FILE_PATHS:PathSoil)/alpha2.nc
forest_alpha3  = $(FILE_PATHS:PathSoil)/alpha3.nc
forest_lambda1 = $(FILE_PATHS:PathSoil)/lambda1.nc
forest_lambda2 = $(FILE_PATHS:PathSoil)/lambda2.nc
forest_lambda3 = $(FILE_PATHS:PathSoil)/lambda3.nc
forest_thetas1 = $(FILE_PATHS:PathSoil)/thetas1.nc
forest_thetas2 = $(FILE_PATHS:PathSoil)/thetas2.nc
forest_thetas3 = $(FILE_PATHS:PathSoil)/thetas3.nc
forest_thetar1 = $(FILE_PATHS:PathSoil)/thetar1.nc
forest_thetar2 = $(FILE_PATHS:PathSoil)/thetar2.nc
forest_thetar3 = $(FILE_PATHS:PathSoil)/thetar3.nc
forest_minInterceptCap = 0.001
forest_cropDeplFactor  = 0.0
forest_rootFraction1   = 0.3
forest_maxRootDepth    = 2.0
forest_cropCoefficientNC = $(PathForest)/cropCoefficientForest_10days.nc
forest_interceptCapNC    = $(PathForest)/interceptCapForest_10days.nc

[__grassland]
PathGrassland = $(FILE_PATHS:PathAnc)
grassland_arnoBeta         = 0.0
grassland_minInterceptCap  = 0.001
grassland_cropDeplFactor   = 0.0
grassland_rootFraction1    = 0.4
grassland_maxRootDepth     = 0.5
grassland_cropCoefficientNC = $(PathGrassland)/cropCoefficientGrassland_10days.nc
grassland_interceptCapNC    = $(PathGrassland)/interceptCapGrassland_10days.nc

[__irrPaddy]
PathIrrPaddy = $(FILE_PATHS:PathAnc)
irrPaddy_arnoBeta        = 0.2
irrPaddy_minInterceptCap = 0.001
irrPaddy_cropDeplFactor  = 0.0
irrPaddy_rootFraction1   = 0.4
irrPaddy_maxRootDepth    = 0.5
irrPaddy_maxtopwater     = 0.05
irrPaddy_cropCoefficientNC = $(PathIrrPaddy)/cropCoefficientirrPaddy_10days.nc

[__irrNonPaddy]
PathIrrNonPaddy = $(FILE_PATHS:PathAnc)
irrNonPaddy_arnoBeta        = 0.2
irrNonPaddy_minInterceptCap = 0.001
irrNonPaddy_cropDeplFactor  = 0.0
irrNonPaddy_rootFraction1   = 0.4
irrNonPaddy_maxRootDepth    = 1.2
irrNonPaddy_cropCoefficientNC = $(PathIrrNonPaddy)/cropCoefficientirrNonPaddy_10days.nc

[__sealed]
sealed_minInterceptCap = 0.001

[__open_water]
water_minInterceptCap = 0.0

[GROUNDWATER]
recessionCoeff  = 0.02
specificYield   = 0.10

[RUNOFF_CONCENTRATION]
forest_runoff_peaktime       = 1.0
grassland_runoff_peaktime    = 0.5
irrPaddy_runoff_peaktime     = 0.5
irrNonPaddy_runoff_peaktime  = 0.5
sealed_runoff_peaktime       = 0.15
water_runoff_peaktime        = 0.01
interflow_runoff_peaktime    = 1.0
baseflow_runoff_peaktime     = 2.0

[ROUTING]
PathRouting = $(FILE_PATHS:PathMaps)
NoRoutingSteps = 10
chanBeta       = 0.6
chanGradMin    = 0.0001
chanGrad   = $(PathRouting)/chanGrad.nc
chanMan    = $(PathRouting)/chanMan.nc
chanLength = $(PathRouting)/chanLength.nc
chanWidth  = $(PathRouting)/chanWidth.nc
chanDepth  = $(PathRouting)/chanDepth.nc

[OUTPUT]
OUT_Dir = $(FILE_PATHS:PathOut)
OUT_TSS_Daily = discharge
OUT_Map_MonthAvg = discharge, totalET, baseflow, runoff, Precipitation
OUT_Map_AnnualAvg = discharge, totalET, baseflow
"""


def write_base_settings():
    p = f"{CASE}/settings_james.ini"
    with open(p, "w") as fh:
        fh.write(SETTINGS_TEMPLATE)
    return p


def write_settings(crop_correct, out_dir):
    src = open(f"{CASE}/settings_james.ini").read()
    src = re.sub(r"^crop_correct\s*=.*$", f"crop_correct          = {crop_correct:.3f}",
                 src, flags=re.M)
    src = re.sub(r"^PathOut\s*=.*$", f"PathOut   = {out_dir}", src, flags=re.M)
    p = f"{CASE}/settings_iter.ini"
    open(p, "w").write(src)
    return p


# -------------------------------------------------------------------- s3 run
def stage_run(crop_correct, it):
    out_dir = f"{CASE}/output_iter{it}"
    csv = f"{out_dir}/discharge_daily.csv"
    if os.path.exists(csv):
        log(f"s3 run iter{it}: {csv} exists, skipping")
        TOOLS_USED.append("run_cwatm_wrapper.py")
        return csv, out_dir
    os.makedirs(out_dir, exist_ok=True)
    settings = write_settings(crop_correct, out_dir)
    sh([PY, f"{TOOLS}/run_cwatm_wrapper.py", "--settings", settings,
        "--cwatm_dir", CWATM_DIR, "--flags=-q"], "run_cwatm_wrapper.py")
    if not os.path.exists(csv):
        raise SystemExit(f"CWatM produced no {csv}")
    return csv, out_dir


# ------------------------------------------------------------------ s4 score
def read_sim(csv):
    df = pd.read_csv(csv, skiprows=3)
    df.columns = [c.strip() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y")
    return pd.Series(df.iloc[:, 1].astype(float).values, index=df["Date"], name="sim")


def read_obs():
    """Caravan streamflow (mm/day) -> m3/s using the reported gauge drainage area."""
    ds = nc.Dataset(OBS_NC)
    d = ds.variables["date"]
    dates = nc.num2date(d[:], d.units, only_use_cftime_datetimes=False)
    sf = np.ma.filled(ds.variables["streamflow"][:].astype(float), np.nan)
    ds.close()
    idx = pd.to_datetime([datetime(t.year, t.month, t.day) for t in dates])
    q_m3s = sf * OBS_AREA_KM2 * 1000.0 / 86400.0   # mm/day * km2 -> m3/s
    s = pd.Series(q_m3s, index=idx, name="obs").dropna()
    if s.empty:
        raise SystemExit(f"no usable observations parsed from {OBS_NC}")
    return s


def score(sim, obs, a, b):
    from ki_tools_common.metrics import all_metrics
    j = pd.concat([sim, obs], axis=1).dropna().loc[a:b]
    if len(j) < 2:
        return None, 0
    m = all_metrics(j["obs"].values, j["sim"].values)
    return {k.lower(): (None if not np.isfinite(v) else round(float(v), 4))
            for k, v in m.items()}, len(j)


def water_balance(out_dir):
    try:
        mask = np.array(nc.Dataset(f"{CASE}/static/MaskMap.nc")["MaskMap"][:]) == 1
        area = np.array(nc.Dataset(f"{CASE}/static/CellArea.nc")["CellArea"][:])
        area = np.where(mask, area, 0.0); tot = area.sum()

        def mean_mm_per_day(var):
            ds = nc.Dataset(f"{out_dir}/{var}_monthavg.nc")
            name = f"{var}_monthavg" if f"{var}_monthavg" in ds.variables else var
            a = np.array(ds.variables[name][:], dtype=float)
            a = np.where(np.isfinite(a), a, 0.0)
            w = (a * area[None, :, :]).sum(axis=(1, 2)) / tot
            return float(np.mean(w)) * 1000.0

        p = mean_mm_per_day("Precipitation")
        et = mean_mm_per_day("totalET")
        ro = mean_mm_per_day("runoff")
        res = p - et - ro
        return {"status": "PASS" if abs(res) < 0.05 * max(p, 1e-9) else "WARN",
                "residual_mm": round(res * 365.25, 2),
                "residual_pct": round(100 * res / p, 2) if p else None,
                "diagnostics": [f"P={p*365.25:.0f} ET={et*365.25:.0f} runoff={ro*365.25:.0f} "
                                f"mm/yr basin-mean (storage change not removed)"]}
    except Exception as e:
        return {"status": "N/A", "residual_mm": None, "residual_pct": None,
                "diagnostics": [f"water-balance maps unavailable: {e}"]}


def write_result(res):
    os.makedirs(STATE, exist_ok=True)
    with open(f"{STATE}/result.json", "w") as fh:
        json.dump(res, fh, indent=2, ensure_ascii=False)
    log("WROTE", f"{STATE}/result.json")


def main():
    os.makedirs(STATE, exist_ok=True)
    os.chdir(ROOT)
    try:
        stage_static()
        stage_soil()
        stage_ancillary()
        stage_forcing()
        check_grids()
        write_base_settings()
        pre = forcing_preflight()
        log("forcing preflight:", json.dumps(pre))

        obs = read_obs()
        log(f"obs: n={len(obs)} {obs.index.min().date()}..{obs.index.max().date()} "
            f"mean={obs.mean():.1f} m3/s")

        tried, best = [], None
        cc = 1.00
        for it in range(MAX_ITER):
            csv, out_dir = stage_run(cc, it)
            sim = read_sim(csv)
            m_cal, n_cal = score(sim, obs, *CAL)
            if m_cal is None or m_cal.get("pbias") is None:
                raise SystemExit(f"iter{it}: no scorable overlap over CAL {CAL} (n={n_cal})")
            log(f"iter{it} crop_correct={cc:.3f}  cal NSE={m_cal['nse']} PBIAS={m_cal['pbias']} (n={n_cal})")
            tried.append({"iter": it, "crop_correct": round(cc, 3), **m_cal})
            if best is None or abs(m_cal["pbias"]) < abs(best[1]["pbias"]):
                best = (it, m_cal, cc, csv, out_dir)
            if abs(m_cal["pbias"]) <= PBIAS_TOL:
                break
            step = 1.0 + 0.5 * (m_cal["pbias"] / 100.0)
            cc = float(np.clip(cc * step, 0.8, 1.5))
            if any(abs(cc - t["crop_correct"]) < 0.005 for t in tried):
                log("crop_correct converged / saturated; stopping")
                break

        it, m_cal, cc, csv, out_dir = best
        sim = read_sim(csv)
        m_cal, n_cal = score(sim, obs, *CAL)
        m_val, n_val = score(sim, obs, *VAL)
        m_full, n_full = score(sim, obs, CAL[0], VAL[1])
        wb = water_balance(out_dir)

        r_full = m_full["r"]
        ceiling = round(r_full ** 2, 4) if r_full is not None else None

        res = {
            "model_id": "CWatM",
            "this_location": LOCATION,
            "obs_source": OBS_SOURCE,
            "status": "completed",
            "tools_used": sorted(set(TOOLS_USED)) + ["parse (read_sim)", "ki_tools_common.metrics.all_metrics"],
            "tools_failed": TOOLS_FAILED,
            "variable": "discharge",
            "obs_shape": "point_time_series",
            "metrics": {
                "nse": m_full["nse"], "kge": m_full["kge"], "pbias": m_full["pbias"],
                "r": m_full["r"], "rmse": m_full["rmse"],
                "period": f"{CAL[0]} to {VAL[1]} (daily, n={n_full})",
                "nse_cal": m_cal["nse"], "kge_cal": m_cal["kge"], "pbias_cal": m_cal["pbias"],
                "nse_val": m_val["nse"], "kge_val": m_val["kge"], "pbias_val": m_val["pbias"],
                "r_val": m_val["r"], "nse_ceiling_r2": ceiling,
                "period_calibration": f"{CAL[0]} to {CAL[1]}",
                "period_validation": f"{VAL[0]} to {VAL[1]}",
            },
            "n_paired_days": {"cal": n_cal, "val": n_val, "full": n_full},
            "calibration_trials": tried,
            "best_crop_correct": round(cc, 3),
            "water_balance": {"status": wb["status"], "residual_pct": wb["residual_pct"],
                              "residual_mm": wb["residual_mm"], "diagnostics": wb["diagnostics"]},
            "forcing_preflight": pre,
            "domain_check": {"expected_area_km2": EXPECTED_AREA_KM2,
                             "merit_upa_at_snapped_outlet_km2": 16293.87,
                             "coarse_basin_area_km2": 17124.82, "n_active_cells": 7},
            "sim_csv": csv,
            "notes": (
                f"James River at Cartersville VA (GRDC 4147330, Caravan Extension, 16,228 km2, "
                f"humid temperate Appalachian Piedmont, 79% forest, ~0 snow). Full CWatM KI chain "
                f"at a GLOBAL (non-China) location: build_cwatm_static (MERIT upa 16,294 km2 at the "
                f"snapped outlet, +0.41% vs GRDC; ESA-CCI-LC global), convert_soil_to_cwatm (HWSD), "
                f"build_cwatm_ancillary, NASA POWER daily forcing per active cell (no CMFD outside "
                f"China), run_cwatm_wrapper (real source/repo/run_cwatm.py), then NSE/KGE/PBIAS vs the "
                f"Caravan daily series (streamflow mm/day -> m3/s via drainage area). 3-year spin-up "
                f"(1990-1992); scored 1993-2012, cal 1993-2002 / val 2003-2012. Best crop_correct={cc:.3f}. "
                f"NSE is r-limited: max attainable NSE = r^2 = {ceiling}."
            ),
        }
        write_result(res)
        print(json.dumps(res["metrics"], indent=2))
    except SystemExit as e:
        write_result({
            "model_id": "CWatM", "this_location": LOCATION, "obs_source": OBS_SOURCE,
            "status": "failed", "tools_used": sorted(set(TOOLS_USED)), "tools_failed": TOOLS_FAILED,
            "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
            "water_balance": {"status": "N/A", "residual_pct": None},
            "notes": f"runner aborted: {e}"})
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        write_result({
            "model_id": "CWatM", "this_location": LOCATION, "obs_source": OBS_SOURCE,
            "status": "failed", "tools_used": sorted(set(TOOLS_USED)), "tools_failed": TOOLS_FAILED,
            "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
            "water_balance": {"status": "N/A", "residual_pct": None},
            "notes": f"runner crashed: {type(e).__name__}: {e}"})
        raise


if __name__ == "__main__":
    main()
