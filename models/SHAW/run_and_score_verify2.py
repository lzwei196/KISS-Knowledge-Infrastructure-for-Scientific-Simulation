#!/usr/bin/env python3
"""
run_and_score_verify2.py — SHAW VERIFIER at Manitoba MAWP station 544 (Alexander Prairie).

Different location from verify_1 (RISMA ON2 soil moisture). Here the obs variable is
soil_temperature_C (Canadian Soil T/SM dataset, MAWP DailyAll bundle). We set up a SHAW
case from the validated `compton` daily template (MTSTEP=1, MCANFLG=0 prairie/bare,
11 soil nodes, 2-digit year), replace weather with station-544 daily weather over the
natural annual freeze-thaw cycle 2019-11-02 .. 2020-11-01 (Winter2020 + Summer2020),
run SHAW, and score 5 cm soil temperature (temp.out node 0.05 m) vs MAWP
Avg_Soil_TP5_TempC.

YEAR REMAP: the compton template's run window is anchored at 2-digit year 15. To reuse
it untouched we shift all obs/weather dates back exactly 4 years (2019->2015, 2020->2016;
both leap structures preserved so DOY mapping is identical) so SHAW emits yr15/yr16. When
pairing simulated against observed we add 4 years back to recover the real calendar date.

RESUMABLE: if temp.out already exists and is non-trivial, setup+run are skipped and only
scoring re-runs.
"""
import os, sys, shutil, subprocess, csv, math, json
from pathlib import Path
from datetime import datetime, timedelta

HC = Path("/mnt/disk1/Hydrocraft_server")
KI = HC / "models/SHAW/knowledge_infrastructure"
sys.path.insert(0, str(KI))
sys.path.insert(0, str(KI / "tools/s1_site_setup"))

from ki_tools_common.metrics import all_metrics
from ki_tools_common.soil_utils import lookup_hwsd
import setup_shaw_from_template as setup

SHAW_EXE = HC / "model/shaw/shaw303"
MAWP = Path("/mnt/disk4/observedST-SM/soil_temperatureand_soil_moisture_canada/manitoba")
WORK = HC / "outputs/shaw_manitoba_544_verify2"
RESULT_DIR = HC / "models/SHAW/detached/verify_2"
CASE = "manitoba544"
STN = 544
LAT, LON, ELEV = 49.81, -100.37, 460.0   # MAWP station 544, Alexander, Manitoba (prairie grassland)
YEAR_SHIFT = 4                            # real year - 4 = SHAW label year (2019->2015 -> yr15)

# MAWP DailyAll column indices (0-based) — quoted CSV, addressed by index not name
C_TMSTAMP, C_STNID = 0, 2
C_MAXAIR, C_MINAIR, C_AVGRH = 6, 8, 10
C_PLUVIO, C_AVGWS, C_TOTRS = 15, 18, 27
C_ST5 = 29                               # Avg_Soil_TP5_TempC

WORK.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)


def _f(x):
    try:
        v = float(str(x).strip().strip('"'))
        if v != v:   # NaN
            return None
        return v
    except (ValueError, TypeError):
        return None


def read_station_obs():
    """Return {real_date: soil_T5_C} and a daily-weather list for station 544 over the
    natural annual cycle (Winter2020 + Summer2020 bundles)."""
    obs_t5 = {}
    wea = {}   # real_date -> dict of weather fields
    for bundle in ("Winter2020DailyAll.csv", "Summer2020DailyAll.csv"):
        with open(MAWP / bundle, newline="") as fh:
            rdr = csv.reader(fh)
            next(rdr)  # header
            for row in rdr:
                if len(row) <= C_ST5:
                    continue
                if str(row[C_STNID]).strip().strip('"') != str(STN):
                    continue
                ts = str(row[C_TMSTAMP]).strip().strip('"')[:10]
                try:
                    d = datetime.strptime(ts, "%Y-%m-%d").date()
                except ValueError:
                    continue
                t5 = _f(row[C_ST5])
                if t5 is not None:
                    obs_t5[d] = t5
                wea[d] = {
                    "tmax": _f(row[C_MAXAIR]), "tmin": _f(row[C_MINAIR]),
                    "rh": _f(row[C_AVGRH]), "precip": _f(row[C_PLUVIO]),
                    "wind": _f(row[C_AVGWS]), "srad": _f(row[C_TOTRS]),
                }
    return obs_t5, wea


def build_weather_csv(wea):
    """Write a SHAW-ready daily CSV (dates shifted -4yr) for convert_forcing_to_shaw."""
    csv_path = WORK / "weather_544.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "tmax_C", "tmin_C", "precip_mm", "srad_MJ_m2", "wind_m_s", "rh_pct"])
        for d in sorted(wea):
            r = wea[d]
            sd = d.replace(year=d.year - YEAR_SHIFT)
            w.writerow([sd.isoformat(),
                        "" if r["tmax"] is None else r["tmax"],
                        "" if r["tmin"] is None else r["tmin"],
                        0.0 if r["precip"] is None else max(0.0, r["precip"]),
                        "" if r["srad"] is None else r["srad"],
                        "" if r["wind"] is None else r["wind"],
                        "" if r["rh"] is None else r["rh"]])
    return csv_path


def build_wea(csv_path, first_doy, first_yr2):
    out_wea = WORK / f"{CASE}.wea"
    conv = KI / "s2_weather_prep/tools/convert_forcing_to_shaw.py"
    cmd = [sys.executable, str(conv), "--csv", str(csv_path),
           "--lat", str(LAT), "--lon", str(LON),
           "--mode", "daily", "--output", str(out_wea)]
    print("CONVERT:", " ".join(cmd)); subprocess.run(cmd, check=True)
    # Prepend previous day (triplet shaw_030: .wea must start 1 day before JSTART)
    lines = out_wea.read_text().splitlines()
    first = lines[0].split()
    prev = first[:]
    pd = first_doy - 1
    pyr = first_yr2
    if pd < 1:
        pyr -= 1; pd = 365
    prev[0] = str(pd); prev[1] = str(pyr)
    prev_line = (" %3s %2s " % (prev[0], prev[1])) + " ".join(f"{float(x):7.1f}" for x in first[2:])
    out_wea.write_text(prev_line + "\n" + "\n".join(lines) + "\n")
    print(f"  .wea: {len(lines)+1} lines, prepended {prev[0]}/{prev[1]}; first real {first[0]}/{first[1]}")


def build_profiles(records):
    """records: list of (doy, yr2). Generate seasonal moisture+temperature profiles
    for lat ~49.8N prairie loamy-sand column. Terminal record pins JEND boundary."""
    nsoil = 11
    t_mean, t_amp = 5.0, 20.0   # 45-55N branch
    def moi_profile(doy):
        surf = 0.22 + 0.06 * math.cos(2 * math.pi * (doy - 100) / 365)  # wetter spring
        return [round(min(0.32, max(0.08, surf + 0.03 * (i / (nsoil - 1)))), 3) for i in range(nsoil)]
    def tem_profile(doy):
        temps = []
        for i in range(nsoil):
            depth = i * 1.2 / (nsoil - 1)
            damping = math.exp(-depth / 0.5)
            phase = depth * 30
            temps.append(round(t_mean + t_amp * damping * math.cos(2 * math.pi * (doy - 200 - phase) / 365), 1))
        return temps
    moi_lines, tem_lines = [], []
    for doy, y2 in records:
        moi_lines.append(f"{doy:4d} {0:3d} {y2:3d} " + " ".join(f"{m:.3f}" for m in moi_profile(doy)))
        tem_lines.append(f"{doy:4d} {0:3d} {y2:3d} " + " ".join(f"{t:6.1f}" for t in tem_profile(doy)))
    (WORK / f"{CASE}.moi").write_text("\n".join(moi_lines) + "\n")
    (WORK / f"{CASE}.tem").write_text("\n".join(tem_lines) + "\n")
    print(f"  .moi/.tem: {len(records)} records {records[0]}..{records[-1]}")


def patch_sit(soil, jstart, yrstart, jend, yrend):
    sit = WORK / f"{CASE}.sit"
    lines = sit.read_text().splitlines()
    lines[0] = f"MAWP Station 544 Alexander MB ({LAT:.2f}N {abs(LON):.2f}W {ELEV:.0f}m) 2019-2020 [yr15/16 remap]"
    # Line B = JSTART HRSTART YRSTART JEND YREND (decoded from compton "1 0 15 365 20")
    lines[1] = f"   {jstart}  0 {yrstart} {jend}  {yrend}"
    lat_int = int(LAT); lat_min = int(round((LAT - lat_int) * 60))
    hrnoon = 12.0 - (LON - (-90.0)) / 15.0   # CST meridian -90
    lines[2] = f" {lat_int} {lat_min}    0.    0.0   {hrnoon:.1f}  {ELEV:.0f}."
    sit.write_text("\n".join(lines) + "\n")
    props = [{"sand": soil["sand"], "silt": soil["silt"], "clay": soil["clay"],
              "oc": soil["oc"], "bd": soil["bulk_density"] * 1000.0,
              "ksat": soil["hydraulics"]["ksat_cm_hr"]} for _ in range(11)]
    setup.update_sit_file(sit, soil_properties=props)
    n = setup.fix_bpar_quartz_from_texture(sit)
    print(f"  .sit patched: lat {lat_int}d{lat_min}m HRNOON {hrnoon:.1f} elev {ELEV}; bpar/quartz fixed {n} nodes")


def setup_case(wea):
    soil = lookup_hwsd(LAT, LON)
    print("HWSD:", soil["texture"], "sand", soil["sand"], "clay", soil["clay"], "FC", soil["hydraulics"]["field_capacity"])
    files = setup.copy_template("compton", str(WORK), CASE)
    setup.update_inp_file(files[".inp"], CASE)
    csv_path = build_weather_csv(wea)
    # first shifted date
    first_real = min(wea); first_shift = first_real.replace(year=first_real.year - YEAR_SHIFT)
    fd = first_shift.timetuple().tm_yday; fy = first_shift.year % 100
    build_wea(csv_path, fd, fy)
    last_real = max(wea); last_shift = last_real.replace(year=last_real.year - YEAR_SHIFT)
    ld = last_shift.timetuple().tm_yday; ly = last_shift.year % 100
    # profile records: start, year-end, next-year start, terminal exactly at JEND=(ld,ly) per shaw_033
    recs = [(fd, fy), (365, fy), (1, fy + 1), (ld, ly)]
    seen = set(); recs2 = []
    for r in recs:
        if r not in seen:
            seen.add(r); recs2.append(r)
    build_profiles(recs2)
    patch_sit(soil, jstart=fd, yrstart=fy, jend=ld, yrend=ly)


def run_model():
    inp = WORK / f"{CASE}.inp"
    for old in WORK.glob("*.out"):   # clear stale outputs so SHAW does not prompt to overwrite
        old.unlink()
    print("RUN SHAW:", SHAW_EXE)
    p = subprocess.run(f'printf "{CASE}.inp\\n\\n" | {SHAW_EXE}',
                       shell=True, cwd=str(WORK), capture_output=True, text=True)
    print("  rc:", p.returncode, "(non-zero EOF benign — judge by output files)")
    to = WORK / "temp.out"
    if not to.exists() or to.stat().st_size == 0:
        print("STDOUT:", p.stdout[-1500:]); print("STDERR:", p.stderr[-1500:])
        raise RuntimeError("temp.out missing/empty after run")
    print("  temp.out size:", to.stat().st_size)


def parse_temp_5cm():
    """Return {real_date: daily-mean 5cm soil T} from temp.out, mapping yr label +4 -> real."""
    lines = (WORK / "temp.out").read_text().splitlines()
    hdr = lines[1].split()           # DY HR YR 0.00 0.02 0.05 ...
    depths = hdr[3:]
    col05 = depths.index("0.05")
    daily = {}
    for ln in lines[2:]:
        p = ln.split()
        if len(p) < 3 + len(depths):
            continue
        try:
            doy = int(p[0]); yr = int(p[2]); val = float(p[3 + col05])
        except ValueError:
            continue
        real_year = 2000 + yr + YEAR_SHIFT if yr < 50 else 1900 + yr + YEAR_SHIFT
        try:
            d = (datetime(real_year, 1, 1) + timedelta(days=doy - 1)).date()
        except ValueError:
            continue
        daily.setdefault(d, []).append(val)
    return {d: sum(v) / len(v) for d, v in daily.items()}


def score(obs_t5):
    sim = parse_temp_5cm()
    spin = datetime(2019, 12, 1).date()   # ~1 month spinup from Nov start
    O, S, dates = [], [], []
    for d in sorted(obs_t5):
        if d < spin or d not in sim:
            continue
        O.append(obs_t5[d]); S.append(sim[d]); dates.append(d)
    print(f"  paired n={len(O)}  {dates[0] if dates else '-'}..{dates[-1] if dates else '-'}")
    m = all_metrics(O, S)
    return m, (dates[0].isoformat() + ".." + dates[-1].isoformat() if dates else None), len(O)


def water_balance():
    wf = WORK / "water.out"
    if not wf.exists() or wf.stat().st_size == 0:
        return {"status": "N/A", "residual_pct": None}
    return {"status": "N/A", "residual_pct": None, "note": f"water.out {wf.stat().st_size} bytes (soil-T verifier, WB not scored)"}


def main():
    obs_t5, wea = read_station_obs()
    print(f"obs: {len(obs_t5)} soil-T5 days, {len(wea)} weather days, "
          f"{min(wea)}..{max(wea)}")
    to = WORK / "temp.out"
    if not (to.exists() and to.stat().st_size > 1000):
        setup_case(wea)
        run_model()
    else:
        print("RESUME: temp.out present, skipping setup+run")
    m, period, n = score(obs_t5)
    wb = water_balance()
    result = {
        "model_id": "SHAW",
        "this_location": "Canadian Soil T/SM",
        "obs_source": "ObservedSoilTSM",
        "status": "completed" if n > 0 else "failed",
        "tools_used": ["setup_shaw_from_template.py", "convert_forcing_to_shaw.py",
                       "lookup_hwsd", "fix_bpar_quartz_from_texture", "shaw303", "metrics.all_metrics"],
        "tools_failed": [],
        "metrics": {
            "nse": round(m["NSE"], 4), "kge": round(m["KGE"], 4),
            "pbias": round(m["PBIAS"], 3), "r": round(m["r"], 4),
            "rmse": round(m["RMSE"], 4), "period": period, "n_days": n,
            "variable": "soil_temperature_5cm: temp.out 0.05m vs MAWP-544 Avg_Soil_TP5_TempC (C)",
        },
        "water_balance": wb,
        "notes": (f"SHAW v3.03 single-point daily run from validated compton template at MAWP "
                  f"station 544 (Alexander, MB prairie, loamy_sand HWSD, BPAR/QUARTZ pedotransfer "
                  f"fix). Annual freeze-thaw cycle 2019-11..2020-11 (dates shifted -4yr to reuse "
                  f"template yr15/16 window). Compared 5cm temp.out to MAWP Avg_Soil_TP5_TempC, "
                  f"Dec2019 spinup dropped. NSE={m['NSE']:.3f} KGE={m['KGE']:.3f} "
                  f"PBIAS={m['PBIAS']:.1f} r={m['r']:.3f} RMSE={m['RMSE']:.2f}C over n={n} days.")
    }
    (RESULT_DIR / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
