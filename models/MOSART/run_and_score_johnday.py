#!/usr/bin/env python3
"""VERIFIER #1 (2nd location) — VIC->MOSART real-case at John Day R. @ McDonald Ferry, OR.

Consistency check for the MOSART real-case (which ran at 唐乃亥/Tangnaihai, upper
Yellow R, NSE 0.8367). MOSART-WM is a ROUTING model: it needs (1) a gridded runoff
field from an upstream land-surface model and (2) a domain grid whose river network
routes to the gauge. This runs the SAME sanctioned VIC->MOSART two-stage pipeline
(SKILL.md) at a DIFFERENT, non-China GRDC-Caravan basin, fully resumable, detached:

  s1  VIC flux      pre-computed by the VIC KI at this basin (2003-2014, 59 cells)  [resume: flux count]
  s2  gridded runoff  flux .txt -> gridded VIC nc -> convert_runoff_forcing (QOVER/QDRAI mm/s)  [resume: per year]
  s3  domain grid   build_mosart_grid.py from the VALIDATED VIC/Lohmann D8 (JDY)   [resume: file exists]
  s4  config + run   run_mosartwmpy.py (BMI, 2003-2014, 3h step, WM off)          [resume: output months]
  s5  parse + score  parse_mosart_output.py at the gauge cell; all_metrics vs GRDC Q

Location : John Day River at McDonald Ferry, OR  (GRDC_4115221, 45.5896,-120.4104, 19,771 km2)
Obs      : GRDC-Caravan Extension, var `streamflow` in mm/day -> m3/s via area/86.4
WM off   : the John Day is one of the longest FREE-FLOWING (unregulated) US rivers.
Score var= RIVER_DISCHARGE_OVER_LAND_LIQ (dag rank-1), obs_shape point_time_series.
Spin-up 2003-2004 (dropped); cal 2005-2009, val 2010-2014.

NOTE: tools/build_mosart_grid.py was reconstructed from its APPROVED reviewer diff
(codex rollout-2026-07-11T07-01-52) after the orchestrator KI-rollback (rsync
--delete on a REQUEST_CHANGES over edge-case robustness) wiped it post-real-case;
it is the identical tool that produced the Tangnaihai NSE 0.8367.
"""
import os, sys, glob, re, json, subprocess
from pathlib import Path

sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/MOSART/source/repo")

import numpy as np
import pandas as pd
import xarray as xr

BASE   = "KISSPATH_ROOT"
KI     = f"{BASE}/models/MOSART/knowledge_infrastructure"
D      = f"{BASE}/models/MOSART/detached/verify_1"
JD     = f"{BASE}/outputs/johnday_mcdonaldferry"
FLUXD  = f"{JD}/vic_result"
FLUXPRE = "johnday_mcdonaldferry_fluxes_"
RP     = f"{JD}/routing_param"
SOIL   = f"{JD}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt"
SRC_DIREC = f"{RP}/JDY_direc.txt"
SRC_XMASK = f"{RP}/JDY_xmask.txt"
SRC_FRAC  = f"{RP}/JDY_frac.txt"
OBS_NC = "KISSPATH_DATA/observed_data/dischargeandwatershed/GRDC-Caravan-extension-nc/timeseries/netcdf/grdc/GRDC_4115221.nc"
AREA_KM2 = 19771.2306292227     # GRDC attribute for this gauge
PY     = sys.executable

NCELL = 59
YR0, YR1 = 2003, 2014           # forcing/sim span (VIC flux availability)
CAL  = ("2005-01-01", "2009-12-31")
VAL  = ("2010-01-01", "2014-12-31")
FULL = ("2005-01-01", "2014-12-31")   # spin-up 2003-2004 dropped

os.makedirs(D, exist_ok=True)
RESULT = {
    "model_id": "MOSART",
    "this_location": "GRDC-Caravan Extension (5,357 global gauges + basin shapes)",
    "obs_source": "GRDC",
    "status": "failed",
    "tools_used": [], "tools_failed": [],
    "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
    "water_balance": {"status": "N/A", "residual_pct": None},
    "notes": "",
    "_detail": {"gauge": "GRDC_4115221 John Day R. @ McDonald Ferry, OR",
                "variable": "RIVER_DISCHARGE_OVER_LAND_LIQ", "obs_shape": "point_time_series",
                "nse_cal": None, "kge_cal": None, "nse_val": None, "kge_val": None,
                "pbias_val": None, "period_calibration": None, "period_validation": None,
                "sim_mean_m3s": None, "obs_mean_m3s": None, "scoring_cell": None},
}

def save(msg=None):
    if msg:
        RESULT["notes"] = (RESULT["notes"] + " | " + msg).strip(" |")
    with open(f"{D}/result.json", "w") as f:
        json.dump(RESULT, f, indent=1, ensure_ascii=False)
    print(f"[result.json] {RESULT['status']} :: {msg or ''}", flush=True)

def die(msg):
    RESULT["status"] = "failed"; save(msg); sys.exit(1)

# ============================================================ s1  VIC flux (pre-computed)
flux = [f for f in glob.glob(f"{FLUXD}/{FLUXPRE}*")
        if not os.path.basename(f).startswith("._")]
print(f"[s1] pre-computed VIC flux files: {len(flux)}/{NCELL}", flush=True)
if len(flux) < NCELL * 0.95:
    RESULT["tools_failed"].append(f"VIC flux: only {len(flux)}/{NCELL} present")
    die("insufficient VIC flux (upstream runoff) for this basin")
RESULT["tools_used"].append("VIC 5.x flux (upstream runoff — pre-computed by the VIC KI at this basin)")

# ============================================================ pad D8 with a NODATA border
# The John Day outlet at McDonald Ferry sits on the grid's north edge (the river flows
# N off-grid to the Columbia), so build_mosart_grid has NO inactive neighbour to host a
# terminal sink -> the outlet stays a dnID==-1 ocean cell whose RIVER_DISCHARGE is 0
# (the gauge-cell outflow trap, SKILL.md). Pad a 1-cell NODATA border on every side so
# the outlet's off-grid downstream lands on an inactive cell the tool converts to a sink,
# making the gauge a THROUGH-cell scoring the full basin discharge. Interior cell centers
# (and thus flux/runoff alignment) are unchanged.
DIREC = f"{D}/JDY_direc.txt"; XMASK = f"{D}/JDY_xmask.txt"; FRAC = f"{D}/JDY_frac.txt"
def _read_ascii(p):
    h = {}; rows = []
    for line in open(p):
        t = line.split()
        if t and t[0].lower() in ("ncols", "nrows", "xllcorner", "yllcorner", "cellsize", "nodata_value"):
            h[t[0].lower()] = float(t[1])
        elif t:
            rows.append([float(x) for x in t])
    return h, np.array(rows)
def _pad(src, dst, nod=0):
    h, a = _read_ascii(src); cs = h["cellsize"]
    pa = np.full((a.shape[0] + 2, a.shape[1] + 2), nod, dtype=float); pa[1:-1, 1:-1] = a
    with open(dst, "w") as f:
        f.write(f"ncols         {int(h['ncols'])+2}\n")
        f.write(f"nrows         {int(h['nrows'])+2}\n")
        f.write(f"xllcorner     {h['xllcorner']-cs}\n")
        f.write(f"yllcorner     {h['yllcorner']-cs}\n")
        f.write(f"cellsize      {cs}\n")
        f.write(f"NODATA_value  {nod}\n")
        for r in pa:
            f.write(" ".join(("%g" % v) for v in r) + "\n")
for s, d in ((SRC_DIREC, DIREC), (SRC_XMASK, XMASK), (SRC_FRAC, FRAC)):
    if not os.path.isfile(d):
        _pad(s, d)
print("[pad] wrote NODATA-bordered D8 grids to detached dir", flush=True)

# ============================================================ mesh (from D8 header)
def read_hdr(path):
    h = {}
    for line in open(path):
        p = line.split()
        if p and p[0].lower() in ("ncols", "nrows", "xllcorner", "yllcorner", "cellsize", "nodata_value"):
            h[p[0].lower()] = float(p[1])
    return h
H = read_hdr(DIREC)
NLON, NLAT, CS = int(H["ncols"]), int(H["nrows"]), H["cellsize"]
XLL, YLL = H["xllcorner"], H["yllcorner"]
LON = XLL + (np.arange(NLON) + 0.5) * CS          # ascending
LAT = YLL + (np.arange(NLAT) + 0.5) * CS          # ascending
lat_key = {round(v, 3): i for i, v in enumerate(LAT)}
lon_key = {round(v, 3): j for j, v in enumerate(LON)}
print(f"[mesh] {NLAT}x{NLON} @ {CS} deg; lat {LAT.min()}..{LAT.max()} lon {LON.min()}..{LON.max()}", flush=True)

FRE = re.compile(r"fluxes_(-?\d+\.?\d*)_(-?\d+\.?\d*)")

# ============================================================ s2  gridded runoff
RUN_DIR = f"{D}/runoff"; os.makedirs(RUN_DIR, exist_ok=True)
need_years = [y for y in range(YR0, YR1 + 1)
              if not os.path.isfile(f"{RUN_DIR}/runoff_{y}.nc")]
if need_years:
    print(f"===== s2 gridded runoff (years {need_years}) =====", flush=True)
    years = list(range(YR0, YR1 + 1))
    days = {y: pd.date_range(f"{y}-01-01", f"{y}-12-31", freq="D") for y in years}
    RUN = {y: np.zeros((len(days[y]), NLAT, NLON), "f4") for y in years}
    BAS = {y: np.zeros((len(days[y]), NLAT, NLON), "f4") for y in years}
    nmap = 0
    for f in flux:
        m = FRE.search(os.path.basename(f))
        if not m:
            continue
        la, lo = round(float(m.group(1)), 3), round(float(m.group(2)), 3)
        i, j = lat_key.get(la), lon_key.get(lo)
        if i is None or j is None:
            continue
        df = pd.read_csv(f, sep=r"\s+", skiprows=3, header=None)
        d = pd.to_datetime(dict(year=df[0].astype(int), month=df[1].astype(int),
                                day=df[2].astype(int)))
        ro, bf = df[16].values.astype("f4"), df[17].values.astype("f4")   # mm/day
        yr = d.dt.year.values
        for y in years:
            sel = yr == y
            if not sel.any():
                continue
            didx = (d[sel] - days[y][0]).dt.days.values
            ok = (didx >= 0) & (didx < len(days[y]))
            RUN[y][didx[ok], i, j] = ro[sel][ok]
            BAS[y][didx[ok], i, j] = bf[sel][ok]
        nmap += 1
    print(f"[s2] mapped {nmap} flux cells onto {NLAT}x{NLON} mesh", flush=True)
    if nmap < NCELL * 0.95:
        RESULT["tools_failed"].append(f"flux->mesh mapping: only {nmap}/{NCELL} cells aligned")
        die("flux cell centers did not align with the D8 mesh")
    for y in need_years:
        raw = f"{RUN_DIR}/_raw_{y}.nc"
        xr.Dataset(dict(RUNOFF=(["time", "lat", "lon"], RUN[y]),
                        BASEFLOW=(["time", "lat", "lon"], BAS[y])),
                   coords=dict(time=days[y], lat=LAT, lon=LON)).to_netcdf(raw)
        p = subprocess.run([PY, f"{KI}/tools/convert_runoff_forcing.py",
                            "--input", raw, "--output", f"{RUN_DIR}/runoff_{y}.nc",
                            "--source-type", "vic", "--surface-var", "RUNOFF",
                            "--subsurface-var", "BASEFLOW", "--source-units", "mm/day"],
                           capture_output=True, text=True)
        if p.returncode != 0:
            print(p.stdout[-800:], p.stderr[-800:], flush=True)
            RESULT["tools_failed"].append(f"convert_runoff_forcing.py y={y}: {p.stderr[-200:]}")
            die("convert_runoff_forcing failed")
        os.remove(raw)
        print(f"[s2] runoff_{y}.nc written", flush=True)
RESULT["tools_used"].append("tools/convert_runoff_forcing.py")

# ============================================================ s3  domain grid
GRID = f"{D}/mosart_grid.nc"
if not os.path.isfile(GRID):
    print("===== s3 build_mosart_grid =====", flush=True)
    p = subprocess.run([PY, f"{KI}/tools/build_mosart_grid.py",
                        "--direc", DIREC, "--xmask", XMASK, "--frac", FRAC,
                        "--elev-soil", SOIL, "--elev-cols", "3,4,22", "--output", GRID],
                       capture_output=True, text=True)
    print(p.stdout[-1000:], flush=True)
    if p.returncode != 0:
        print(p.stderr[-1500:], flush=True)
        RESULT["tools_failed"].append(f"build_mosart_grid.py: {p.stderr[-200:]}")
        die("build_mosart_grid failed")
pv = subprocess.run([PY, f"{KI}/tools/convert_grid_parameters.py",
                     "--input", GRID, "--validate-only"], capture_output=True, text=True)
print(pv.stdout[-500:], flush=True)
RESULT["tools_used"] += ["tools/build_mosart_grid.py (recovered from approved reviewer diff)",
                         "tools/convert_grid_parameters.py"]
gds = xr.open_dataset(GRID)
SC_LAT = float(gds.attrs["scoring_lat"]); SC_LON = float(gds.attrs["scoring_lon"])
NACT = int(gds.attrs.get("n_active_cells", 0))
gds.close()
RESULT["_detail"]["scoring_cell"] = f"({SC_LAT},{SC_LON})"
print(f"[s3] scoring/gauge cell = ({SC_LAT},{SC_LON}); n_active={NACT}", flush=True)

# ============================================================ s4  config + run
CFG = f"{D}/config.yaml"
OUT = f"{D}/mosart_out"
with open(CFG, "w") as f:
    f.write(f"""simulation:
  name: jdy_verify
  start_date: {YR0}-01-01
  end_date: {YR1}-12-31
  timestep: 10800
  subcycles: 3
  routing_iterations: 5
  log_level: WARNING
  log_to_std_out: false
  log_to_file: false
  restart_file: ~
  output_path: {OUT}
  output_resolution: 86400
  output_file_frequency: monthly
  output:
    - variable: runoff_land
      name: RIVER_DISCHARGE_OVER_LAND_LIQ
      long_name: main channel outflow
      units: m3/s
grid:
  path: {GRID}
  longitude: lon
  latitude: lat
  unmask_output: false
  variables:
    drainage_fraction: frac
    local_drainage_area: area
    total_drainage_area_multi: areaTotal
    total_drainage_area_single: areaTotal2
    id: ID
    nldas_id: NLDAS_ID
    downstream_id: dnID
    flow_direction: fdir
    hillslope_manning: nh
    subnetwork_manning: nt
    channel_manning: nr
    hillslope: hslp
    drainage_density: gxr
    subnetwork_slope: tslp
    subnetwork_width: twid
    channel_length: rlen
    channel_slope: rslp
    channel_width: rwid
    channel_floodplain_width: rwid0
    grid_channel_depth: rdep
    land_fraction: land_frac
runoff:
  read_from_file: true
  path: {RUN_DIR}/runoff_{{yyyy}}.nc
  longitude: lon
  latitude: lat
  time: time
  variables:
    surface_runoff: QOVER
    subsurface_runoff: QDRAI
    wetland_runoff: ~
water_management:
  enabled: false
""")

out_dir = f"{OUT}/jdy_verify"
done_last = os.path.isfile(f"{out_dir}/jdy_verify_{YR1}_12.nc")
if not done_last:
    print("===== s4 run_mosartwmpy (2003-2014) =====", flush=True)
    p = subprocess.run([PY, f"{KI}/tools/run_mosartwmpy.py", "--config", CFG,
                        "--output-json", f"{D}/run_summary.json"],
                       capture_output=True, text=True)
    print((p.stdout or "")[-1500:], flush=True)
    if p.returncode != 0:
        print("STDERR:", (p.stderr or "")[-2000:], flush=True)
        RESULT["tools_failed"].append(f"run_mosartwmpy.py: rc={p.returncode}")
        die("mosartwmpy run failed")
else:
    print("[s4] mosart output already complete, skip", flush=True)
RESULT["tools_used"].append("tools/run_mosartwmpy.py (mosartwmpy BMI)")

# ============================================================ s5  parse + score
print("===== s5 parse + score =====", flush=True)
csv = f"{D}/discharge_gauge.csv"
p = subprocess.run([PY, f"{KI}/tools/parse_mosart_output.py",
                    "--input-dir", out_dir, "--output", csv,
                    "--variable", "RIVER_DISCHARGE_OVER_LAND_LIQ",
                    "--mode", "point", "--lat", str(SC_LAT), "--lon", str(SC_LON)],
                   capture_output=True, text=True)
print((p.stdout or "")[-800:], flush=True)
if p.returncode != 0:
    print(p.stderr[-1500:], flush=True)
    RESULT["tools_failed"].append(f"parse_mosart_output.py: {p.stderr[-200:]}")
    die("parse failed")
RESULT["tools_used"].append("tools/parse_mosart_output.py")

sim = pd.read_csv(csv, parse_dates=["time"]).set_index("time")["RIVER_DISCHARGE_OVER_LAND_LIQ"]
sim.index = sim.index.normalize()
sim = sim.groupby(level=0).mean()

# --- obs: GRDC-Caravan streamflow (mm/day) -> m3/s ---
ods = xr.open_dataset(OBS_NC)
odate = pd.to_datetime(ods["date"].values)
oflow_mmday = ods["streamflow"].values.astype("float64")
ods.close()
obs = pd.Series(oflow_mmday * AREA_KM2 / 86.4, index=odate.normalize())
obs = obs[np.isfinite(obs.values)]

from ki_tools_common.metrics import all_metrics
def score(a, b, label="headline", period_role="full"):
    j = pd.concat([obs.rename("o"), sim.rename("s")], axis=1, join="inner").dropna()
    j = j[(j.index >= a) & (j.index <= b)]
    if len(j) < 2:
        return None, 0
    # pass dates (j has a DatetimeIndex) + label so the shared scorer captures a DATED series (step 5):
    # a dateless capture caps a temporal metric at series_only and can never be trusted.
    m = all_metrics(j["o"].values, j["s"].values,
                    dates=j.index.values, label=label,
                    meta={"period_role": period_role, "unit": "m3/s"})
    return {(k.lower() if k != "r" else "r"):
            (None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 4))
            for k, v in m.items()}, len(j)

mf, nf = score(*FULL, label="headline", period_role="full")
mc, nc = score(*CAL, label="cal", period_role="cal")
mv, nv = score(*VAL, label="val", period_role="val")
print(f"[s5] full n={nf} {mf}", flush=True)
print(f"[s5] cal  n={nc} {mc}", flush=True)
print(f"[s5] val  n={nv} {mv}", flush=True)
if not mf:
    RESULT["tools_failed"].append("no overlapping sim/obs days")
    die("no overlap between sim and obs")

RESULT["metrics"].update(nse=mf["nse"], r=mf["r"], kge=mf["kge"], pbias=mf["pbias"],
                         period=f"{FULL[0]}..{FULL[1]}")
if mc:
    RESULT["_detail"].update(nse_cal=mc["nse"], kge_cal=mc["kge"],
                             period_calibration=f"{CAL[0]}..{CAL[1]}")
if mv:
    RESULT["_detail"].update(nse_val=mv["nse"], kge_val=mv["kge"], pbias_val=mv["pbias"],
                             period_validation=f"{VAL[0]}..{VAL[1]}")
sim_mean = float(sim[(sim.index >= FULL[0]) & (sim.index <= FULL[1])].mean())
obs_mean = float(obs[(obs.index >= FULL[0]) & (obs.index <= FULL[1])].mean())
RESULT["_detail"]["sim_mean_m3s"] = round(sim_mean, 1)
RESULT["_detail"]["obs_mean_m3s"] = round(obs_mean, 1)
RESULT["status"] = "completed"
save(f"VIC->MOSART routed daily Q at John Day R. @ McDonald Ferry (GRDC_4115221) "
     f"gauge cell ({SC_LAT},{SC_LON}); sim_mean {sim_mean:.1f} vs obs_mean {obs_mean:.1f} m3/s; "
     f"full NSE {mf['nse']}, KGE {mf['kge']}, r {mf['r']}, PBIAS {mf['pbias']}; "
     f"cal NSE {mc['nse'] if mc else None} / val NSE {mv['nse'] if mv else None}. "
     f"Grid built by build_mosart_grid.py from the VALIDATED VIC/Lohmann JDY D8 "
     f"({NACT} active cells, single outlet at McDonald Ferry). "
     f"WM off (John Day is free-flowing/unregulated). Spin-up 2003-2004 dropped. "
     f"obs = GRDC-Caravan streamflow mm/day -> m3/s via area {AREA_KM2:.0f} km2 /86.4.")
print("DONE", flush=True)
