#!/usr/bin/env python3
"""VIC -> MOSART consistency verifier #3 at 奴下 (Nuxia), Yarlung Tsangpo / upper
Brahmaputra (gauge 94109). Tibetan-Plateau, monsoon-fed alpine basin — a river system
entirely distinct from the Tangnaihai real-case (Yellow), Wangjiaba verify_2 (Huai) and
John Day verify_1 (USA).

Same sanctioned VIC->MOSART two-stage pipeline as the Tangnaihai real-case and the
Wangjiaba verify_2 runner: a VALIDATED VIC/Lohmann D8 network -> mosartwmpy domain grid
(build_mosart_grid.py), VIC per-cell runoff/baseflow gridded + unit-converted
(convert_runoff_forcing.py) -> mosartwmpy BMI run -> parse+score at the gauge cell.

Obs note: the GRDC Asia-Region daily export (250 stations) contains NO Yarlung Tsangpo /
Brahmaputra gauge with data (the Songhua HAERBIN stub 2106500 is empty), so this verifier
uses the basin's native long observed series 94109 (奴下, 1970-2013, m3/s) — the same obs
the VIC KI delineated the basin against. This mirrors verify_1 (Caravan) / verify_2
(HUAIH-51030) using their basins' native obs.

Assets:
  D8 network : outputs/nuxia_yarlung/routing_param/NX_{direc,xmask,frac}.txt
               (single -88 outlet, 406 active cells == 406 VIC flux cells)
  VIC flux   : outputs/nuxia_yarlung/vic_result/nuxia_yarlung_fluxes_*.txt
               (VIC 5.0.1, daily, 1980-1995; cols 16=OUT_RUNOFF 17=OUT_BASEFLOW mm/day, skiprows=3)
  elevation  : outputs/nuxia_yarlung/vic_temp/soil/SOIL_PARAM_COMPLETE.txt (cols 3,4,22)
  obs        : data/obs/NX/94109_nuxia.txt (tab, utf-8, cols dates,Q m3/s)

WM disabled (Yarlung above Nuxia is quasi-natural for 1980-1995; Zangmu dam post-2014).
Spin-up 1980 (dropped); cal 1981-1988, val 1989-1995. Score at grid scoring_lat/scoring_lon.
Resumable: grid/runoff/mosart outputs are skipped if already present.
"""
import os, sys, glob, re, json, subprocess
from pathlib import Path

sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/ki_tools_common")

import numpy as np
import pandas as pd
import xarray as xr

BASE = "/mnt/disk1/Hydrocraft_server"
KI   = f"{BASE}/models/MOSART/knowledge_infrastructure"
D    = f"{BASE}/models/MOSART/detached/verify_3"
RD   = f"{BASE}/outputs/nuxia_yarlung/routing_param"          # D8 network
RC   = f"{BASE}/outputs/nuxia_yarlung"                        # VIC flux + soil
FLUXDIR = f"{RC}/vic_result"
SOIL = f"{RC}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt"
OBS  = f"{BASE}/data/obs/NX/94109_nuxia.txt"
PY   = sys.executable

YR0, YR1 = 1980, 1995
CAL  = ("1981-01-01", "1988-12-31")
VAL  = ("1989-01-01", "1995-12-31")
FULL = ("1981-01-01", "1995-12-31")

os.makedirs(D, exist_ok=True)
RESULT = {
    "model_id": "MOSART", "this_location": "Nuxia (奴下), Yarlung Tsangpo / upper Brahmaputra",
    "obs_source": "native obs 94109 (奴下); GRDC Asia export has no Yarlung/Brahmaputra gauge with data",
    "status": "failed", "tools_used": [], "tools_failed": [],
    "metrics": {"nse": None, "kge": None, "pbias": None, "r": None,
                "nse_cal": None, "kge_cal": None, "nse_val": None,
                "kge_val": None, "pbias_val": None, "period": None},
    "water_balance": {"status": "N/A", "residual_pct": None},
    "notes": "",
}

def save(msg=None):
    if msg:
        RESULT["notes"] = (RESULT["notes"] + " | " + msg).strip(" |")
    with open(f"{D}/result.json", "w") as f:
        json.dump(RESULT, f, indent=1, ensure_ascii=False)
    print(f"[result.json] {RESULT['status']} :: {msg or ''}", flush=True)

def die(msg):
    RESULT["status"] = "failed"; save(msg); sys.exit(1)

# ============================================================ flux inventory
flux = [f for f in glob.glob(f"{FLUXDIR}/nuxia_yarlung_fluxes_*")
        if not os.path.basename(f).startswith("._") and f.endswith(".txt")]
print(f"[s1] VIC flux files: {len(flux)}", flush=True)
if len(flux) < 100:
    die(f"too few VIC flux files ({len(flux)})")
RESULT["tools_used"].append("VIC 5 flux (upstream runoff, precomputed 1980-1995)")

# ============================================================ mesh from D8 header
def read_hdr(path):
    h = {}
    for line in open(path):
        p = line.split()
        if p and p[0].lower() in ("ncols","nrows","xllcorner","yllcorner","cellsize","nodata_value"):
            h[p[0].lower()] = float(p[1])
    return h
H = read_hdr(f"{RD}/NX_direc.txt")
NLON, NLAT, CS = int(H["ncols"]), int(H["nrows"]), H["cellsize"]
XLL, YLL = H["xllcorner"], H["yllcorner"]
LON = XLL + (np.arange(NLON) + 0.5) * CS
LAT = YLL + (np.arange(NLAT) + 0.5) * CS
lat_key = {round(v, 3): i for i, v in enumerate(LAT)}
lon_key = {round(v, 3): j for j, v in enumerate(LON)}
FRE = re.compile(r"fluxes_(-?\d+\.?\d*)_(-?\d+\.?\d*)")

# ============================================================ s2 gridded runoff
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
    print(f"[s2] mapped {nmap}/{len(flux)} flux cells onto {NLAT}x{NLON} mesh", flush=True)
    for y in need_years:
        raw = f"{RUN_DIR}/_raw_{y}.nc"
        xr.Dataset(dict(RUNOFF=(["time","lat","lon"], RUN[y]),
                        BASEFLOW=(["time","lat","lon"], BAS[y])),
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

# ============================================================ s3 domain grid
GRID = f"{D}/mosart_grid.nc"
if not os.path.isfile(GRID):
    print("===== s3 build_mosart_grid =====", flush=True)
    p = subprocess.run([PY, f"{KI}/tools/build_mosart_grid.py",
                        "--direc", f"{RD}/NX_direc.txt", "--xmask", f"{RD}/NX_xmask.txt",
                        "--frac", f"{RD}/NX_frac.txt", "--elev-soil", SOIL,
                        "--elev-cols", "3,4,22", "--output", GRID],
                       capture_output=True, text=True)
    print(p.stdout[-800:], flush=True)
    if p.returncode != 0:
        print(p.stderr[-1500:], flush=True)
        RESULT["tools_failed"].append(f"build_mosart_grid.py: {p.stderr[-200:]}")
        die("build_mosart_grid failed")
pv = subprocess.run([PY, f"{KI}/tools/convert_grid_parameters.py",
                     "--input", GRID, "--validate-only"], capture_output=True, text=True)
print(pv.stdout[-400:], flush=True)
RESULT["tools_used"] += ["tools/build_mosart_grid.py", "tools/convert_grid_parameters.py"]
gds = xr.open_dataset(GRID)
SC_LAT = float(gds.attrs["scoring_lat"]); SC_LON = float(gds.attrs["scoring_lon"])
try:
    NACT = int(gds.attrs.get("n_active_cells", 0))
except Exception:
    NACT = 0
gds.close()
print(f"[s3] scoring/gauge cell = ({SC_LAT},{SC_LON}); active cells={NACT}", flush=True)

# ============================================================ s4 config + run
CFG = f"{D}/config.yaml"
OUT = f"{D}/mosart_out"
with open(CFG, "w") as f:
    f.write(f"""simulation:
  name: nx_verify3
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

out_dir = f"{OUT}/nx_verify3"
done_last = os.path.isfile(f"{out_dir}/nx_verify3_{YR1}_12.nc")
if not done_last:
    print("===== s4 run_mosartwmpy (1980-1995) =====", flush=True)
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

# ============================================================ s5 parse + score
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

try:
    obs_raw = pd.read_csv(OBS, sep="\t", encoding="utf-8")
except Exception:
    obs_raw = pd.read_csv(OBS, sep="\t", encoding="latin-1")
obs = obs_raw.copy()
obs["t"] = pd.to_datetime(obs["dates"], errors="coerce")
obs["Q"] = pd.to_numeric(obs["Q"], errors="coerce")
obs = obs.dropna(subset=["t"])
obs = obs[obs["Q"] > -90].set_index("t")["Q"]
obs.index = obs.index.normalize()
obs = obs.groupby(level=0).mean()

from ki_tools_common.metrics import all_metrics
def score(a, b, label="headline", period_role="full"):
    j = pd.concat([obs, sim], axis=1, join="inner").dropna()
    j = j[(j.index >= a) & (j.index <= b)]
    if len(j) < 2:
        return None, 0
    # dated capture via the shared scorer (step 5): j has a DatetimeIndex
    m = all_metrics(j.iloc[:, 0].values, j.iloc[:, 1].values,
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
if mf:
    RESULT["metrics"].update(nse=mf["nse"], r=mf["r"], kge=mf["kge"], pbias=mf["pbias"])
if mc:
    RESULT["metrics"].update(nse_cal=mc["nse"], kge_cal=mc["kge"])
if mv:
    RESULT["metrics"].update(nse_val=mv["nse"], kge_val=mv["kge"], pbias_val=mv["pbias"])
RESULT["metrics"]["period"] = f"{FULL[0]}..{FULL[1]} (cal {CAL[0]}..{CAL[1]}, val {VAL[0]}..{VAL[1]})"
RESULT["status"] = "completed" if mf else "failed"

if mf:
    sim_mean = float(sim[(sim.index >= FULL[0]) & (sim.index <= FULL[1])].mean())
    obs_mean = float(obs[(obs.index >= FULL[0]) & (obs.index <= FULL[1])].mean())
    save(f"VIC->MOSART routed daily Q at Nuxia gauge cell ({SC_LAT},{SC_LON}); "
         f"sim_mean {sim_mean:.0f} vs obs_mean {obs_mean:.0f} m3/s; "
         f"full NSE {mf['nse']}, r {mf['r']}, KGE {mf['kge']}, PBIAS {mf['pbias']}. "
         f"Grid built by build_mosart_grid.py from the validated VIC/Lohmann NX D8 network "
         f"({NACT} active cells, single outlet). WM disabled (Yarlung above Nuxia quasi-natural "
         f"1980-1995). spinup {YR0}. Distinct river system (Brahmaputra/Yarlung, Tibetan Plateau) "
         f"vs Yellow real-case / Huai verify_2 / John Day verify_1. GRDC Asia export has no "
         f"Yarlung gauge with data -> basin's native obs 94109 used.")
else:
    save("scoring produced no overlapping obs/sim window")
print("DONE", flush=True)
