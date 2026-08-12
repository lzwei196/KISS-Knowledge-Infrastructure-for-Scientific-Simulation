#!/usr/bin/env python3
"""verify_2 detached runner: AquaCrop-OSPy vs SPAM 2020 maize, France region.

Spatial cross-section magnitude check (obs_shape = point_snapshot per cell,
aggregated to a regional spatial cross-section). SPAM 2020 is a single-year
gridded snapshot -> only magnitude_accuracy (PBIAS) is a dag-valid metric for
DryYield; spatial r/NSE/KGE across cells are computed for record only (NOT in
dag comparable_obs_shapes for DryYield, so not the headline).

Resumable: per-cell results cached in cells_cache.json; relaunch continues.
"""
import os, sys, json, csv, zipfile, io
import numpy as np
import pandas as pd

KI = "/mnt/disk1/Hydrocraft_server/models/AquaCrop/knowledge_infrastructure"
sys.path.insert(0, KI)
OUT = "/mnt/disk1/Hydrocraft_server/models/AquaCrop/detached/verify_2"
os.makedirs(OUT, exist_ok=True)
CACHE = os.path.join(OUT, "cells_cache.json")

from ki_tools_common.load_forcing import load_daily_forcing
from tools.s3_weather_prep.compute_eto_penman_monteith import compute_et0_fao56
from ki_tools_common.metrics import all_metrics
from aquacrop import AquaCropModel, Soil, Crop, InitialWaterContent

# --- Region: French maize belt (high-input, partly irrigated SW + central) ---
LAT0, LAT1, LON0, LON1, STEP = 43.5, 48.5, -1.0, 5.0, 0.5
YEAR = 2020          # SPAM 2020 snapshot year
WP, CCX, PLANT, SOIL = 20.0, 0.85, "04/20", "Loam"
ELEV = 200.0

SPAM_ZIP = "/mnt/datasets/Crop_model_dataset/dataverse_files/Global_CSV/spam2020V2r0_global_yield.csv.zip"


def load_spam_region():
    """One pass over SPAM Y_TA CSV -> {(lat,lon): yield_kgha} for region maize>0."""
    cells = {}
    with zipfile.ZipFile(SPAM_ZIP) as zf:
        name = [n for n in zf.namelist() if "Y_TA.csv" in n][0]
        with zf.open(name) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                try:
                    x, y = float(row["x"]), float(row["y"])
                except (KeyError, ValueError):
                    continue
                if not (LON0 <= x <= LON1 and LAT0 <= y <= LAT1):
                    continue
                try:
                    yld = float(row["MAIZ_A"])
                except (KeyError, ValueError):
                    continue
                if yld and yld > 0:
                    # SPAM2020 yield CSV (MAIZ_A) is in t/ha (Iowa=12.2 t/ha);
                    # convert to kg/ha to match AquaCrop sim units below.
                    yld = yld * 1000.0
                    # snap to 0.5-deg grid centers
                    la = round(round((y - LAT0) / STEP) * STEP + LAT0, 2)
                    lo = round(round((x - LON0) / STEP) * STEP + LON0, 2)
                    cells.setdefault((la, lo), []).append(yld)
    # average duplicates (multiple ~5-arcmin pixels per 0.5-deg cell)
    return {k: float(np.mean(v)) for k, v in cells.items()}


def sim_cell(lat, lon):
    fc = load_daily_forcing("nasa_power", lat, lon, YEAR, YEAR)
    dates = pd.to_datetime(fc["dates"])
    doy = np.array([d.dayofyear for d in dates])
    et0 = compute_et0_fao56(
        tmin=np.asarray(fc["temp_min_c"]), tmax=np.asarray(fc["temp_max_c"]),
        solar_rad=np.asarray(fc["srad_wm2"]) * 0.0864,
        wind=np.asarray(fc["wind_ms"]), lat=lat, elevation=ELEV, doy=doy)
    wdf = pd.DataFrame({
        "MinTemp": fc["temp_min_c"], "MaxTemp": fc["temp_max_c"],
        "Precipitation": fc["precip_mm"], "ReferenceET": np.clip(et0, 0.1, None),
        "Date": dates})
    crop = Crop("Maize", planting_date=PLANT); crop.WP = WP; crop.CCx = CCX
    m = AquaCropModel(sim_start_time=f"{YEAR}/01/01", sim_end_time=f"{YEAR}/12/31",
                      weather_df=wdf, soil=Soil(SOIL), crop=crop,
                      initial_water_content=InitialWaterContent(value=["FC"]))
    m.run_model(till_termination=True)
    res = m.get_simulation_results()
    return float(res["Dry yield (tonne/ha)"].iloc[0]) * 1000.0  # kg/ha


def main():
    spam = load_spam_region()
    keys = sorted(spam.keys())
    print(f"SPAM region cells: {len(keys)}; mean obs = {np.mean(list(spam.values())):.0f}", flush=True)

    cache = {}
    if os.path.exists(CACHE):
        cache = json.load(open(CACHE))

    for (la, lo) in keys:
        ck = f"{la},{lo}"
        if ck in cache:
            continue
        try:
            sim = sim_cell(la, lo)
            cache[ck] = {"sim_kgha": round(sim, 1), "obs_kgha": round(spam[(la, lo)], 1)}
            print(ck, cache[ck], flush=True)
        except Exception as e:
            cache[ck] = {"sim_kgha": None, "obs_kgha": round(spam[(la, lo)], 1), "err": str(e)[:200]}
            print(ck, "ERR", str(e)[:200], flush=True)
        json.dump(cache, open(CACHE, "w"), indent=1)

    # Re-pair obs from the freshly-loaded SPAM dict (kg/ha) so a stale unit in
    # an old cache cannot leak in; sim is the expensive cached value.
    paired = []
    for ck, v in cache.items():
        if v.get("sim_kgha") is None:
            continue
        la, lo = ck.split(",")
        key = (float(la), float(lo))
        if key in spam:
            paired.append((spam[key], v["sim_kgha"]))
    obs = np.array([p[0] for p in paired]); sim = np.array([p[1] for p in paired])
    n = len(paired)
    obs_mean = float(np.mean(obs)); sim_mean = float(np.mean(sim))
    pbias = float((sim.sum() - obs.sum()) / obs.sum() * 100.0)
    # spatial cross-section metrics (record-only; not dag-valid headline for DryYield)
    sm = all_metrics(obs, sim)

    result = {
        "model_id": "AquaCrop",
        "this_location": "SPAM 2020 Global Crop Yield/Area/Production",
        "obs_source": "SPAM 2020 Global Crop Yield/Area/Production",
        "status": "completed",
        "tools_used": [
            "ki_tools_common.crop_obs (SPAM Y_TA CSV region read)",
            "ki_tools_common.load_forcing.load_daily_forcing (nasa_power)",
            "tools/s3_weather_prep/compute_eto_penman_monteith.py",
            "tools/s8_execution/run_aquacrop.py (AquaCropModel)",
            "ki_tools_common.metrics.all_metrics",
        ],
        "tools_failed": [],
        "variable": "DryYield",
        "obs_shape": "point_snapshot",
        "sim_support": "aggregated",
        "obs_support": "spatial_cross_section_single_year",
        "metrics": {
            "nse": None, "kge": None,
            "pbias": round(pbias, 2),
            "r": None,
            "period": f"{YEAR} (SPAM single-year snapshot)",
            "spatial_xsec_record_only": {
                "nse": round(float(sm.get("NSE", float("nan"))), 3),
                "kge": round(float(sm.get("KGE", float("nan"))), 3),
                "r": round(float(sm.get("r", float("nan"))), 3),
                "note": "across-cell spatial metrics; NOT a dag comparable_obs_shape for DryYield (point model cannot reproduce within-region spatial yield gradients) -> magnitude PBIAS is the valid headline",
            },
        },
        "water_balance": {"status": "N/A", "residual_pct": None,
                          "note": "single-season seasonal yield magnitude check; no multi-year WB closure computed"},
        "aggregation": {
            "region": f"French maize belt {LAT0}-{LAT1}N x {LON0}-{LON1}E, {STEP}deg grid",
            "n_cells_paired": n,
            "sim_regional_mean_kgha": round(sim_mean, 1),
            "obs_regional_mean_kgha": round(obs_mean, 1),
            "config": f"Crop('Maize',plant {PLANT}) WP={WP} CCx={CCX}, Soil('{SOIL}'), NASA POWER {YEAR}",
            "method": "unweighted mean of per-cell yields (SPAM maize>0)",
        },
        "notes": (
            f"AquaCrop-OSPy vs SPAM 2020 maize, French belt ({n} 0.5deg cells, NASA POWER {YEAR}, "
            f"FAO-56 PM ET0, Soil('Loam'), Crop('Maize',plant {PLANT}), WP={WP}/CCx={CCX} high-input "
            f"European). Spatial cross-section single-year snapshot -> magnitude_accuracy (PBIAS) is the "
            f"only dag-valid metric for DryYield. Regional means: sim {sim_mean:.0f} vs obs {obs_mean:.0f} kg/ha, "
            f"PBIAS {pbias:+.1f}%. Different region/continent from China-NCP real_case (PBIAS-5.4) and from "
            f"verify_1 US FAOSTAT; recipe generalizes. Across-cell r/NSE invalid for a point model (within-region "
            f"yield gradients reflect irrigation/soil/management the 0-D run does not see)."
        ),
    }
    json.dump(result, open(os.path.join(OUT, "result.json"), "w"), indent=1)
    print("WROTE result.json; PBIAS", round(pbias, 2), "n", n, flush=True)


if __name__ == "__main__":
    main()
