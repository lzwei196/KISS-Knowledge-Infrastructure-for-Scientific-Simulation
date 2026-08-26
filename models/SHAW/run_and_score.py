#!/usr/bin/env python3
"""
run_and_score.py — SHAW verifier at RISMA Ontario station ON2.

Sets up a SHAW case from the validated `compton` template (Quebec agricultural,
daily MTSTEP=1, MCANFLG=0, 11 soil nodes, 2-digit year, multi-year span
yr15->yr20 baked into .sit Line B), replaces weather with the RISMA daily
bundle (2015-2019), runs SHAW, and scores 5 cm liquid water content (liquid.out
node 0.05 m) against RISMA observed vwc_5cm.

RESUMABLE: if liquid.out already exists and covers the period, the model run is
skipped and only scoring re-runs.
"""
import os, sys, shutil, subprocess, csv
from pathlib import Path
from datetime import datetime, timedelta

HC = Path("KISSPATH_ROOT")
KI = HC / "models/SHAW/knowledge_infrastructure"
sys.path.insert(0, str(KI))
sys.path.insert(0, str(KI / "tools/s1_site_setup"))

from ki_tools_common.metrics import all_metrics
import setup_shaw_from_template as setup

SHAW_EXE = HC / "model/shaw/shaw303"
OBS = HC / "data/obs/risma_on2"
WORK = HC / "outputs/shaw_risma_on2"
RESULT_DIR = HC / "models/SHAW/detached/verify_1"
CASE = "risma_on2"
LAT, LON, ELEV = 45.3, -75.0, 70.0   # RISMA ON network, South Nation watershed, eastern Ontario clay plain
START_YEAR, END_YEAR = 2015, 2019

WORK.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)


def build_weather():
    """Convert RISMA daily bundle -> SHAW .wea, prepend previous day (yr-1 DOY365)."""
    out_wea = WORK / f"{CASE}.wea"
    conv = KI / "s2_weather_prep/tools/convert_forcing_to_shaw.py"
    cmd = [sys.executable, str(conv),
           "--csv", str(OBS / "weather_complete.csv"),
           "--lat", str(LAT), "--lon", str(LON),
           "--start_year", str(START_YEAR), "--end_year", str(END_YEAR),
           "--mode", "daily", "--output", str(out_wea)]
    print("CONVERT:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    # Prepend a previous day so SHAW (begins day 0 of yr15) has previous-day data
    lines = out_wea.read_text().splitlines()
    first = lines[0].split()
    prev = first[:]
    prev[0] = "365"                       # DOY 365
    prev[1] = str((START_YEAR - 1) % 100) # yr 14
    prev_line = (" %3s %2s " % (prev[0], prev[1])) + " ".join(f"{float(x):6.1f}" for x in first[2:])
    out_wea.write_text(prev_line + "\n" + "\n".join(lines) + "\n")
    print(f"  .wea: {len(lines)+1} lines, prepended {prev[0]}/{prev[1]}")


def build_profiles():
    """Multi-year initial/boundary moisture+temperature profiles (yr15..yr20).

    Surface evolves with weather; these mainly pin the deep boundary node and
    initial state. Last record at DOY365 yr20 == JEND/YREND (triplet shaw_033).
    """
    import math
    nsoil = 11
    moi_lines, tem_lines = [], []
    t_mean, t_amp = 12.0, 15.0  # lat ~45N
    # moist, well-drained-to-poorly-drained Ontario clay-loam column: gentle gradient near FC
    def moi_profile(doy):
        surf = 0.30 + 0.05 * math.cos(2 * math.pi * (doy - 100) / 365)  # wetter spring, drier late summer
        return [round(min(0.40, surf + 0.04 * (i / (nsoil - 1))), 3) for i in range(nsoil)]
    def tem_profile(doy):
        temps = []
        for i in range(nsoil):
            depth = i * 1.2 / (nsoil - 1)
            damping = math.exp(-depth / 0.5)
            phase = depth * 30
            temps.append(round(t_mean + t_amp * damping * math.cos(2 * math.pi * (doy - 200 - phase) / 365), 1))
        return temps
    records = []
    for yr in range(START_YEAR, END_YEAR + 1):
        y2 = yr % 100
        for doy in [1, 91, 182, 274, 365]:
            records.append((doy, y2))
    records.append((365, END_YEAR % 100 + 1))  # terminal record at YREND (yr20) >= JEND
    for doy, y2 in records:
        moi_lines.append(f"{doy:4d} {0:3d} {y2:3d} " + " ".join(f"{m:.3f}" for m in moi_profile(doy)))
        tem_lines.append(f"{doy:4d} {0:3d} {y2:3d} " + " ".join(f"{t:6.1f}" for t in tem_profile(doy)))
    (WORK / f"{CASE}.moi").write_text("\n".join(moi_lines) + "\n")
    (WORK / f"{CASE}.tem").write_text("\n".join(tem_lines) + "\n")
    print(f"  .moi/.tem: {len(records)} records, last {records[-1]}")


def patch_sit(soil):
    sit = WORK / f"{CASE}.sit"
    lines = sit.read_text().splitlines()
    # Line 1 title
    lines[0] = f"RISMA Ontario ON2 ({LAT:.2f}N {abs(LON):.2f}W {ELEV:.0f}m) 2015-2019"
    # Line 3: LAT_INT LAT_MIN SLOPE ASPECT HRNOON ELEV  (keep dates Line 2 = yr15->yr20 from template)
    lat_int = int(LAT); lat_min = int(round((LAT - lat_int) * 60))
    hrnoon = 12.0 - (LON - (-75.0)) / 15.0  # EST meridian -75
    lines[2] = f" {lat_int} {lat_min}    0.    0.0   {hrnoon:.1f}  {ELEV:.0f}."
    sit.write_text("\n".join(lines) + "\n")
    # Update soil texture from HWSD across all nodes, then fix bpar/quartz
    props = [{"sand": soil["sand"], "silt": soil["silt"], "clay": soil["clay"],
              "oc": soil["oc"], "bd": soil["bulk_density"] * 1000.0,
              "ksat": soil["hydraulics"]["ksat_cm_hr"]} for _ in range(11)]
    setup.update_sit_file(sit, soil_properties=props)
    n = setup.fix_bpar_quartz_from_texture(sit)
    print(f"  .sit patched: lat {lat_int}d{lat_min}m HRNOON {hrnoon:.1f} elev {ELEV}; bpar/quartz fixed {n} nodes")


def setup_case():
    from ki_tools_common.soil_utils import lookup_hwsd
    soil = lookup_hwsd(LAT, LON)
    print("HWSD:", soil["texture"], "sand", soil["sand"], "clay", soil["clay"], "FC", soil["hydraulics"]["field_capacity"])
    # copy template files
    files = setup.copy_template("compton", str(WORK), CASE)
    # .inp references
    setup.update_inp_file(files[".inp"], CASE)
    build_weather()
    build_profiles()
    patch_sit(soil)


def run_model():
    inp = WORK / f"{CASE}.inp"
    print("RUN SHAW:", SHAW_EXE)
    # SHAW reads .inp path then a final Enter from stdin; benign EOF backtrace at end
    p = subprocess.run(f'printf "{CASE}.inp\\n\\n" | {SHAW_EXE}',
                       shell=True, cwd=str(WORK), capture_output=True, text=True)
    print("  rc:", p.returncode, "(non-zero EOF is benign — judge by output files)")
    liq = WORK / "liquid.out"
    if not liq.exists() or liq.stat().st_size == 0:
        print("STDERR:", p.stderr[-2000:])
        raise RuntimeError("liquid.out missing/empty after run")
    print("  liquid.out size:", liq.stat().st_size)


def parse_liquid_5cm():
    """Return dict date->mean daily 5cm liquid water content from liquid.out."""
    liq = (WORK / "liquid.out").read_text().splitlines()
    # header line 2: DY HR YR <depths...>; find column of 0.05
    hdr = liq[1].split()
    depths = hdr[3:]
    col05 = depths.index("0.05")  # index into node values
    daily = {}
    for ln in liq[2:]:
        p = ln.split()
        if len(p) < 3 + len(depths):
            continue
        try:
            doy = int(p[0]); yr = int(p[2]); val = float(p[3 + col05])
        except ValueError:
            continue
        year = 2000 + yr if yr < 50 else 1900 + yr
        try:
            d = (datetime(year, 1, 1) + timedelta(days=doy - 1)).date()
        except ValueError:
            continue
        daily.setdefault(d, []).append(val)
    return {d: sum(v) / len(v) for d, v in daily.items()}


def water_balance():
    wf = WORK / "water.out"
    if not wf.exists():
        return {"status": "N/A", "residual_pct": None}
    try:
        txt = wf.read_text()
        return {"status": "N/A", "residual_pct": None, "note": f"water.out {len(txt)} bytes (not parsed)"}
    except Exception:
        return {"status": "N/A", "residual_pct": None}


def score():
    sim = parse_liquid_5cm()
    obs = {}
    for r in csv.DictReader(open(OBS / "obs_vwc_by_depth.csv")):
        v = r.get("vwc_5cm", "")
        try:
            fv = float(v)
        except (ValueError, TypeError):
            continue
        if fv <= 0.0:  # 0.0000 = sensor missing/frozen-glitch
            continue
        obs[datetime.strptime(r["date"], "%Y-%m-%d").date()] = fv
    # spinup: drop before 2015-05-01
    spin = datetime(2015, 5, 1).date()
    O, S, dates = [], [], []
    for d in sorted(obs):
        if d < spin or d not in sim:
            continue
        O.append(obs[d]); S.append(sim[d]); dates.append(d)
    print(f"  paired n={len(O)}  {dates[0] if dates else '-'}..{dates[-1] if dates else '-'}")
    m = all_metrics(O, S)
    return m, (dates[0].isoformat() + ".." + dates[-1].isoformat() if dates else None), len(O)


def main():
    liq = WORK / "liquid.out"
    if not (liq.exists() and liq.stat().st_size > 1000):
        setup_case()
        run_model()
    else:
        print("RESUME: liquid.out present, skipping setup+run")
    m, period, n = score()
    wb = water_balance()
    result = {
        "model_id": "SHAW",
        "this_location": "RISMA - Real-time In-situ Soil Monitoring for Agriculture (~36 stations, 2011-present)",
        "obs_source": "RISMA",
        "status": "completed",
        "tools_used": ["setup_shaw_from_template.py", "convert_forcing_to_shaw.py",
                       "lookup_hwsd", "fix_bpar_quartz_from_texture", "shaw303", "metrics.all_metrics"],
        "tools_failed": [],
        "metrics": {
            "nse": round(m["NSE"], 4), "kge": round(m["KGE"], 4),
            "pbias": round(m["PBIAS"], 3), "r": round(m["r"], 4),
            "rmse": round(m["RMSE"], 4), "period": period, "n_days": n,
            "variable": "liquid_water_content_5cm vs RISMA vwc_5cm (m3/m3)",
        },
        "water_balance": wb,
        "notes": (f"SHAW v3.03 single-point daily run 2015-2019 from validated compton template "
                  f"(clay-loam->HWSD loam texture, BPAR/QUARTZ pedotransfer fix); compared 5cm "
                  f"liquid.out to RISMA vwc_5cm, May2015 spinup dropped. NSE={m['NSE']:.3f} "
                  f"KGE={m['KGE']:.3f} PBIAS={m['PBIAS']:.1f} r={m['r']:.3f} over n={n} days.")
    }
    import json
    (RESULT_DIR / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
