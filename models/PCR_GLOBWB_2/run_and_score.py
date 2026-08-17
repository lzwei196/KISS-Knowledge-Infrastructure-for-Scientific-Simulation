#!/usr/bin/env python3
"""
PCR-GLOBWB 2 verifier run #1 (this invocation): daily discharge on the Elbe
River at Neu Darchau (GRDC-Caravan extension gauge GRDC_6340110, Germany).

Third, independent location for the Songhua/Harbin real case. Deliberately a
maximally different climate/regulation regime from the two prior locations:
  - real case : Songhua @ Harbin  -- cold-continental snowmelt monsoon (China)
  - verify #2 : Araguaia @ Araguatins -- tropical wet-dry savanna (Brazil)
  - THIS run  : Elbe @ Neu Darchau -- temperate European lowland, low snow
The Rhine is excluded on purpose: it is the KI's own reference basin.

Runs the FULL documented KI pipeline using ONLY the KI tools:
  s1  make_clone_map.py                 clone + landmask from the model's own LDD
  s1b fetch_pcrglobwb_inputs.py         bbox subset of global_30min from 4TU OPeNDAP
  s2  convert_forcing_to_pcrglobwb.py   MSWX -> clone-grid forcing via
                                        ki_tools_common.load_forcing
  s4  .ini configuration (all sections, human factors ON)
  s6  run_pcrglobwb.py                  deterministic_runner.py
  s7  parse_pcrglobwb_output.py         discharge at the snapped gauge cell
  s8  ki_tools_common.metrics.all_metrics

FORCING: MSWX (global 0.1 deg 3-hourly). CMFD is China-only. MSWX ships
SWd/wind/spechum/Pres, so refET is FAO-56 Penman-Monteith (dt_031), exactly as
at Songhua and Araguaia.

PCRASTER PATH: run_pcrglobwb.py shells out to deterministic_runner.py, which
calls the `mapattr` command-line tool. `mapattr` lives in the conda env's bin/
and is NOT on the default PATH; without it virtualOS.py raises a red-herring
`KeyError: 'time'` (dt_021). We satisfy that ENVIRONMENT precondition here, in
the driver, rather than patching the tool.

RESUMABLE: every stage skips itself when its output already exists.

Run under a python that has ki_tools_common (e.g. /usr/bin/python3); the
PCRaster stages are shelled out to the pcrglobwb_python3 interpreter.
"""

import os
import sys
import json
import glob
import subprocess
from datetime import datetime

import numpy as np

# --------------------------------------------------------------------------
KI = "KISSPATH_KI_ROOT/PCR_GLOBWB_2/knowledge_infrastructure"
TOOLS = os.path.join(KI, "tools")
PCR_PY = ("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
          "PCR_GLOBWB_2/miniconda/envs/pcrglobwb_python3/bin/python")
PCR_BIN = os.path.dirname(PCR_PY)
MODEL_DIR = ("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
             "PCR_GLOBWB_2/source/repo/model")

OUT = "KISSPATH_OUTPUTS/pcrglobwb2_elbe_neudarchau"
INPUT_DIR = os.path.join(OUT, "input")
CLONE_DIR = os.path.join(OUT, "clone")
FORCING_DIR = os.path.join(INPUT_DIR, "global_30min/meteo/forcing")
RESULT_DIR = os.environ.get(
    "KDT_RESULT_DIR",
    "KISSPATH_KI_ROOT/PCR_GLOBWB_2/detached/verify_1")

MSWX_DIR = "KISSPATH_FORCING"
OBS_FILE = ("KISSPATH_DATA/observed_data/dischargeandwatershed/"
            "GRDC-Caravan-extension-nc/timeseries/netcdf/grdc/GRDC_6340110.nc")

GAUGE_ID = "GRDC_6340110"
GAUGE_NAME = "ELBE RIVER, NEU DARCHAU"
GAUGE_LAT, GAUGE_LON = 53.2354, 10.8896     # reported station coordinates
GAUGE_AREA_KM2 = 130643.066                 # Caravan basin-shapefile area
# Clone (from a verified s1 trace): UL(10.0,54.0) LR(17.0,48.0), 12x14 cells,
# gauge cell (53.25,11.25), 132,329 km2 over 68 cells (+1.29% vs reported).
# The Vltava headwaters reach ~48.3N, so the bbox extends well south of the gauge.
BBOX = (9.5, 47.5, 17.5, 54.5)              # generous, covers the traced clone
YEAR_START, YEAR_END = 2000, 2010           # water-demand inputs end 2010-12
IC_YEAR = 1999

# 2000 is the model's warm-up year and is excluded from every score.
CAL = ("2001-01-01", "2005-12-31")
VAL = ("2006-01-01", "2010-12-31")
SCORE_START = "2001-01-01"

PREFIX = "Elbe30min"

# Forcing preflight bands, TEMPERATE-EUROPE values. BOTH bounds are mandatory:
# an upper-only range check is not a range check, and lets a silently-collapsed
# variable (e.g. specific humidity pinned at 1e-6 by a unit-order bug) sail
# through. The check gates on the 2005 annual MEAN of each variable.
FORCING_BANDS = {
    "precip_mm":   (0.0, 300.0),      # mm/day
    "temp_mean_c": (-5.0, 25.0),      # degC, temperate; basin annual mean ~9
    "srad_wm2":    (10.0, 350.0),     # daily-mean W/m2
    "wind_ms":     (0.05, 20.0),      # m/s
    "shum_kgkg":   (5e-4, 3e-2),      # kg/kg, temperate
    "pres_pa":     (8.0e4, 1.03e5),   # Pa
}
ET0_BAND_MM_YR = (400.0, 1200.0)
# --------------------------------------------------------------------------


def log(msg):
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def pcraster_env():
    """Child env with the conda bin/ (holding `mapattr`) prepended to PATH."""
    env = dict(os.environ)
    env["PATH"] = PCR_BIN + os.pathsep + env.get("PATH", "")
    return env


def sh(cmd, **kw):
    log("RUN " + " ".join(str(c) for c in cmd))
    kw.setdefault("env", pcraster_env())
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(map(str, cmd))}")
    return r


def stage_preflight():
    """Fail loudly and early on the two preconditions that silently mis-fail."""
    import shutil
    mapattr = shutil.which("mapattr", path=pcraster_env()["PATH"])
    if not mapattr:
        raise RuntimeError(
            "`mapattr` not resolvable on PATH. deterministic_runner.py shells "
            "out to it; without it virtualOS.py raises a misleading "
            "KeyError: 'time' (dt_021).")
    log(f"s0 preflight: mapattr -> {mapattr}")
    if not os.path.isfile(OBS_FILE):
        raise FileNotFoundError(f"obs not found: {OBS_FILE}")
    if not os.path.isdir(MSWX_DIR):
        raise FileNotFoundError(f"MSWX forcing archive not found: {MSWX_DIR}")
    for y in range(YEAR_START, YEAR_END + 1):
        for sub, pre in (("P", "P"), ("Tair", "Tair"), ("SWd", "SWd"),
                         ("LWd", "LWd"), ("wind", "Wind"),
                         ("spechum", "spechum"), ("Pres", "Pres")):
            f = os.path.join(MSWX_DIR, sub, f"{pre}_{y}.nc")
            if not os.path.isfile(f):
                raise FileNotFoundError(f"MSWX file missing: {f}")
    log(f"s0 preflight: MSWX complete for {YEAR_START}-{YEAR_END}")


# --------------------------------------------------------------------------
# s1 clone + landmask
# --------------------------------------------------------------------------
def stage_clone():
    meta_path = os.path.join(CLONE_DIR, f"{PREFIX}.clone.json")
    if os.path.exists(meta_path):
        log("s1 clone: cached")
        return json.load(open(meta_path))
    sh([PCR_PY, os.path.join(TOOLS, "make_clone_map.py"),
        "--out-dir", CLONE_DIR, "--prefix", PREFIX,
        "--gauge-lat", GAUGE_LAT, "--gauge-lon", GAUGE_LON,
        "--target-area-km2", GAUGE_AREA_KM2, "--snap-search", 2,
        "--cellsize", 0.5, "--buffer-cells", 1])
    return json.load(open(meta_path))


# --------------------------------------------------------------------------
# s1b input acquisition
# --------------------------------------------------------------------------
def stage_inputs():
    flag = os.path.join(INPUT_DIR, ".fetch_ok")
    if os.path.exists(flag):
        log("s1b inputs: cached")
        return
    sh([PCR_PY, os.path.join(TOOLS, "fetch_pcrglobwb_inputs.py"),
        "--bbox", *BBOX, "--local-dir", INPUT_DIR,
        "--year-start", YEAR_START, "--year-end", YEAR_END,
        "--ic-year", IC_YEAR, "--workers", 4])
    open(flag, "w").write("ok\n")


# --------------------------------------------------------------------------
# s2 forcing (MSWX -> clone grid, via ki_tools_common.load_forcing)
# --------------------------------------------------------------------------
def forcing_preflight(clone_meta):
    """Sanity-check ONE clone cell of raw MSWX before the 11-year build."""
    from ki_tools_common.load_forcing import load_daily_forcing_points
    lat, lon = clone_meta["gauge_cell_lat"], clone_meta["gauge_cell_lon"]
    # Two points -> the BATCHED reader, which shares one decompression pass.
    probe = [(lat, lon), (clone_meta["lat_min_centre"], clone_meta["lon_min_centre"])]
    d = load_daily_forcing_points("mswx", probe, 2005, 2005,
                                  forcing_dir=MSWX_DIR)[0]
    failures, warnings_ = [], []
    for key, (lo, hi) in FORCING_BANDS.items():
        v = np.asarray(d[key], dtype=float)
        v = v[np.isfinite(v)]
        if v.size == 0:
            failures.append(f"{key}: all-NaN")
            continue
        vmin, vmax, vmean = float(v.min()), float(v.max()), float(v.mean())
        if vmean < lo or vmean > hi:
            failures.append(f"{key}: mean {vmean:.4g} outside [{lo:g},{hi:g}]")
        elif vmin < lo - abs(lo) * 0.8 - 1.0 or vmax > hi * 1.5:
            warnings_.append(f"{key}: range [{vmin:.4g},{vmax:.4g}] "
                             f"strays beyond band [{lo:g},{hi:g}]")
        log(f"  preflight {key:12s} min={vmin:11.4g} mean={vmean:11.4g} max={vmax:11.4g}")
    p_yr = float(np.nansum(d["precip_mm"]))
    log(f"  preflight annual precip {p_yr:.0f} mm/yr at ({lat},{lon})")
    if not (350.0 <= p_yr <= 1800.0):
        failures.append(f"annual precip {p_yr:.0f} mm/yr implausible for Elbe")
    if failures:
        raise RuntimeError("forcing preflight FAILED: " + "; ".join(failures))
    return {"all_pass": True, "source": "MSWX 3-hourly 0.1deg (global)",
            "failures": [], "warnings": warnings_,
            "probe_cell": [lat, lon], "probe_year": 2005,
            "probe_annual_precip_mm": round(p_yr, 1)}


def stage_forcing(clone_meta):
    p = os.path.join(FORCING_DIR, "precipitation.nc")
    t = os.path.join(FORCING_DIR, "temperature.nc")
    e = os.path.join(FORCING_DIR, "referencePotET.nc")
    # dt_031: refET is a REQUIRED product (referenceETPotMethod = Input).
    if os.path.exists(p) and os.path.exists(t) and os.path.exists(e):
        log("s2 forcing: cached")
        return
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cf", os.path.join(TOOLS, "convert_forcing_to_pcrglobwb.py"))
    cf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cf)
    cf.build_from_ki_forcing(
        source="mswx", clone_meta=clone_meta, output_dir=FORCING_DIR,
        start_year=YEAR_START, end_year=YEAR_END,
        forcing_dir=MSWX_DIR, subsample=2,
        refet_method="penman",   # dt_031: FAO-56 PM, not temperature-only Hamon
        cache_dir=os.path.join(OUT, "forcing_cache"))
    cf.validate_outputs(FORCING_DIR, None, None)


# --------------------------------------------------------------------------
# s4 .ini configuration
# --------------------------------------------------------------------------
INI_TEMPLATE = """[globalOptions]
outputDir = {out}
cloneMap  = {clone}
landmask  = {landmask}
inputDir  = {input_dir}/

institution = HydroCraft / Jianyun Zhang Research Group
title       = PCR-GLOBWB 2 Elbe 30min -- discharge at Neu Darchau (GRDC 6340110)
description = 30 arcmin run, human factors ON, MSWX forcing, FAO-56 Penman-Monteith refET

startTime = {start}
endTime   = {end}

maxSpinUpsInYears = 0
minConvForSoilSto = 0.0
minConvForGwatSto = 0.0
minConvForChanSto = 0.0
minConvForTotlSto = 0.0


[meteoOptions]
precipitationNC = global_30min/meteo/forcing/precipitation.nc
temperatureNC   = global_30min/meteo/forcing/temperature.nc

# MSWX ships SWd/wind/spechum/Pres -> FAO-56 Penman-Monteith refET (dt_031)
referenceETPotMethod = Input
refETPotFileNC = global_30min/meteo/forcing/referencePotET.nc


[landSurfaceOptions]
debugWaterBalance = True
numberOfUpperSoilLayers = 2

topographyNC     = global_30min/landSurface/topography/topography_parameters_30_arcmin_october_2015.nc
soilPropertiesNC = global_30min/landSurface/soil/soilProperties.nc

includeIrrigation = True
historicalIrrigationArea = global_30min/waterUse/irrigation/irrigated_areas/irrigationArea30ArcMin.nc
irrigationEfficiency     = global_30min/waterUse/irrigation/irrigation_efficiency/efficiency.nc

includeDomesticWaterDemand  = True
includeIndustryWaterDemand  = True
includeLivestockWaterDemand = True

domesticWaterDemandFile  = global_30min/waterUse/waterDemand/domestic_water_demand_version_october_2014.nc
industryWaterDemandFile  = global_30min/waterUse/waterDemand/industrial_water_demand_version_october_2014.nc
livestockWaterDemandFile = global_30min/waterUse/waterDemand/livestock_water_demand_1960-2012.nc

desalinationWater = global_30min/waterUse/desalination/desalination_water_use_version_october_2014.nc

allocationSegmentsForGroundSurfaceWater = global_30min/waterUse/abstraction_zones/abstraction_zones_60min_30min.nc

irrigationSurfaceWaterAbstractionFractionData        = global_30min/waterUse/source_partitioning/surface_water_fraction_for_irrigation/AEI_SWFRAC.nc
irrigationSurfaceWaterAbstractionFractionDataQuality = global_30min/waterUse/source_partitioning/surface_water_fraction_for_irrigation/AEI_QUAL.nc

treshold_to_maximize_irrigation_surface_water      = 0.50
treshold_to_minimize_fossil_groundwater_irrigation = 0.70

maximumNonIrrigationSurfaceWaterAbstractionFractionData = global_30min/waterUse/source_partitioning/surface_water_fraction_for_non_irrigation/max_city_sw_fraction.nc


[forestOptions]
name = forest
debugWaterBalance = True
snowModuleType      = Simple
freezingT           = 0.0
degreeDayFactor     = {ddf}
snowWaterHoldingCap = 0.1
refreezingCoeff     = 0.05
minTopWaterLayer  = 0.0
minCropKC         = 0.2
cropCoefficientNC = global_30min/landSurface/landCover/naturalTall/Global_CropCoefficientKc-Forest_30min.nc
interceptCapNC    = global_30min/landSurface/landCover/naturalTall/interceptCapInputForest366days.nc
coverFractionNC   = global_30min/landSurface/landCover/naturalTall/coverFractionInputForest366days.nc
landCoverMapsNC   = global_30min/landSurface/landCover/naturalTall/forestProperties.nc
{ic_forest}

[grasslandOptions]
name = grassland
debugWaterBalance = True
snowModuleType      = Simple
freezingT           = 0.0
degreeDayFactor     = {ddf}
snowWaterHoldingCap = 0.1
refreezingCoeff     = 0.05
minTopWaterLayer = 0.0
minCropKC        = 0.2
cropCoefficientNC = global_30min/landSurface/landCover/naturalShort/Global_CropCoefficientKc-Grassland_30min.nc
interceptCapNC    = global_30min/landSurface/landCover/naturalShort/interceptCapInputGrassland366days.nc
coverFractionNC   = global_30min/landSurface/landCover/naturalShort/coverFractionInputGrassland366days.nc
landCoverMapsNC  = global_30min/landSurface/landCover/naturalShort/grasslandProperties.nc
{ic_grassland}

[irrPaddyOptions]
name = irrPaddy
debugWaterBalance = True
snowModuleType      = Simple
freezingT           = 0.0
degreeDayFactor     = {ddf}
snowWaterHoldingCap = 0.1
refreezingCoeff     = 0.05
landCoverMapsNC  = global_30min/landSurface/landCover/irrPaddy/paddyProperties.nc
minTopWaterLayer = 0.05
minCropKC        = 0.2
cropDeplFactor   = 0.2
minInterceptCap  = 0.0002
cropCoefficientNC = global_30min/landSurface/landCover/irrPaddy/Global_CropCoefficientKc-IrrPaddy_30min.nc
{ic_irrPaddy}

[irrNonPaddyOptions]
name = irrNonPaddy
debugWaterBalance = True
snowModuleType      = Simple
freezingT           = 0.0
degreeDayFactor     = {ddf}
snowWaterHoldingCap = 0.1
refreezingCoeff     = 0.05
landCoverMapsNC  = global_30min/landSurface/landCover/irrNonPaddy/nonPaddyProperties.nc
minTopWaterLayer = 0.0
minCropKC        = 0.2
cropDeplFactor   = 0.5
minInterceptCap  = 0.0002
cropCoefficientNC = global_30min/landSurface/landCover/irrNonPaddy/Global_CropCoefficientKc-IrrNonPaddy_30min.nc
{ic_irrNonPaddy}

[groundwaterOptions]
debugWaterBalance = True
groundwaterPropertiesNC = global_30min/groundwater/properties/groundwaterProperties.nc
minRecessionCoeff = 1.0e-4
limitFossilGroundWaterAbstraction      = True
estimateOfRenewableGroundwaterCapacity = 0.0
estimateOfTotalGroundwaterThickness    = global_30min/groundwater/aquifer_thickness_estimate/thickness_30min.nc
minimumTotalGroundwaterThickness       = 100.
maximumTotalGroundwaterThickness       = None
pumpingCapacityNC = global_30min/waterUse/groundwater_pumping_capacity/regional_abstraction_limit.nc
{ic_groundwater}
allocationSegmentsForGroundwater = global_30min/waterUse/abstraction_zones/abstraction_zones_30min_30min.nc


[routingOptions]
debugWaterBalance = True
lddMap      = global_30min/routing/ldd_and_cell_area/lddsound_30min.nc
cellAreaMap = global_30min/routing/ldd_and_cell_area/cellarea30min.nc
routingMethod = accuTravelTime
manningsN = 0.04
dynamicFloodPlain = True
floodplainManningsN = 0.07
gradient             = global_30min/routing/channel_properties/channel_gradient.nc
constantChannelDepth = global_30min/routing/channel_properties/bankfull_depth.nc
constantChannelWidth = global_30min/routing/channel_properties/bankfull_width.nc
minimumChannelWidth  = global_30min/routing/channel_properties/bankfull_width.nc
bankfullCapacity = None
relativeElevationFiles  = global_30min/routing/channel_properties/dzRel%04d.nc
relativeElevationLevels = 0.0, 0.01, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00
cropCoefficientWaterNC = global_30min/routing/kc_surface_water/cropCoefficientForOpenWater.nc
minCropWaterKC         = 1.00
waterBodyInputNC       = global_30min/routing/surface_water_bodies/waterBodies30min.nc
onlyNaturalWaterBodies = False
{ic_routing}

[reportingOptions]
outDailyTotNC = discharge,totalRunoff,gwRecharge
outMonthTotNC = actualET,precipitation,totalRunoff,baseflow,directRunoff,interflowTotal,gwRecharge
outMonthAvgNC = discharge,temperature,storGroundwater,channelStorage,totalWaterStorageThickness
outMonthEndNC = storGroundwater,channelStorage,totalWaterStorageThickness
outAnnuaTotNC = totalEvaporation,precipitation,gwRecharge,totalRunoff,baseflow
outAnnuaAvgNC = temperature,discharge
outAnnuaEndNC = storGroundwater,totalWaterStorageThickness
outMonthMaxNC = discharge,totalRunoff
outAnnuaMaxNC = None
"""

IC_REL = f"global_30min/initialConditions/non-natural/consistent_run_201903XX/{IC_YEAR}"
IC_DATE = f"{IC_YEAR}-12-31"

_COVER_IC = ["interceptStor", "snowCoverSWE", "snowFreeWater", "topWaterLayer",
             "storUpp", "storLow", "interflow"]
_COVER_KEY = {"interceptStor": "interceptStorIni", "snowCoverSWE": "snowCoverSWEIni",
              "snowFreeWater": "snowFreeWaterIni", "topWaterLayer": "topWaterLayerIni",
              "storUpp": "storUppIni", "storLow": "storLowIni",
              "interflow": "interflowIni"}

_GW_IC = [("storGroundwaterIni", "storGroundwater"),
          ("storGroundwaterFossilIni", "storGroundwaterFossil"),
          ("avgNonFossilGroundwaterAllocationLongIni", "avgNonFossilGroundwaterAllocationLong"),
          ("avgNonFossilGroundwaterAllocationShortIni", "avgNonFossilGroundwaterAllocationShort"),
          ("avgTotalGroundwaterAbstractionIni", "avgTotalGroundwaterAbstraction"),
          ("avgTotalGroundwaterAllocationLongIni", "avgTotalGroundwaterAllocationLong"),
          ("avgTotalGroundwaterAllocationShortIni", "avgTotalGroundwaterAllocationShort"),
          ("relativeGroundwaterHeadIni", "relativeGroundwaterHead"),
          ("baseflowIni", "baseflow")]

_ROUTE_IC = [("waterBodyStorageIni", "waterBodyStorage"),
             ("channelStorageIni", "channelStorage"),
             ("readAvlChannelStorageIni", "readAvlChannelStorage"),
             ("avgDischargeLongIni", "avgDischargeLong"),
             ("avgDischargeShortIni", "avgDischargeShort"),
             ("m2tDischargeLongIni", "m2tDischargeLong"),
             ("avgBaseflowLongIni", "avgBaseflowLong"),
             ("riverbedExchangeIni", "riverbedExchange"),
             ("subDischargeIni", "subDischarge"),
             ("avgLakeReservoirInflowShortIni", "avgLakeReservoirInflowShort"),
             ("avgLakeReservoirOutflowLongIni", "avgLakeReservoirOutflowLong"),
             ("timestepsToAvgDischargeIni", "timestepsToAvgDischarge")]


def _ic_block(cover):
    return "\n".join(f"{_COVER_KEY[s]} = {IC_REL}/{s}_{cover}_{IC_DATE}.nc"
                     for s in _COVER_IC)


def _ic_pairs(pairs):
    return "\n".join(f"{k} = {IC_REL}/{v}_{IC_DATE}.nc" for k, v in pairs)


def stage_ini(clone_meta, degree_day_factor=0.0025):
    ini = os.path.join(OUT, "setup_elbe_neudarchau_30min.ini")
    text = INI_TEMPLATE.format(
        out=OUT, clone=clone_meta["clone_map"], landmask=clone_meta["landmask_map"],
        input_dir=INPUT_DIR,
        start=f"{YEAR_START}-01-01", end=f"{YEAR_END}-12-31",
        ddf=degree_day_factor,
        ic_forest=_ic_block("forest"),
        ic_grassland=_ic_block("grassland"),
        ic_irrPaddy=_ic_block("irrPaddy"),
        ic_irrNonPaddy=_ic_block("irrNonPaddy"),
        ic_groundwater=_ic_pairs(_GW_IC),
        ic_routing=_ic_pairs(_ROUTE_IC),
    )
    with open(ini, "w") as f:
        f.write(text)
    log(f"s4 ini written: {ini}")
    return ini


# --------------------------------------------------------------------------
# s6 model run
# --------------------------------------------------------------------------
def stage_run(ini):
    nc_out = os.path.join(OUT, "netcdf", "discharge_dailyTot_output.nc")
    if os.path.exists(nc_out):
        log("s6 model: cached (discharge_dailyTot_output.nc exists)")
        return nc_out
    sh([PCR_PY, os.path.join(TOOLS, "run_pcrglobwb.py"), ini,
        "--model-dir", MODEL_DIR])
    if not os.path.exists(nc_out):
        raise RuntimeError(f"model finished but {nc_out} was not written")
    return nc_out


# --------------------------------------------------------------------------
# s7 output parsing
# --------------------------------------------------------------------------
def stage_parse(clone_meta):
    csv = os.path.join(OUT, "simulated_discharge_neudarchau.csv")
    if os.path.exists(csv):
        log("s7 parse: cached")
        return csv
    sh([PCR_PY, os.path.join(TOOLS, "parse_pcrglobwb_output.py"),
        os.path.join(OUT, "netcdf"),
        "--variable", "discharge",
        "--aggregation", "dailyTot",   # dt_027: discharge lives in >1 file
        "--lat", clone_meta["gauge_cell_lat"],
        "--lon", clone_meta["gauge_cell_lon"],
        "--output", csv])
    return csv


# --------------------------------------------------------------------------
# water balance from the annual basin fields
# --------------------------------------------------------------------------
def water_balance():
    """Basin land-water balance over 2001-2010: P - ET - Q_local - dS."""
    import netCDF4 as nc4
    ncdir = os.path.join(OUT, "netcdf")

    def annual(varname, tag):
        path = os.path.join(ncdir, f"{varname}_{tag}_output.nc")
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        with nc4.Dataset(path) as ds:
            v = ds.variables[varname]
            a = np.asarray(v[:], dtype=float)
            if hasattr(v, "_FillValue"):
                a[a == float(v._FillValue)] = np.nan
            a = np.ma.filled(np.ma.masked_invalid(a), np.nan)
            times = nc4.num2date(ds.variables["time"][:],
                                 ds.variables["time"].units)
            years = np.array([t.year for t in times])
        with np.errstate(invalid="ignore"):
            basin = np.nanmean(a.reshape(a.shape[0], -1), axis=1)
        return dict(zip(years.tolist(), basin.tolist()))

    P = annual("precipitation", "annuaTot")
    E = annual("totalEvaporation", "annuaTot")
    Q = annual("totalRunoff", "annuaTot")
    S = annual("totalWaterStorageThickness", "annuaEnd")

    yrs = [y for y in range(YEAR_START + 1, YEAR_END + 1)
           if y in P and y in E and y in Q]
    if len(yrs) < 2 or (YEAR_START not in S) or (YEAR_END not in S):
        raise RuntimeError("insufficient annual output for a water balance")

    sP = sum(P[y] for y in yrs)
    sE = sum(E[y] for y in yrs)
    sQ = sum(Q[y] for y in yrs)
    dS = S[YEAR_END] - S[YEAR_START]
    resid = sP - sE - sQ - dS
    pct = 100.0 * resid / sP if sP else float("nan")

    status = "PASS" if abs(pct) < 5 else ("WARN" if abs(pct) < 10 else "FAIL")
    log(f"water balance {yrs[0]}-{yrs[-1]}: P={sP*1000:.0f} ET={sE*1000:.0f} "
        f"Q={sQ*1000:.0f} dS={dS*1000:.0f} resid={resid*1000:.0f} mm ({pct:+.2f}%)")
    return {"status": status,
            "residual_pct": round(float(pct), 3),
            "residual_mm": round(float(resid * 1000.0), 2),
            "diagnostics": [
                f"period {yrs[0]}-{yrs[-1]} (warm-up {YEAR_START} excluded)",
                f"P={sP*1000:.1f} mm, ET={sE*1000:.1f} mm, "
                f"totalRunoff={sQ*1000:.1f} mm, dTWS={dS*1000:.1f} mm",
            ]}


# --------------------------------------------------------------------------
# s8 scoring
# --------------------------------------------------------------------------
def load_obs():
    """Caravan `streamflow` is mm/day over the basin -> m3/s via the basin area."""
    import netCDF4 as nc4
    with nc4.Dataset(OBS_FILE) as ds:
        q = np.ma.filled(np.asarray(ds.variables["streamflow"][:], dtype=float),
                         np.nan)
        tv = ds.variables["date"]
        dates = nc4.num2date(tv[:], tv.units,
                             only_use_cftime_datetimes=False,
                             only_use_python_datetimes=True)
    # mm/day * km2 -> m3/s :  mm/d * 1e-3 m/mm * 1e6 m2/km2 / 86400 s = /86.4
    scale = GAUGE_AREA_KM2 / 86.4
    out = {}
    for d, v in zip(dates, q):
        if np.isfinite(v):
            out[d.strftime("%Y-%m-%d")] = float(v) * scale
    return out


def load_sim(csv_path):
    out = {}
    with open(csv_path) as f:
        next(f)
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 2:
                continue
            try:
                out[parts[0][:10]] = float(parts[1])
            except ValueError:
                pass
    return out


def score(sim, obs, period=None):
    """Paired sim/obs metrics from ONE all_metrics call (all-or-nothing)."""
    from ki_tools_common.metrics import all_metrics
    keys = sorted(set(sim) & set(obs))
    lo = period[0] if period else SCORE_START
    hi = period[1] if period else f"{YEAR_END}-12-31"
    keys = [k for k in keys if lo <= k <= hi]
    keys = [k for k in keys if np.isfinite(sim[k]) and np.isfinite(obs[k])]
    if len(keys) < 2:
        return None, 0
    o = np.array([obs[k] for k in keys], dtype=float)
    s = np.array([sim[k] for k in keys], dtype=float)
    m = {k.lower(): float(v) for k, v in all_metrics(o, s).items()}
    return m, len(keys)


def main():
    os.makedirs(RESULT_DIR, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    stage_preflight()
    clone_meta = stage_clone()
    stage_inputs()

    pf_path = os.path.join(OUT, "forcing_preflight.json")
    if os.path.exists(pf_path):
        preflight = json.load(open(pf_path))
        log("forcing preflight: cached")
    else:
        preflight = forcing_preflight(clone_meta)
        json.dump(preflight, open(pf_path, "w"), indent=2)

    stage_forcing(clone_meta)
    ini = stage_ini(clone_meta)
    stage_run(ini)
    csv_path = stage_parse(clone_meta)

    sim = load_sim(csv_path)
    obs = load_obs()
    log(f"sim days={len(sim)}  obs days={len(obs)}")

    m_all, n_all = score(sim, obs)
    m_cal, n_cal = score(sim, obs, CAL)
    m_val, n_val = score(sim, obs, VAL)

    if m_all is None:
        metrics = {k: None for k in ("nse", "r", "kge", "pbias",
                                     "nse_cal", "kge_cal",
                                     "nse_val", "kge_val", "pbias_val")}
        metrics["period"] = None
        null_reason = "no temporal overlap between simulated and observed discharge"
    else:
        metrics = {
            "nse": round(float(m_all["nse"]), 4),
            "r": round(float(m_all["r"]), 4),
            "kge": round(float(m_all["kge"]), 4),
            "pbias": round(float(m_all["pbias"]), 4),
            "nse_cal": round(float(m_cal["nse"]), 4) if m_cal else None,
            "kge_cal": round(float(m_cal["kge"]), 4) if m_cal else None,
            "nse_val": round(float(m_val["nse"]), 4) if m_val else None,
            "kge_val": round(float(m_val["kge"]), 4) if m_val else None,
            "pbias_val": round(float(m_val["pbias"]), 4) if m_val else None,
            "period": f"{SCORE_START}..{YEAR_END}-12-31",
            "period_calibration": f"{CAL[0]}..{CAL[1]}",
            "period_validation": f"{VAL[0]}..{VAL[1]}",
        }
        null_reason = None

    try:
        wb = water_balance()
    except Exception as exc:                    # non-fatal
        log(f"water balance unavailable: {exc}")
        wb = {"status": "N/A", "residual_pct": None, "residual_mm": None,
              "diagnostics": [f"{type(exc).__name__}: {exc}"]}

    paired = [k for k in sorted(set(sim) & set(obs)) if k >= SCORE_START]
    sim_vals = np.array([sim[k] for k in paired], dtype=float)
    obs_vals = np.array([obs[k] for k in paired], dtype=float)

    notes = (
        f"Verifier location #1 (this run): {GAUGE_NAME} ({GAUGE_ID}), Germany -- "
        f"a temperate European lowland river, low snow fraction (~0.08), "
        f"{GAUGE_AREA_KM2:,.0f} km2, chosen as a third independent climate/"
        f"regulation regime distinct from the cold-continental Songhua real case "
        f"and the tropical Araguaia (verify #2); the Rhine is excluded as it is "
        f"the KI's own reference basin. The full KI pipeline ran unmodified: "
        f"make_clone_map traced 68 LDD cells (132,329 km2, +1.29% vs the reported "
        f"area) and snapped the gauge from (53.235,10.890) to cell centre "
        f"(53.25,11.25); the clone spans UL(10,54)->LR(17,48) so the Vltava "
        f"headwaters (~48.3N) are inside it. CMFD is China-only, so forcing came "
        f"from global MSWX; because MSWX ships SWd/wind/spechum/Pres the refET is "
        f"FAO-56 Penman-Monteith (dt_031), the same choice as at Songhua and "
        f"Araguaia. run_pcrglobwb.py still needs the dt_021 PATH precondition "
        f"(`mapattr` on PATH, else virtualOS.py dies with a red-herring "
        f"KeyError: 'time'); this driver supplies PATH in the environment rather "
        f"than patching the tool. Observed streamflow is Caravan mm/day, "
        f"converted to m3/s with the basin area. 2000 is warm-up and is excluded "
        f"from every score; cal 2001-2005, val 2006-2010."
    )
    if null_reason:
        notes += f" METRICS NULL: {null_reason}."

    result = {
        "model_id": "PCR_GLOBWB_2",
        "this_location": "GRDC-Caravan Extension (5,357 global gauges + basin shapes)",
        "obs_source": "GRDC",
        "status": "completed",
        "tools_used": [
            "make_clone_map.py", "fetch_pcrglobwb_inputs.py",
            "convert_forcing_to_pcrglobwb.py", "run_pcrglobwb.py",
            "parse_pcrglobwb_output.py", "ki_tools_common.load_forcing",
            "ki_tools_common.metrics.all_metrics",
        ],
        "tools_failed": [],
        "metrics": metrics,
        "water_balance": wb,
        "notes": notes,
        # ---- supporting detail (ignored by the orchestrator's schema) ----
        "gauge": {"id": GAUGE_ID, "name": GAUGE_NAME,
                  "lat": GAUGE_LAT, "lon": GAUGE_LON,
                  "reported_area_km2": GAUGE_AREA_KM2},
        "gauge_cell": {"lat": clone_meta["gauge_cell_lat"],
                       "lon": clone_meta["gauge_cell_lon"],
                       "upstream_area_km2": clone_meta["catchment_area_km2"],
                       "area_error_pct": clone_meta["area_error_pct"]},
        "forcing_preflight": preflight,
        "obs_shape": "point_time_series",
        "test_runs": [{"variable": "discharge", "obs_shape": "point_time_series",
                       "n_paired_days": n_all, "n_cal_days": n_cal,
                       "n_val_days": n_val}],
        "sim_mean_m3s": round(float(sim_vals.mean()), 2) if sim_vals.size else None,
        "obs_mean_m3s": round(float(obs_vals.mean()), 2) if obs_vals.size else None,
        "simulation_period": f"{YEAR_START}-01-01..{YEAR_END}-12-31",
    }
    if null_reason:
        result["metrics_null_reason"] = null_reason

    path = os.path.join(RESULT_DIR, "result.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    log("WROTE " + path)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
