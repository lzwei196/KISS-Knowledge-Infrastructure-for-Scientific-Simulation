#!/usr/bin/env python3
"""Score the ALREADY-COMPLETED WRF-Hydro verify_2 run (Laoguan He @ Xixia, GRDC 2182250).

The real WRF-Hydro binary ran end-to-end 1985-07-01 .. 1991-11-09 (2323/2375 daily
CHRTOUT = 97.8%; diag_hydro confirms a live run, no crash -- the detached process was
externally killed at the tail). Rather than wipe and redo the ~3 h run, we score the
existing real-model output: it already spans spinup (1985 H2) + calibration (1986-1988)
+ nearly all of validation (1989 .. 1991-11-09). We reuse the verify_2 runner's OWN
outlet-selection / extraction / metric / water-balance functions verbatim; the only
adjustment is that the water-balance endpoint is set to the last SIMULATED day instead
of the nominal END (1991-12-31), whose LDASOUT was never written.
"""
import json
import glob
import datetime as _dt
from pathlib import Path

import run_and_score_verify2 as R   # module-level import; main() is __main__-guarded

RUN = R.RUN
STATE_DIR = R.STATE_DIR


def main():
    # last simulated day from the CHRTOUT set
    chrt = sorted(glob.glob(str(RUN / "*.CHRTOUT_DOMAIN1")))
    last_tag = Path(chrt[-1]).name[:8]
    last_day = _dt.date(int(last_tag[:4]), int(last_tag[4:6]), int(last_tag[6:8]))
    R.END = last_day                       # so water_balance() reads an existing LDASOUT
    R.log(f"=== SCORE-ONLY: {len(chrt)} CHRTOUT, last simulated day {last_day} ===")

    # record the full pipeline that produced the on-disk artifacts
    R.TOOLS_USED.extend([
        "s1_domain/define_lambert_domain.py",
        "s2_geo_em/build_geo_em.py",
        "s3_wrfinput/build_wrfinput.py",
        "s4_fulldom/build_fulldom_hires.py",
        "s5_soil_properties/build_soil_properties.py",
        "s6_groundwater/build_groundwater.py",
        "s8_forcing/cmfd_to_ldasin.py",
        "s9_namelists/generate_namelists.py",
        "s10_execution/run_wrfhydro.py",
    ])

    idx, outlet = R.pick_outlet()
    scored, merged = R.extract_and_score(idx)
    wb, comp = R.water_balance()

    result = {
        "model_id": "WRF_Hydro",
        "this_location": ("GRDC Asia-Region Daily Discharge Export "
                          "(250 stations, 2026-05-11 download)"),
        "obs_source": ("GRDC Asia-Region Daily Discharge Export "
                       "(250 stations, 2026-05-11 download)"),
        "status": "completed",
        "tools_used": [], "tools_failed": [],
        "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
        "water_balance": {"status": wb.get("status", "N/A"),
                          "residual_pct": wb.get("residual_pct"),
                          "residual_mm": wb.get("residual_mm"),
                          "components": comp},
    }

    m, cv = scored
    cal, val, full = cv["calibration"], cv["validation"], cv["full"]
    result["metrics"] = {
        "nse": round(float(m["NSE"]), 4),
        "kge": round(float(m["KGE"]), 4),
        "pbias": round(float(m["PBIAS"]), 2),
        "r": round(float(m["r"]), 4),
        "period": (f"{merged.index.min():%Y-%m-%d}..{merged.index.max():%Y-%m-%d} "
                   f"({len(merged)} paired daily values; 1985-H2 discarded as spinup; "
                   f"tail 1991-11-10..12-31 not simulated -- run externally "
                   f"truncated at 97.8%)"),
        "nse_cal": round(float(cal["NSE"]), 4), "kge_cal": round(float(cal["KGE"]), 4),
        "pbias_cal": round(float(cal["PBIAS"]), 2), "r_cal": round(float(cal["r"]), 4),
        "nse_val": round(float(val["NSE"]), 4), "kge_val": round(float(val["KGE"]), 4),
        "pbias_val": round(float(val["PBIAS"]), 2), "r_val": round(float(val["r"]), 4),
        "n_cal": int(cal["n"]), "n_val": int(val["n"]), "n_full": int(full["n"]),
        "period_calibration": f"{R.CAL[0]}..{R.CAL[1]}",
        "period_validation": f"{R.VAL[0]}..1991-11-09",
        "sim_mean_m3s": round(float(merged["Q_sim"].mean()), 3),
        "obs_mean_m3s": round(float(merged["Q_obs"].mean()), 3),
    }
    result["outlet"] = outlet
    result["published_area_km2"] = R.PUBLISHED_AREA_KM2
    result["gauge"] = {"grdc_no": 2182250, "river": "LAOGUAN HE", "station": "XIXIA",
                       "country": "CN", "lat": R.GAUGE_LAT, "lon": R.GAUGE_LON}
    result["domain_rebuilt"] = True
    result["sanitation"] = R.SANITATION
    result["ki_defects_worked_around"] = [
        "D1 generate_namelists KHOUR off-by-one vs forcing span (dt_v044)",
        "D2 SKILL.md documents extract_discharge --gauge_lat/--min_order and "
        "find_gauge_feature(); neither exists on disk (only argmax find_outlet_feature)",
        "D3 hydro.namelist template hard-codes CHRTOUT_GRID=1 / RTOUT_DOMAIN=1",
        "D4 dt_v036 water-soil-type on land cells + dt_v005 GREENFRAC=0 -> "
        "crash-avoidance sanitation of the DOMAIN NetCDF outputs",
    ]
    result["notes"] = (
        "WRF-Hydro v5.2.0 standalone (NoahMP + gridded diffusive-wave routing) verifier "
        "#2 at Laoguan He @ Xixia (GRDC 2182250, Qinling south slope, Han/Danjiang "
        "headwater, humid subtropical China, published 3,418 km2) -- a THIRD distinct "
        "climate vs the regulated-arid N-China real-case (Zijingguan) and humid-"
        "continental verify_1 (Berounka, Czech). Basin delineated from LOCAL MERIT-Hydro "
        "dir/upa (upa-snap = 3,421 km2 vs published 3,418; reverse-D8 trace polygonized "
        "to laoguan_basin.shp). DOMAIN built from scratch by KI tools s1-s6 @1 km on "
        "china_dem_90m + HWSD (96x101 LSM, 384x404 routing @250 m, max Strahler order 4); "
        "forcing = this basin's own CMFD V2.0 3hr->hourly LDASIN via cmfd_to_ldasin.py "
        "(57,024 files). Physics is the KI STOCK Config A (RUNOFF_OPTION=3 Schaake96, "
        "channel_option=3 diffusive wave, GWBASESWCRT=1, UDMP_OPT=0, rst_typ=0); "
        "REFKDT=0.8 baked into build_soil_properties, GW bucket left STOCK -- an "
        "UNCALIBRATED stock-parameter run matching the verify_1 convention. The real "
        "WRF-Hydro binary ran end-to-end 1985-07-01..1991-11-09 (2323/2375 daily CHRTOUT "
        "= 97.8%; diag_hydro shows a live run, no crash -- the detached process was "
        "externally truncated at the tail, so the final ~52 days of val 1991 are "
        "unsimulated). Metrics scored on the real-model output over 1986-01-01.."
        "1991-11-09 (1985 H2 discarded as spinup). Discharge from CHRTOUT at the "
        "gauge-matched max-order feature (dt_v009 -- NOT basin-mean LDASOUT SFCRNOFF). "
        + (" ".join(R.NOTES_EXTRA) if R.NOTES_EXTRA else "")
    )

    seen = set()
    result["tools_used"] = [t for t in R.TOOLS_USED if not (t in seen or seen.add(t))]
    result["tools_failed"] = R.TOOLS_FAILED

    out = STATE_DIR / "result.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    R.log(f"WROTE {out} status={result['status']}")
    print("RESULT_JSON_BEGIN")
    print(json.dumps(result, ensure_ascii=False))
    print("RESULT_JSON_END")


if __name__ == "__main__":
    main()
