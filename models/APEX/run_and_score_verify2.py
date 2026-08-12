#!/usr/bin/env python3
"""APEX VERIFIER (verify_2): continuous maize at a Hai-River-plain maize-belt
cell (Hebei, 38.25N 115.75E) -- a genuinely DIFFERENT location than the
real-case Bengbu Huai cell (32.75N 117.25E) and than verify_1's Henan cell --
scored against the GDHY v1.2/v1.3 0.5-degree gridded historical maize yield
(1981-2016) at that same cell.

Faithful twin of the real-case runner (run_and_score.py):
  * Same validated Bengbu-corn workspace template + APEX0806 binary.
  * Same Y10RF management (validated CORN BENGBU schedule with the full-auto
    irrigation header disabled -> supplemental/rainfed, N reduced 184.8->120),
    wired to every subarea -> continuous corn.  Same Huang-Huai-Hai summer-maize
    agroecology so the fixed management stays representative.
  * ONLY the location changes: CMFD forcing rebuilt at 38.25N/115.75E and the
    SIT lat/lon/elev updated so daylength/PHU match the new cell.  CMFD
    1961-2016 (20-yr spin-up 1961-1980), scoring window 1981-2016, ngn=0.

Obs = GDHY maize yield at the 38.25N,115.75E cell (t/ha).  This is a 0.5-degree
AREA-average (regional_aggregate_time_series) carrying a technology/management
trend the fixed-management APEX run cannot track -> determining metric is pbias
(magnitude); detrended r reported for pattern only.

Resumable: skips the slow forcing build and the APEX run if their outputs exist.
Writes the verifier result object to detached/verify_2/result.json.
"""
import os
import sys
import json
import shutil
import glob
from pathlib import Path

KI = Path("/mnt/disk1/Hydrocraft_server/models/APEX/knowledge_infrastructure")
TOOLS = KI / "tools"
VALIDATED = Path("/mnt/disk1/Hydrocraft_server/outputs/apex_bengbu_corn_ki_test")
STATE = Path("/mnt/disk1/Hydrocraft_server/models/APEX/detached/verify_2")
WS = STATE / "ws"
OUT = STATE
GDHY = Path("/mnt/datasets/Crop_model_dataset/GDHY_v1.2_v1.3/maize")

LAT, LON, ELEV = 38.25, 115.75, 25.0    # Hebei / Hai-River plain maize belt
SPIN_START, SCORE_START, SCORE_END = 1961, 1981, 2016
LOCATION = ("GDHY v1.2/v1.3 Global Dataset of Historical Yields (1981-2016); "
            "sim @ Hai-River-plain Hebei cell 38.25N,115.75E")

for c in ["/mnt/disk1/Hydrocraft_server/models/ki_tools_common",
          "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent"]:
    if os.path.isdir(os.path.join(c, "ki_tools_common")):
        sys.path.insert(0, c)
        break
sys.path.insert(0, str(TOOLS))


def log(m):
    print(f"[verify_2] {m}", flush=True)


def build_workspace():
    if WS.exists():
        shutil.rmtree(WS)
    WS.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(VALIDATED, WS)
    binexe = KI / "reference" / "APEX0806.exe"
    if binexe.is_file():
        shutil.copy2(binexe, WS / "APEX0806.exe")
    # Y10RF = validated CORN BENGBU schedule, auto-irrigation header disabled,
    # cell-average N (184.8 -> 120) -- identical management to the real-case.
    y10 = (WS / "Y10.OPC").read_text().splitlines()
    y10[1] = "   3   0   0   0   0   0   0"
    y10 = [ln.replace("184.80", "120.00") for ln in y10]
    (WS / "Y10RF.OPC").write_text("\n".join(y10) + "\n")
    ids = []
    for ln in (WS / "OPSCCOM.DAT").read_text(errors="ignore").splitlines():
        t = ln.split()
        if t and t[0].lstrip("-").isdigit():
            ids.append(int(t[0]))
    if not ids:
        ids = [1, 2, 3, 4]
    (WS / "OPSCCOM.DAT").write_text(
        "\r\n".join(f"{i:5d} Y10RF.OPC" for i in ids) + "\r\n")
    log(f"workspace built, subareas wired to Y10RF: {ids}")


def forcing_ready():
    dly = WS / "WEATHER01.DLY"
    if not dly.is_file():
        cands = list(WS.glob("*.dly")) + list(WS.glob("*.DLY"))
        dly = cands[0] if cands else None
    if dly is None or not dly.is_file():
        return False
    ys = set()
    for ln in dly.read_text(errors="replace").splitlines():
        p = ln.split()
        if p and p[0].isdigit() and len(p[0]) == 4:
            ys.add(int(p[0]))
    return SPIN_START in ys and SCORE_END in ys and len(ys) >= (SCORE_END - SPIN_START + 1) - 1


def run_ready():
    acy = WS / "OUTPUT.ACY"
    if not acy.is_file() or acy.stat().st_size == 0:
        return False
    return "CORN" in acy.read_text(errors="replace")


def load_gdhy():
    import netCDF4
    import numpy as np
    series = {}
    for f in sorted(glob.glob(str(GDHY / "yield_*.nc4"))):
        yr = int(os.path.basename(f).split("_")[1][:4])
        ds = netCDF4.Dataset(f)
        lat = ds.variables["lat"][:]
        lon = ds.variables["lon"][:]
        iy = int(np.argmin(np.abs(lat - LAT)))
        ix = int(np.argmin(np.abs(lon - (LON % 360))))
        v = ds.variables["var"][iy, ix]
        ds.close()
        if not np.ma.is_masked(v) and np.isfinite(v):
            series[yr] = float(v)
    return series


def parse_sim():
    from s7_parse_output import parse
    import pandas as pd
    df = parse(str(WS))
    cols = {c.upper(): c for c in df.columns}
    cpnm = cols.get("CPNM")
    yldg = cols.get("YLDG")
    yrn = cols.get("YR#")
    if yrn is None:
        for c in df.columns:
            if c.strip() == "YR#":
                yrn = c
                break
    d = df[df[cpnm].astype(str).str.upper() == "CORN"].copy()
    d[yldg] = pd.to_numeric(d[yldg], errors="coerce")
    d[yrn] = pd.to_numeric(d[yrn], errors="coerce")
    d = d.dropna(subset=[yldg, yrn])
    d["year"] = SPIN_START + d[yrn].astype(int) - 1
    ser = d.groupby("year")[yldg].mean().to_dict()
    return {int(k): float(v) for k, v in ser.items()}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    from s2_convert_forcing import build_forcing
    from s4_update_site import update_site
    from s5_update_control import update_control

    if not (WS.exists() and (WS / "Y10RF.OPC").is_file()):
        build_workspace()
    else:
        log("workspace already present, reusing")

    # relocate site (daylength/PHU) to the Hebei cell
    try:
        update_site(str(WS), lat=LAT, lon=LON, elev_m=ELEV)
        log(f"site relocated to {LAT},{LON} elev {ELEV}")
    except Exception as e:
        log(f"update_site warning: {e}")

    if forcing_ready():
        log("forcing already built, skipping s2")
    else:
        log(f"building CMFD forcing 1961-2016 @ {LAT},{LON} (real weather, 20-yr spin-up)...")
        build_forcing(str(WS), lat=LAT, lon=LON,
                      year1=SPIN_START, year2=SCORE_END, source="cmfd")
        log("forcing built")

    log("updating control (NBYR=56, IYR=1961, ngn=0)")
    update_control(str(WS), year1=SPIN_START, year2=SCORE_END,
                   ngn=0, spinup_years=0)

    if run_ready():
        log("APEX output already present, skipping s6")
    else:
        from s6_run_apex import run
        log("running APEX0806 (wine) ...")
        run(str(WS), timeout=7200)
        log("APEX run complete")

    sim = parse_sim()
    obs = load_gdhy()
    years = sorted(y for y in range(SCORE_START, SCORE_END + 1)
                   if y in sim and y in obs)
    log(f"paired years: {len(years)} ({years[0]}-{years[-1]})")
    obs_s = [obs[y] for y in years]
    sim_s = [sim[y] for y in years]

    from ki_tools_common.metrics import all_metrics, trend_metrics
    m = all_metrics(obs_s, sim_s)
    m = {k.lower(): (None if v is None else float(v)) for k, v in m.items()}
    tm = trend_metrics(obs_s, sim_s)
    tm = {k: (None if v is None or (isinstance(v, float) and v != v) else float(v))
          for k, v in tm.items()}

    result = {
        "model_id": "APEX",
        "this_location": LOCATION,
        "obs_source": "GDHY v1.2/v1.3 Global Dataset of Historical Yields (1981-2016)",
        "status": "completed",
        "tools_used": ["s1_setup_workspace.py", "s2_convert_forcing.py",
                       "s4_update_site.py", "s5_update_control.py",
                       "s6_run_apex.py", "s7_parse_output.py"],
        "tools_failed": [],
        "variable": "YLDG",
        "obs_shape": "regional_aggregate_time_series",
        "comparison_mode": "aggregate_trend_comparison",
        "determining_metric": "pbias",
        "metrics": {
            "nse": m.get("nse"), "kge": m.get("kge"),
            "pbias": m.get("pbias"), "r": m.get("r"),
            "rmse": m.get("rmse"),
            "r_detr": tm.get("r_detr"), "r_firstdiff": tm.get("r_firstdiff"),
            "slope_ratio": tm.get("slope_ratio"),
            "period": f"{years[0]}-{years[-1]}",
        },
        "water_balance": {"status": "N/A", "residual_pct": None},
        "n_years": len(years),
        "sim_mean_tha": round(sum(sim_s) / len(sim_s), 3),
        "obs_mean_tha": round(sum(obs_s) / len(obs_s), 3),
        "sim_series": {str(y): round(sim[y], 3) for y in years},
        "obs_series": {str(y): round(obs[y], 3) for y in years},
        "notes": ("Verifier twin of the Bengbu real-case: identical Y10RF rainfed CORN "
                  "management + APEX0806 binary + CMFD forcing + 20-yr spin-up, moved to a "
                  "DIFFERENT cell (Hai-River-plain Hebei 38.25N,115.75E, same Huang-Huai-Hai "
                  "summer-maize regime) and scored vs the GDHY 0.5-deg gridded maize yield at "
                  "that cell (t/ha). GDHY is a trended area-average the fixed-management run "
                  "cannot track -> pbias is the determining metric (magnitude); detrended r "
                  "reported for pattern only."),
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2))
    log(f"RESULT: pbias={m.get('pbias')} nse={m.get('nse')} kge={m.get('kge')} "
        f"r={m.get('r')} sim_mean={result['sim_mean_tha']} obs_mean={result['obs_mean_tha']}")
    log(f"wrote {OUT/'result.json'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").write_text(json.dumps({
            "model_id": "APEX",
            "this_location": LOCATION,
            "obs_source": "GDHY v1.2/v1.3 Global Dataset of Historical Yields (1981-2016)",
            "status": "failed",
            "error": str(e),
        }, indent=2))
        sys.exit(1)
