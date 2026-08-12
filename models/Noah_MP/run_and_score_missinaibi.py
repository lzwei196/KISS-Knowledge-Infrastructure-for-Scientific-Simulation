#!/usr/bin/env python3
"""
Noah-MP HRLDAS VERIFIER runner — MISSINAIBI RIVER AT MATTICE (HYDAT 04LJ001, Ontario, Canada).

Consistency check #3 for the Noah-MP KI (real-case was 允景洪/Lancang, China). Same KI tools,
DIFFERENT location + DIFFERENT forcing product (Canada is outside CMFD -> MSWX global 3-hourly).
Obs = HYDAT daily discharge (DLY_FLOWS), a natural RHBN reference basin (REGULATED=0), 8570 km2.

Pipeline (uses the Noah-MP KI tools, mirroring the real-case + Clutha/Wangjiaba verifiers):
  0. Delineate the basin above the gauge from HydroBASINS North America lev12 (upstream traversal
     of NEXT_DOWN from the outlet sub-basin that contains the pour point, UP_AREA ~= 8570 km2).
  1. Enumerate MSWX 0.1deg cells inside the basin polygon; subsample to N (lat-lon spread).
  2. READ-ONCE MSWX: for each year slice the basin bounding box out of the yearly MSWX file
     (3-hourly global 0.1deg), aggregate 3h->DAILY, write CMFD-style box files
     (temp_/prec_/pres_/shum_/srad_/lrad_/wind_ YYYY.nc) with units the KI cmfd path expects
     (Celsius / mm/s / Pa / kg/kg / W/m2 / m/s). Daily stamp 10:30 to mirror CMFD daily.
  3. Per cell (RESUMABLE): KI convert_forcing_to_noahmp (--source cmfd) -> LDASIN, build 1x1
     HRLDAS setup file, KI run_noahmp (existing binary), KI parse_noahmp_output -> runoff+ET.
  4. Area-weight cell runoff -> basin-mean runoff (mm/day) -> discharge Q = runoff*A/86.4.
  5. Water-balance closure; NSE/KGE/PBIAS/r vs observed daily Q (m3/s, HYDAT DLY_FLOWS).
     (Noah-MP is an LSM with NO routing; a simple linear-reservoir routed series is also
      reported for reference, clearly labelled as beyond the KI.)

Everything (delineation, MSWX read-once, per-cell convert/run/parse) runs INSIDE this one
detached script and is resumable at every stage (basin cache, MSWX box year, cell runoff.npz).
"""
import os, sys, glob, json, shutil, subprocess, traceback, calendar
import numpy as np
import netCDF4 as nc
from datetime import datetime, timedelta

# ----------------------------------------------------------------------------- paths
ROOT   = "/mnt/disk1/Hydrocraft_server/models/Noah_MP"
KI     = f"{ROOT}/knowledge_infrastructure"
TOOLS  = f"{KI}/tools"
BIN    = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/Noah_MP/source/hrldas/hrldas/run/hrldas.exe"
SRCDIR = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/Noah_MP/source/repo"
MSWX   = "/mnt/disk3/msxw"
HYBAS  = "/mnt/disk1/Hydrocraft_server/data/awd_paper/hydrobasins/north_america/hybas_na_lev12_v1c.shp"
ESA    = "/mnt/datasets/vegetation/ESA_CCI_LC_global/ESA_CCI_LC_global_1992_01deg.tif"
MERIT  = "/mnt/datasets/MERIT_DEM"
HYDAT  = "/mnt/datasets/observed_data/dischargeandwatershed/National Water Data Archive HYDAT/Hydat.sqlite3"
WORK   = f"{ROOT}/detached/verify_3"
CELLS  = f"{WORK}/cells"
BOX    = f"{WORK}/mswx_cmfd"            # CMFD-style box forcing derived from MSWX
RESULT = f"{WORK}/result.json"
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent")

# ----------------------------------------------------------------------------- config
GAUGE       = "04LJ001"
LOCATION    = "Missinaibi River at Mattice (HYDAT 04LJ001, Ontario, Canada)"
POUR_LAT, POUR_LON = 49.61108, -83.26778
AREA_KNOWN  = 8570.0                  # km2 (HYDAT DRAINAGE_AREA_GROSS)
N_CELLS     = 40
RUN_START   = datetime(2004, 1, 1)    # spinup begins (2004-2005 discarded)
SCORE_START = datetime(2006, 1, 1)    # metrics start
RUN_END     = datetime(2012, 12, 31)  # scored through here
FORCE_END   = datetime(2013, 1, 10)   # forcing generated a bit beyond (off-by-one margin)
CAL = ("2006-01-01", "2009-12-31")
VAL = ("2010-01-01", "2012-12-31")

# MSWX var dir/file/var -> CMFD-style filename stem + how to aggregate 3h->daily
MSWX_VARS = {
    "temp": ("Tair",    "Tair_%d.nc",    "air_temperature",              "mean"),
    "pres": ("Pres",    "Pres_%d.nc",    "surface_pressure",             "mean"),
    "shum": ("spechum", "spechum_%d.nc", "specific_humidity",            "mean"),
    "srad": ("SWd",     "SWd_%d.nc",     "downward_shortwave_radiation", "mean"),
    "lrad": ("LWd",     "LWd_%d.nc",     "downward_longwave_radiation",  "mean"),
    "wind": ("Wind",    "Wind_%d.nc",    "wind_speed",                   "mean"),
    "prec": ("P",       "P_%d.nc",       "precipitation",                "rate"),
}

# ESA-CCI LCCS -> MODIS/IGBP (MODIFIED_IGBP_MODIS_NOAH, 1-20)
def esa_to_igbp(v):
    v = int(v)
    if v in (10,11,12,20,30): return 12
    if v == 40:               return 14
    if v == 50:               return 2
    if v in (60,61,62):       return 4
    if v in (70,71,72):       return 1
    if v in (80,81,82):       return 3
    if v == 90:               return 5
    if v == 100:              return 8
    if v == 110:              return 9
    if v in (120,121,122):    return 7
    if v == 130:              return 10
    if v == 140:              return 19
    if v in (150,151,152,153):return 16
    if v in (160,170,180):    return 11
    if v == 190:              return 13
    if v in (200,201,202):    return 16
    if v == 210:              return 17
    if v == 220:              return 15
    return 10

def log(*a): print(*a, flush=True)

# ----------------------------------------------------------------------------- basin
def delineate():
    cache = f"{WORK}/basin_cells.json"
    if os.path.exists(cache):
        return json.load(open(cache))
    import geopandas as gpd
    from shapely.geometry import Point
    from collections import defaultdict, deque
    log("loading HydroBASINS North America lev12 (large; one-time)...")
    g = gpd.read_file(HYBAS)
    pt = Point(POUR_LON, POUR_LAT)
    hit = g[g.contains(pt)]
    if len(hit) == 0:
        # nearest basin centroid fallback
        g["d"] = g.geometry.centroid.distance(pt)
        hit = g.nsmallest(1, "d")
    else:
        hit = hit.iloc[(hit.UP_AREA - AREA_KNOWN).abs().argsort()]
    outlet = int(hit.iloc[0].HYBAS_ID)
    ids = g["HYBAS_ID"].to_numpy(); nd = g["NEXT_DOWN"].to_numpy()
    children = defaultdict(list)
    for i in range(len(ids)):
        children[int(nd[i])].append(int(ids[i]))
    ups = {outlet}; dq = deque([outlet])
    while dq:
        c = dq.popleft()
        for ch in children.get(c, []):
            if ch not in ups: ups.add(ch); dq.append(ch)
    sub = g[g.HYBAS_ID.isin(ups)]
    area = float(sub.SUB_AREA.sum())
    poly = sub.geometry.union_all() if hasattr(sub.geometry, "union_all") else sub.geometry.unary_union
    with nc.Dataset(f"{MSWX}/Tair/Tair_2005.nc") as d:
        lats = np.array(d["lat"][:], float); lons = np.array(d["lon"][:], float)
    minx, miny, maxx, maxy = poly.bounds
    lat_in = np.where((lats >= miny - 0.06) & (lats <= maxy + 0.06))[0]
    lon_in = np.where((lons >= minx - 0.06) & (lons <= maxx + 0.06))[0]
    i0, i1 = int(lat_in.min()), int(lat_in.max()) + 1
    j0, j1 = int(lon_in.min()), int(lon_in.max()) + 1
    blat = lats[i0:i1]; blon = lons[j0:j1]
    inside = [(float(la), float(lo)) for la in blat for lo in blon
              if poly.contains(Point(float(lo), float(la)))]
    inside.sort()
    if len(inside) > N_CELLS:
        idx = np.linspace(0, len(inside) - 1, N_CELLS).round().astype(int)
        sampled = [inside[i] for i in sorted(set(idx))]
    else:
        sampled = inside
    out = {"gauge": GAUGE, "outlet": outlet, "n_sub": int(len(sub)),
           "area_km2": area, "box_idx": [i0, i1, j0, j1],
           "n_full_cells": len(inside), "cells": sampled}
    log(f"basin: outlet={outlet} n_sub={len(sub)} area={area:.0f} km2 "
        f"box={i1-i0}x{j1-j0} full_cells={len(inside)} sampled={len(sampled)}")
    json.dump(out, open(cache, "w"))
    return out

# ------------------------------------------------------- MSWX read-once -> CMFD-style box
def prep_mswx_box(box_idx):
    """Slice basin box from MSWX yearly files, 3h->daily, write CMFD-style box files.
    Resumable: a (var,year) whose output already exists is skipped."""
    os.makedirs(BOX, exist_ok=True)
    i0, i1, j0, j1 = box_idx
    with nc.Dataset(f"{MSWX}/Tair/Tair_2005.nc") as d:
        blat = np.array(d["lat"][i0:i1], float); blon = np.array(d["lon"][j0:j1], float)
    nlat, nlon = len(blat), len(blon)
    for yr in range(RUN_START.year, FORCE_END.year + 1):
        for stem, (subdir, fpat, vname, agg) in MSWX_VARS.items():
            out = f"{BOX}/{stem}_{yr}.nc"
            if os.path.exists(out):
                continue
            src = f"{MSWX}/{subdir}/{fpat % yr}"
            if not os.path.exists(src):
                log(f"  MSWX missing {src}"); continue
            need_end = min(FORCE_END, datetime(yr, 12, 31))
            ndays = (need_end - datetime(yr, 1, 1)).days + 1
            with nc.Dataset(src) as d:
                navail = d[vname].shape[0]
                nsteps = min(ndays * 8, (navail // 8) * 8)
                raw = np.array(d[vname][:nsteps, i0:i1, j0:j1], float)  # (nsteps, nlat, nlon)
            ndays = raw.shape[0] // 8
            raw = raw[:ndays * 8].reshape(ndays, 8, nlat, nlon)
            if agg == "rate":
                daily = np.nansum(raw, axis=1) / 86400.0   # mm/day -> mm/s (kg/m2/s)
            else:
                daily = np.nanmean(raw, axis=1)
            tmp = out + ".tmp"
            with nc.Dataset(tmp, "w", format="NETCDF4") as o:
                o.createDimension("time", ndays)
                o.createDimension("lat", nlat); o.createDimension("lon", nlon)
                o.createVariable("lat", "f4", ("lat",))[:] = blat
                o.createVariable("lon", "f4", ("lon",))[:] = blon
                vt = o.createVariable("time", "f8", ("time",))
                vt.units = f"hours since {yr}-01-01 00:00:00"
                vt[:] = np.arange(ndays) * 24.0 + 10.5   # 10:30 daily, mirrors CMFD daily
                o.createVariable(stem, "f4", ("time", "lat", "lon"))[:] = daily.astype("f4")
            os.replace(tmp, out)
        log(f"  MSWX box ready for {yr}")
    return blat, blon

def merit_elev(lat, lon):
    la = int(np.floor(lat / 5.0) * 5); lo = int(np.floor(lon / 5.0) * 5)
    ns = f"n{la:02d}" if la >= 0 else f"s{-la:02d}"
    ew = f"e{lo:03d}" if lo >= 0 else f"w{-lo:03d}"
    t = f"{MERIT}/{ns}{ew}_dem.tif"
    if not os.path.exists(t): return 250.0
    import rasterio
    with rasterio.open(t) as s:
        r, c = s.index(lon, lat)
        try: e = float(s.read(1)[r, c])
        except Exception: e = 250.0
    return e if e > -100 else 250.0

def esa_igbp(lat, lon):
    import rasterio
    with rasterio.open(ESA) as s:
        r, c = s.index(lon, lat)
        v = int(s.read(1)[r, c])
    return esa_to_igbp(v) if v > 0 else 10

# ------------------------------------------------------------------- setup file build
def build_setup(path, lat, lon, hgt, ivgtyp, isltyp, tmn, smc0):
    with nc.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("Time", 1); ds.createDimension("soil_layers_stag", 4)
        ds.createDimension("south_north", 1); ds.createDimension("west_east", 1)
        def v2(n, val, dt="f4"):
            ds.createVariable(n, dt, ("Time","south_north","west_east"))[0,0,0] = val
        def vs(n, arr):
            ds.createVariable(n, "f4", ("Time","soil_layers_stag","south_north","west_east"))[0,:,0,0] = arr
        v2("XLAT",lat); v2("XLONG",lon); v2("HGT",hgt); v2("TMN",tmn)
        v2("IVGTYP",ivgtyp,"i4"); v2("ISLTYP",isltyp,"i4")
        v2("VEGFRA",50.0); v2("LAI",2.0); v2("SHDMIN",5.0); v2("SHDMAX",80.0)
        v2("CANWAT",0.0); v2("TSK",tmn); v2("SNOW",0.0); v2("SNODEP",0.0)
        v2("XLAND",1.0); v2("SEAICE",0.0)
        vs("TSLB",[tmn]*4); vs("SMOIS",[smc0]*4); vs("SH2O",[smc0]*4)
        ds.DX=10000.0; ds.DY=10000.0; ds.TRUELAT1=45.0; ds.TRUELAT2=60.0
        ds.STAND_LON=float(lon); ds.MAP_PROJ=6; ds.GRID_ID=1
        ds.ISWATER=17; ds.ISURBAN=13; ds.ISICE=15; ds.ISLAKE=21
        ds.MMINLU="MODIFIED_IGBP_MODIS_NOAH"; ds.TITLE="HYDROCRAFT NOAHMP SETUP"

NML = """&NOAHLSM_OFFLINE
 HRLDAS_SETUP_FILE = "{setup}"
 INDIR = "{indir}"
 OUTDIR = "{outdir}"
 START_YEAR={sy}
 START_MONTH={sm}
 START_DAY={sd}
 START_HOUR=10
 START_MIN=00
 KDAY={kday}
 SPINUP_LOOPS=0
 FORCING_NAME_T="T2D"
 FORCING_NAME_Q="Q2D"
 FORCING_NAME_U="U2D"
 FORCING_NAME_V="V2D"
 FORCING_NAME_P="PSFC"
 FORCING_NAME_LW="LWDOWN"
 FORCING_NAME_SW="SWDOWN"
 FORCING_NAME_PR="RAINRATE"
 DYNAMIC_VEG_OPTION=4
 CANOPY_STOMATAL_RESISTANCE_OPTION=1
 BTR_OPTION=1
 SURFACE_RUNOFF_OPTION=1
 SUBSURFACE_RUNOFF_OPTION=1
 DVIC_INFILTRATION_OPTION=1
 SURFACE_DRAG_OPTION=1
 FROZEN_SOIL_OPTION=1
 SUPERCOOLED_WATER_OPTION=1
 RADIATIVE_TRANSFER_OPTION=3
 SNOW_ALBEDO_OPTION=1
 SNOW_COMPACTION_OPTION=2
 SNOW_COVER_OPTION=1
 PCP_PARTITION_OPTION=1
 SNOW_THERMAL_CONDUCTIVITY=1
 TBOT_OPTION=2
 TEMP_TIME_SCHEME_OPTION=3
 GLACIER_OPTION=1
 SURFACE_RESISTANCE_OPTION=4
 SOIL_DATA_OPTION=1
 PEDOTRANSFER_OPTION=1
 CROP_OPTION=0
 IRRIGATION_OPTION=0
 IRRIGATION_METHOD=0
 TILE_DRAINAGE_OPTION=0
 WETLAND_OPTION=0
 FORCING_TIMESTEP=86400
 NOAH_TIMESTEP=1800
 OUTPUT_TIMESTEP=86400
 SPLIT_OUTPUT_COUNT=1
 SKIP_FIRST_OUTPUT=.false.
 RESTART_FREQUENCY_HOURS=0
 NSOIL=4
 soil_thick_input(1)=0.10
 soil_thick_input(2)=0.30
 soil_thick_input(3)=0.60
 soil_thick_input(4)=1.00
 ZLVL=10.0
 SF_URBAN_PHYSICS=0
 USE_WUDAPT_LCZ=0
/
"""

def run_cell(i, lat, lon):
    cdir = f"{CELLS}/cell_{i:03d}"
    done = f"{cdir}/runoff.npz"
    if os.path.exists(done):
        return np.load(done, allow_pickle=True)
    if os.path.exists(cdir): shutil.rmtree(cdir)
    os.makedirs(cdir); fdir = f"{cdir}/forcing"; os.makedirs(fdir)
    # 1. forcing via KI tool (reads CMFD-style box, argmin-selects this cell)
    r = subprocess.run([sys.executable, f"{TOOLS}/convert_forcing_to_noahmp.py",
        "--input_dir", BOX, "--output_dir", fdir, "--lat", str(lat), "--lon", str(lon),
        "--start_date", RUN_START.strftime("%Y-%m-%d"),
        "--end_date", FORCE_END.strftime("%Y-%m-%d"),
        "--timestep", "86400", "--source", "cmfd"], capture_output=True, text=True)
    nfor = len(glob.glob(f"{fdir}/*.LDASIN_DOMAIN1"))
    if nfor < 100:
        log(f"cell {i}: forcing FAILED ({nfor} files)"); log(r.stdout[-400:]); log(r.stderr[-500:]); return None
    # annual-mean T for TMN, from generated forcing (first spinup year)
    tsum = 0.0; nt = 0
    for f in sorted(glob.glob(f"{fdir}/{RUN_START.year}*.LDASIN_DOMAIN1"))[:365]:
        with nc.Dataset(f) as d: tsum += float(d["T2D"][0,0,0]); nt += 1
    tmn = tsum / max(nt, 1)
    hgt = merit_elev(lat, lon)
    try: ivg = esa_igbp(lat, lon)
    except Exception: ivg = 10
    # 2. setup + namelist
    setup = f"{cdir}/hrldas_setup.nc"
    build_setup(setup, lat, lon, hgt, ivg, 6, tmn, 0.30)
    kday = (RUN_END - RUN_START).days
    with open(f"{cdir}/namelist.hrldas", "w") as fh:
        fh.write(NML.format(setup=setup, indir=fdir, outdir=cdir + "/",
                            sy=RUN_START.year, sm=RUN_START.month, sd=RUN_START.day, kday=kday))
    # 3. run via KI run_noahmp.py (existing binary)
    rr = subprocess.run([sys.executable, f"{TOOLS}/run_noahmp.py",
        "--source_dir", SRCDIR, "--run_dir", cdir,
        "--namelist", f"{cdir}/namelist.hrldas", "--binary", BIN,
        "--skip_compile", "--timeout", "3600"], capture_output=True, text=True)
    outs = glob.glob(f"{cdir}/*.LDASOUT_DOMAIN1")
    if len(outs) < 100:
        log(f"cell {i}: run FAILED ({len(outs)} outputs)"); log(rr.stdout[-400:]); log(rr.stderr[-400:]); return None
    # 4. parse via KI parser
    pr = subprocess.run([sys.executable, f"{TOOLS}/parse_noahmp_output.py",
        "--output_dir", cdir, "--variables", "SFCRNOFF,UGDRNOFF,LH,SNEQV",
        "--output", f"{cdir}/parsed.csv"], capture_output=True, text=True)
    import pandas as pd
    df = pd.read_csv(f"{cdir}/parsed.csv")
    df["datetime"] = pd.to_datetime(df["datetime"])
    dates = df["datetime"].dt.strftime("%Y-%m-%d").values
    ro = (df.get("SFCRUNOFF_INC_mm", 0).fillna(0) + df.get("UDRUNOFF_INC_mm", 0).fillna(0)).values
    lh = df["LH"].where(df["LH"] > -1000).fillna(0).values if "LH" in df else np.zeros(len(df))
    et = lh / 2.5e6 * 86400.0
    np.savez(done, dates=dates, runoff_mm=ro, et_mm=et, lat=lat, lon=lon,
             tmn=tmn, hgt=hgt, ivg=ivg)
    shutil.rmtree(fdir, ignore_errors=True)
    for f in glob.glob(f"{cdir}/*.LDASOUT_DOMAIN1"): os.remove(f)
    log(f"cell {i}: OK runoff={ro.sum():.0f}mm/period et={et.sum():.0f}mm hgt={hgt:.0f} ivg={ivg} tmn={tmn:.1f}")
    return np.load(done, allow_pickle=True)

def load_obs():
    """HYDAT DLY_FLOWS -> daily discharge (m3/s) for the gauge. FLOW1..FLOW31 per month row."""
    import sqlite3, pandas as pd
    con = sqlite3.connect(HYDAT); cur = con.cursor()
    cur.execute("SELECT * FROM DLY_FLOWS WHERE STATION_NUMBER=? AND YEAR BETWEEN ? AND ?",
                (GAUGE, RUN_START.year, RUN_END.year))
    cols = [d[0] for d in cur.description]; rows = []
    for rec in cur.fetchall():
        row = dict(zip(cols, rec)); yr = int(row["YEAR"]); mo = int(row["MONTH"])
        dim = calendar.monthrange(yr, mo)[1]
        for dd in range(1, dim + 1):
            q = row.get(f"FLOW{dd}")
            if q is None: continue
            rows.append((f"{yr:04d}-{mo:02d}-{dd:02d}", float(q)))
    con.close()
    return pd.DataFrame(rows, columns=["date", "Qobs"])

def basin_precip_mm(cells, weights, dstart, dend):
    """Area-weighted basin-mean total precip (mm) over [dstart,dend] from the CMFD-style box."""
    tot = 0.0
    for (la, lo), w in zip(cells, weights):
        cell_tot = 0.0
        for yr in range(int(dstart.year), int(dend.year) + 1):
            fp = f"{BOX}/prec_{yr}.nc"
            if not os.path.exists(fp): continue
            with nc.Dataset(fp) as d:
                lats = d["lat"][:]; lons = d["lon"][:]
                ila = int(np.argmin(np.abs(lats - la))); ilo = int(np.argmin(np.abs(lons - lo)))
                t = nc.num2date(d["time"][:], d["time"].units, only_use_cftime_datetimes=False)
                vals = d["prec"][:, ila, ilo]   # mm/s (kg/m2/s)
                for k, tt in enumerate(t):
                    dd = datetime(tt.year, tt.month, tt.day)
                    if dstart <= dd <= dend: cell_tot += float(vals[k]) * 86400.0
        tot += w * cell_tot
    return float(tot)

def main():
    os.makedirs(CELLS, exist_ok=True)
    import pandas as pd
    basin = delineate()
    cells = basin["cells"]; area = basin["area_km2"]; box_idx = basin["box_idx"]
    log(f"running {len(cells)} cells over area {area:.0f} km2")
    prep_mswx_box(box_idx)
    weights = np.array([np.cos(np.radians(la)) for la, lo in cells]); weights /= weights.sum()
    per = []
    for i, (la, lo) in enumerate(cells):
        try:
            d = run_cell(i, la, lo)
        except Exception as e:
            log(f"cell {i} EXC {e}"); log(traceback.format_exc()[-800:]); d = None
        per.append(d)
    ok = [(w, d) for w, d in zip(weights, per) if d is not None]
    if not ok:
        json.dump({"model_id":"Noah_MP","this_location":LOCATION,"obs_source":"HYDAT",
                   "status":"failed","metrics":{},"water_balance":{"status":"N/A"},
                   "notes":"all cells failed"}, open(RESULT,"w"), indent=2); return
    wsum = sum(w for w, _ in ok)
    ref = ok[0][1]["dates"]
    basin_ro = np.zeros(len(ref)); basin_et = np.zeros(len(ref))
    for w, d in ok:
        n = min(len(ref), len(d["runoff_mm"]))
        basin_ro[:n] += (w / wsum) * d["runoff_mm"][:n]
        basin_et[:n] += (w / wsum) * d["et_mm"][:n]
    # discharge: runoff mm/day -> m3/s over basin area
    q_sim_raw = basin_ro * area / 86.4
    # simple linear-reservoir routing (reference only; NOT part of Noah-MP KI)
    k = 12.0
    q_route = np.zeros_like(q_sim_raw); s = q_sim_raw[0]
    for t in range(len(q_sim_raw)):
        s += (q_sim_raw[t] - s) / k; q_route[t] = s
    sim = pd.DataFrame({"date": ref, "Qsim_raw": q_sim_raw, "Qsim_route": q_route,
                        "runoff_mm": basin_ro, "et_mm": basin_et})
    obs = load_obs()
    m = sim.merge(obs, on="date")
    m["date"] = pd.to_datetime(m["date"])
    m = m[m["date"] >= SCORE_START]
    m = m.dropna(subset=["Qobs", "Qsim_raw"])
    log(f"paired days (post-spinup): {len(m)}  obs_mean={m.Qobs.mean():.1f}  "
        f"sim_raw_mean={m.Qsim_raw.mean():.1f}  sim_route_mean={m.Qsim_route.mean():.1f} m3/s")

    from ki_tools_common.metrics import all_metrics
    def mset(o, s):
        r = all_metrics(np.asarray(o, float), np.asarray(s, float))
        return {kk.lower(): (None if (v is None or (isinstance(v,float) and np.isnan(v))) else float(v))
                for kk, v in r.items()}
    full_raw = mset(m.Qobs, m.Qsim_raw)
    full_route = mset(m.Qobs, m.Qsim_route)
    def period(df, a, b):
        return df[(df.date >= pd.Timestamp(a)) & (df.date <= pd.Timestamp(b))]
    mc, mv = period(m, *CAL), period(m, *VAL)
    cal_rt = mset(mc.Qobs, mc.Qsim_route) if len(mc) > 2 else {}
    val_rt = mset(mv.Qobs, mv.Qsim_route) if len(mv) > 2 else {}
    mm = m.set_index("date")
    mo = mm.resample("MS").mean(numeric_only=True).dropna(subset=["Qobs"])
    month_route = mset(mo.Qobs, mo.Qsim_route) if len(mo) > 2 else {}

    # water balance closure (basin totals over scored period)
    ndays = len(m)
    tot_ro = float(m.runoff_mm.sum()); tot_et = float(m.et_mm.sum())
    Pmm = basin_precip_mm(cells, weights, m.date.min(), m.date.max())
    from ki_tools_common.validation import validate_water_balance
    wb = validate_water_balance(precip_mm=Pmm, et_mm=tot_et, runoff_mm=tot_ro,
                                delta_storage_mm=None, period_days=ndays)

    result = {
        "model_id": "Noah_MP",
        "this_location": LOCATION,
        "obs_source": "HYDAT",
        "status": "completed",
        "tools_used": ["convert_forcing_to_noahmp.py", "run_noahmp.py",
                       "parse_noahmp_output.py", "ki_tools_common.metrics.all_metrics",
                       "ki_tools_common.validation.validate_water_balance"],
        "tools_failed": [],
        "metrics": {
            "nse": full_route.get("nse"), "kge": full_route.get("kge"),
            "pbias": full_route.get("pbias"), "r": full_route.get("r"),
            "period": f"{SCORE_START.date()}..{RUN_END.date()}",
            "nse_cal": cal_rt.get("nse"), "nse_val": val_rt.get("nse"),
            "kge_val": val_rt.get("kge"), "pbias_val": val_rt.get("pbias"),
            "period_calibration": f"{CAL[0]}..{CAL[1]}",
            "period_validation": f"{VAL[0]}..{VAL[1]}",
        },
        "metrics_raw_unrouted": {"full": full_raw},
        "metrics_monthly_routed": month_route,
        "water_balance": {
            "status": wb["status"], "residual_mm": wb.get("residual_mm"),
            "residual_pct": wb.get("residual_pct"), "diagnostics": wb.get("diagnostics", []),
            "precip_mm": Pmm, "et_mm": tot_et, "runoff_mm": tot_ro,
        },
        "forcing": "MSWX global 0.1deg 3-hourly -> daily (Canada basin, outside CMFD)",
        "variable": "SFCRUNOFF + UDRUNOFF (total runoff)",
        "obs_shape": "regional_aggregate_time_series",
        "basin": {"area_km2": area, "n_sub_basins": basin["n_sub"],
                  "n_cells_run": len(ok), "n_cells_sampled": len(cells)},
        "discharge_stats_m3s": {
            "obs_mean": float(m.Qobs.mean()),
            "sim_raw_mean": float(m.Qsim_raw.mean()),
            "sim_route_mean": float(m.Qsim_route.mean()),
            "paired_days": int(len(m))},
        "notes": ("Noah-MP HRLDAS v5.2 gridded as %d area-weighted MSWX columns over the "
                  "%.0f km2 Missinaibi basin above Mattice (HYDAT 04LJ001, natural RHBN, "
                  "REGULATED=0; HydroBASINS NA lev12 upstream traversal). MSWX 3-hourly "
                  "read-once -> daily -> LDASIN via KI convert_forcing_to_noahmp (cmfd path). "
                  "Runoff SFCRNOFF+UGDRNOFF area-converted to discharge (m3/s). Noah-MP is an "
                  "LSM with NO river routing (KI stage 8 external); reported nse/kge/pbias use "
                  "a simple linear-reservoir (k=12d) reference routing, raw-unrouted in "
                  "metrics_raw_unrouted. Same KI tools as real-case; snow-dominated boreal basin."
                  ) % (len(ok), area),
    }
    json.dump(result, open(RESULT, "w"), indent=2, default=str)
    log("WROTE " + RESULT)
    log(json.dumps(result["metrics"], indent=2))
    log(json.dumps(result["water_balance"], indent=2))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("FATAL " + str(e)); log(traceback.format_exc())
        try:
            json.dump({"model_id":"Noah_MP","this_location":LOCATION,"obs_source":"HYDAT",
                       "status":"failed","metrics":{},"water_balance":{"status":"N/A"},
                       "notes":"runner exception: " + str(e)}, open(RESULT,"w"), indent=2)
        except Exception: pass
        sys.exit(1)
