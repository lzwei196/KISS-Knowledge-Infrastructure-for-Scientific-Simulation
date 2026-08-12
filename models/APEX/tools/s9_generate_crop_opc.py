#!/usr/bin/env python3
"""
s9_generate_crop_opc.py — Generate APEX0806 operation schedule (OPC) for any crop.

Builds a management schedule with planting dates, fertilizer rates, and tillage.
Dates come from GGCMI Phase 3 crop calendar (when ``--ggcmi-dir`` is supplied);
NPK rates come from NPKGRIDSv1.08 (when ``--npkgrids-dir`` is supplied).
Falls back to hardcoded latitude-band defaults when either dataset is not provided.

**APEX0806 operation codes** (different from APEX1501 — do NOT mix):
  136 = plant/drill,  261 = fertilize,  292 = harvest grain
  151 = field cultivator,  157 = cultivation,  451 = kill crop

**APEX0806 fertilizer codes** (FERTCOM.DAT, codes 1-72 only):
  53 = Elem-N (100% N),  54 = Elem-P (100% P)
  Codes 92/93 are APEX1501 only — they cause Fortran PAUSE in APEX0806.

Data paths (server):
  GGCMI:     /home/server/Crop_model_dataset/GGCMI_phase3_crop_calendar/
  NPKGRIDS:  /home/server/Crop_model_dataset/24616050/

GGCMI crop code mapping:
  corn/maize → mai_rf  |  winter_wheat → wwh_rf  |  spring_wheat → swh_rf
  soybean    → soy_rf  |  rice         → ri1_ir   (first/single season irrigated — ric_rf does NOT exist)

Usage:
    python s9_generate_crop_opc.py --crop corn --lat 32.9 --lon 117.4 \\
        --ggcmi-dir /home/server/Crop_model_dataset/GGCMI_phase3_crop_calendar/ \\
        --npkgrids-dir /home/server/Crop_model_dataset/24616050/ \\
        --workspace /tmp/apex_run
    python s9_generate_crop_opc.py --crop wheat --lat 45.0 --lon 126.6 \\
        --ggcmi-dir /home/server/Crop_model_dataset/GGCMI_phase3_crop_calendar/ \\
        --workspace /tmp/apex_run
    python s9_generate_crop_opc.py --list-crops --workspace /tmp/apex_run
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

# Crop templates: (plant_id, name, typical schedules by latitude band)
# Plant IDs from PLANTABLE.DAT
CROP_DB = {
    "corn": {
        "plant_id": 2,
        "name": "CORN",
        "schedules": {
            # (min_lat, max_lat): (plant_month, plant_day, harvest_month, harvest_day, n_rate_kgha)
            "tropical": (0, 23, 10, 15, 3, 15, 120),       # Oct plant, Mar harvest
            "subtropical": (23, 35, 6, 10, 10, 15, 150),    # Jun plant, Oct harvest (China summer maize)
            "temperate": (35, 50, 5, 1, 10, 1, 180),        # May plant, Oct harvest (US Corn Belt)
            "cool": (50, 65, 5, 15, 9, 15, 140),            # May plant, Sep harvest
        },
    },
    "wheat": {
        "plant_id": 3,  # WWHT (winter wheat)
        "name": "WWHT",
        "schedules": {
            "subtropical": (23, 35, 10, 15, 6, 10, 120),    # Oct plant, Jun harvest (China winter wheat)
            "temperate": (35, 50, 10, 1, 7, 1, 140),        # Oct plant, Jul harvest
            "cool": (50, 65, 9, 15, 8, 1, 120),             # Sep plant, Aug harvest
        },
    },
    "spring_wheat": {
        "plant_id": 7,  # SWHT
        "name": "SWHT",
        "schedules": {
            "temperate": (35, 50, 4, 1, 8, 15, 100),
            "cool": (50, 65, 4, 15, 8, 30, 80),
        },
    },
    "soybean": {
        "plant_id": 1,
        "name": "SOYB",
        "schedules": {
            "subtropical": (23, 35, 6, 15, 10, 20, 20),     # Jun plant, Oct harvest (minimal N — legume)
            "temperate": (35, 50, 5, 15, 10, 1, 20),
        },
    },
    "rice": {
        "plant_id": 18,
        "name": "RICE",
        "schedules": {
            "tropical": (0, 23, 6, 1, 11, 1, 100),
            "subtropical": (23, 35, 5, 1, 10, 1, 120),
        },
    },
    "cotton": {
        "plant_id": 86,
        "name": "COTT",
        "schedules": {
            "subtropical": (23, 35, 4, 15, 10, 15, 100),
            "temperate": (35, 40, 5, 1, 10, 1, 80),
        },
    },
    "sorghum": {
        "plant_id": 4,
        "name": "GRSG",
        "schedules": {
            "subtropical": (23, 35, 6, 1, 10, 15, 80),
            "temperate": (35, 50, 5, 15, 10, 1, 100),
        },
    },
    "pasture": {
        "plant_id": 187,
        "name": "PAST",
        "schedules": {
            "all": (0, 65, 1, 1, 12, 31, 0),  # year-round
        },
    },
}


# GGCMI Phase 3 crop code → filename stem.
# Rice: GGCMI uses ri1 (first/single season) and ri2 (second/late season).
# There is NO "ric" code — that filename does not exist in the catalog.
# ri1_ir is preferred for China (nearly all paddy rice is irrigated);
# ri1_rf is identical in value but semantically wrong for paddy systems.
_GGCMI_CODE = {
    "corn":          "mai_rf",
    "maize":         "mai_rf",
    "wheat":         "wwh_rf",
    "winter_wheat":  "wwh_rf",
    "spring_wheat":  "swh_rf",
    "soybean":       "soy_rf",
    "rice":          "ri1_ir",   # first/single season, irrigated (dominant in China)
    "rice_s1":       "ri1_ir",   # explicit first-season alias
    "rice_s2":       "ri2_ir",   # second-season / late rice
    "sorghum":       "sor_rf",
    "cotton":        "cot_rf",
}

# NPKGRIDSv1.08 crop → filename stem
_NPKGRIDS_CROP = {
    "corn":          "maize",
    "maize":         "maize",
    "wheat":         "wheat",
    "winter_wheat":  "wheat",
    "spring_wheat":  "wheat",
    "soybean":       "soybean",
    "rice":          "rice",
    "rice_s1":       "rice",
    "rice_s2":       "rice",
    "cotton":        "cotton",
    "sorghum":       "sorghum",
}

# Tier-3 fallback NPK rates (kg/ha elemental N and P) keyed by crop name.
# Values from FAOSTAT China 2010-2015 provincial means (verified).
_NPK_FALLBACK = {
    "corn":         {"n": 180.0, "p": 50.0},
    "maize":        {"n": 180.0, "p": 50.0},
    "wheat":        {"n": 160.0, "p": 45.0},
    "winter_wheat": {"n": 160.0, "p": 45.0},
    "spring_wheat": {"n": 120.0, "p": 35.0},
    "rice":         {"n": 140.0, "p": 35.0},
    "rice_s1":      {"n": 140.0, "p": 35.0},
    "rice_s2":      {"n": 130.0, "p": 30.0},
    "soybean":      {"n":  20.0, "p": 20.0},
    "sorghum":      {"n":  80.0, "p": 25.0},
    "cotton":       {"n":  80.0, "p": 25.0},
    "pasture":      {"n":   0.0, "p":  0.0},
}


def lookup_ggcmi_calendar(crop_name: str, lat: float, lon: float,
                          ggcmi_dir: str) -> dict | None:
    """Return {plant_month, plant_day, harvest_month, harvest_day, gsl, source}
    from GGCMI Phase 3, or None if the file is absent or the cell is masked.

    Falls back to None — caller must handle via get_schedule() Tier-3 defaults.
    """
    import numpy as np
    try:
        import netCDF4 as nc
    except ImportError:
        print("  WARN: netCDF4 not available, skipping GGCMI lookup")
        return None

    from datetime import datetime, timedelta

    code = _GGCMI_CODE.get(crop_name.lower())
    if code is None:
        return None

    path = os.path.join(ggcmi_dir, f"{code}_ggcmi_crop_calendar_phase3_v1.01.nc4")
    if not os.path.exists(path):
        print(f"  WARN: GGCMI file not found for crop '{crop_name}' (code={code}): {path}")
        print(f"  → falling back to CROP_DB latitude-band defaults")
        return None

    ds = nc.Dataset(path)
    lat_arr = ds.variables["lat"][:]
    lon_arr = ds.variables["lon"][:]
    lat_i = int(np.argmin(np.abs(lat_arr - lat)))
    lon_i = int(np.argmin(np.abs(lon_arr - lon)))
    pd_doy = ds.variables["planting_day"][lat_i, lon_i]
    md_doy = ds.variables["maturity_day"][lat_i, lon_i]
    gsl    = ds.variables["growing_season_length"][lat_i, lon_i]
    ds.close()

    if np.ma.is_masked(pd_doy) or float(pd_doy) < 1 or float(md_doy) < 1:
        print(f"  WARN: GGCMI cell masked for '{crop_name}' (code={code}) at ({lat:.3f},{lon:.3f})")
        print(f"  → falling back to CROP_DB latitude-band defaults")
        return None

    def doy_to_md(doy):
        d = datetime(2001, 1, 1) + timedelta(days=int(doy) - 1)
        return d.month, d.day

    pm, pd_ = doy_to_md(float(pd_doy))
    hm, hd  = doy_to_md(float(md_doy))
    return {"plant_month": pm, "plant_day": pd_,
            "harvest_month": hm, "harvest_day": hd,
            "gsl": int(gsl), "source": f"GGCMI_phase3/{code}"}


def _npkgrids_spatial_mean(ds, lat_arr, lon_arr, lat: float, lon: float,
                            radius_deg: float = 2.0) -> tuple[float, float, int]:
    """Return (N_mean, P2O5_mean, n_cells) from non-zero cells within radius_deg."""
    import numpy as np
    lat_mask = np.abs(lat_arr - lat) <= radius_deg
    lon_mask = np.abs(lon_arr - lon) <= radius_deg
    n_field   = ds.variables["Nrate"][:]
    p2o5_field = ds.variables["P2O5rate"][:]
    region_n   = n_field[np.ix_(lat_mask, lon_mask)]
    region_p   = p2o5_field[np.ix_(lat_mask, lon_mask)]
    # Mask: non-zero, non-fill, non-masked
    valid = (~np.ma.getmaskarray(region_n)) & (region_n > 0)
    n_cells = int(valid.sum())
    if n_cells == 0:
        return 0.0, 0.0, 0
    return float(region_n[valid].mean()), float(region_p[valid].mean()), n_cells


def lookup_npkgrids(crop_name: str, lat: float, lon: float,
                    npkgrids_dir: str,
                    spatial_radius_deg: float = 2.0) -> dict:
    """Tiered NPK lookup (Option D):

    Tier 1 — NPKGRIDSv1.08 cell value > 0           → use directly
    Tier 2 — NPKGRIDSv1.08 spatial mean (±2°) > 0   → use mean, WARN
    Tier 3 — _NPK_FALLBACK crop default              → use default, WARN

    Always returns a dict {n_rate_kgha, p_rate_kgha, source, tier}.
    Never returns None — caller always gets a usable value.
    """
    import numpy as np
    crop_key = crop_name.lower()
    fallback = _NPK_FALLBACK.get(crop_key, {"n": 100.0, "p": 30.0})

    def _fallback_result(reason: str) -> dict:
        print(f"  WARN: NPKGRIDS Tier-3 fallback for '{crop_name}': {reason}")
        print(f"  → N={fallback['n']:.1f} kg/ha, Elem-P={fallback['p']:.1f} kg/ha "
              f"[_NPK_FALLBACK crop default]")
        return {"n_rate_kgha": fallback["n"], "p_rate_kgha": fallback["p"],
                "source": "_NPK_FALLBACK", "tier": 3}

    try:
        import netCDF4 as nc
    except ImportError:
        return _fallback_result("netCDF4 not installed")

    stem = _NPKGRIDS_CROP.get(crop_key)
    if stem is None:
        return _fallback_result(f"no NPKGRIDS mapping for crop '{crop_name}'")

    path = os.path.join(npkgrids_dir, f"NPKGRIDSv1.08_{stem}.nc")
    if not os.path.exists(path):
        return _fallback_result(f"file not found: {path}")

    ds = nc.Dataset(path)
    lat_arr = ds.variables["lat"][:]
    lon_arr = ds.variables["lon"][:]
    lat_i   = int(np.argmin(np.abs(lat_arr - lat)))
    lon_i   = int(np.argmin(np.abs(lon_arr - lon)))
    n_cell  = float(ds.variables["Nrate"][lat_i, lon_i])
    p2o5_cell = float(ds.variables["P2O5rate"][lat_i, lon_i])

    # Tier 1: cell value non-zero
    if n_cell > 0:
        ds.close()
        p_elem = p2o5_cell / 2.291
        return {"n_rate_kgha": n_cell, "p_rate_kgha": p_elem,
                "source": "NPKGRIDSv1.08", "tier": 1}

    # Tier 2: spatial mean within radius_deg
    n_mean, p2o5_mean, n_cells = _npkgrids_spatial_mean(
        ds, lat_arr, lon_arr, lat, lon, spatial_radius_deg)
    ds.close()

    if n_mean > 0:
        p_elem = p2o5_mean / 2.291
        print(f"  WARN: NPKGRIDS Tier-2 spatial mean for '{crop_name}' at "
              f"({lat:.3f},{lon:.3f}): cell=0, using {n_cells}-cell mean "
              f"within ±{spatial_radius_deg}°")
        print(f"  → N={n_mean:.1f} kg/ha, Elem-P={p_elem:.1f} kg/ha [NPKGRIDSv1.08 spatial mean]")
        return {"n_rate_kgha": n_mean, "p_rate_kgha": p_elem,
                "source": f"NPKGRIDSv1.08_spatial_mean±{spatial_radius_deg}deg",
                "tier": 2, "n_cells": n_cells}

    # Tier 3: crop default
    return _fallback_result(f"cell=0 and no non-zero cells within ±{spatial_radius_deg}°")


def get_schedule(crop_name, lat):
    """Get planting schedule for crop at latitude."""
    crop = CROP_DB.get(crop_name.lower())
    if not crop:
        raise ValueError(f"Unknown crop '{crop_name}'. Available: {list(CROP_DB.keys())}")

    abs_lat = abs(lat)
    for zone_name, (min_lat, max_lat, p_mon, p_day, h_mon, h_day, n_rate) in crop["schedules"].items():
        if min_lat <= abs_lat < max_lat:
            return {
                "plant_id": crop["plant_id"],
                "crop_name": crop["name"],
                "zone": zone_name,
                "plant_month": p_mon,
                "plant_day": p_day,
                "harvest_month": h_mon,
                "harvest_day": h_day,
                "n_rate_kgha": n_rate,
            }

    # Default to closest zone
    zones = list(crop["schedules"].values())
    return {
        "plant_id": crop["plant_id"],
        "crop_name": crop["name"],
        "zone": "default",
        "plant_month": zones[0][2],
        "plant_day": zones[0][3],
        "harvest_month": zones[0][4],
        "harvest_day": zones[0][5],
        "n_rate_kgha": zones[0][6],
    }


def _op_line(yr, mo, dy, till, mach, crop_id, opv,
             opv1=0.0, opv2=0.0, opv3=0.0, opv4=0.0, opv5=0.0, opv6=0.0, opv7=0.0):
    """Format one APEX OPC line matching the working template format.

    Actual Fortran format (confirmed from working Y10.OPC Bengbu reference):
      3(I3) + 4(I5) + 7(F8.2)
      YR MO DY | EQUIP TRACTOR CROP OPV | OPV1 OPV2 OPV3 OPV4 OPV5 OPV6 OPV7

    WARNING: 5×I5 (adding an OPV0 field) silently shifts OPV1 (PHU) to OPV2
    position. APEX reads PHU=0 → crop matures at planting → zero biomass/yield.

    APEX0806 operation codes (v1501 uses DIFFERENT codes — do NOT mix):
      136 = plant/drill,  261 = fertilize,  292 = harvest grain
      160 = field cultivator (code 151 NOT in TILLCOM.DAT → Fortran PAUSE)
      451 = kill crop (REQUIRED after 292 to prevent crop carry-over cascade)

    For PLANTING (equip 136):
      OPV1 = PHU (potential heat units, 0-5000)
      OPV5 = plant population (plants/m²)
    For FERTILIZER (equip 261):
      OPV  = fertilizer ID from FERTCOM.DAT  ← APEX0806 only has codes 1-72.
             Use 53 (Elem-N, 100%N) and 54 (Elem-P, 100%P).
             Codes 92/93 (APEX1501) are NOT in FERTCOM.DAT; they trigger a
             Fortran PAUSE that hangs the subprocess indefinitely.
      OPV1 = application rate (kg/ha)
    For HARVEST (equip 292):
      OPV7 = heat unit fraction (0.0 = harvest on calendar date regardless of HUI)
    """
    return (f"{yr:3d}{mo:3d}{dy:3d}{till:5d}{mach:5d}{crop_id:5d}{opv:5d}"
            f"{opv1:8.2f}{opv2:8.2f}{opv3:8.2f}{opv4:8.2f}{opv5:8.2f}{opv6:8.2f}{opv7:8.2f}")


def write_opc(schedule, n_years, output_path, title="Generated by KDT"):
    """Write an APEX OPC file for the given crop schedule."""
    # Determine LUN (Land Use Number from NRCS table, manual p.78-79)
    lun_map = {
        "CORN": 3, "SOYB": 3, "GRSG": 3,   # Row crops, good condition
        "WWHT": 9, "SWHT": 9,                # Small grain, good condition
        "RICE": 3, "COTT": 3,                # Row crops
        "PAST": 21,                           # Pasture, good condition
    }
    crop_name = schedule.get("crop_name", "CORN")
    lun = lun_map.get(crop_name, 3)

    lines = []
    lines.append(f"   {title}")
    # Line 2: 20 fields × I4 (manual p.78). Only LUN is needed, rest default to 0.
    line2 = f"{lun:4d}" + "   0" * 19
    lines.append(line2)

    pid = schedule["plant_id"]
    pm = schedule["plant_month"]
    pd = schedule["plant_day"]
    hm = schedule["harvest_month"]
    hd = schedule["harvest_day"]
    n_kg = schedule["n_rate_kgha"]

    # Estimate PHU (potential heat units) from growing season length and latitude
    # PHU = sum of daily (Tavg - Tbase) from plant to harvest
    # Rough estimate: ~15-20 HU/day for summer crops in temperate zones
    phu_defaults = {
        "CORN": 1600, "SOYB": 1200, "WWHT": 1800, "SWHT": 1200,
        "RICE": 1500, "GRSG": 1400, "COTT": 1800, "PAST": 1400,
    }
    crop_name = schedule.get("crop_name", "CORN")
    phu = phu_defaults.get(crop_name, 1500)

    # Plant population (plants/m²)
    ppop_defaults = {
        "CORN": 7.0, "SOYB": 30.0, "WWHT": 350.0, "SWHT": 350.0,
        "RICE": 25.0, "GRSG": 15.0, "COTT": 8.0, "PAST": 0.0,
    }
    ppop = ppop_defaults.get(crop_name, 7.0)

    # APEX0806 HARD LIMIT: an operation schedule carrying >= 50 rotation years
    # overruns a fixed-size internal rotation array.  Verified 2026-08-09 on the
    # Huaibin GDHY workspace: 49 rotation years -> rc=0, 50 -> forrtl severe (157)
    # access violation at end of run, AND the overrun silently perturbs YLDG in
    # EVERY year (7.298 vs 7.219 t/ha mean 1981-2016), so a >= 50-year schedule is
    # invalid even where APEX manages to write the rows.  APEX RECYCLES the OPC
    # rotation to cover NBYR, so clamping is lossless: a 49-year OPC with NBYR=56
    # reproduced years 1-49 bit-identically and filled 50-56 from the rotation head.
    MAX_ROTATION_YEARS = 49
    if n_years > MAX_ROTATION_YEARS:
        sys.stderr.write(
            f"[s9] WARNING: n_years={n_years} exceeds the APEX0806 rotation "
            f"limit; clamping the OPC to {MAX_ROTATION_YEARS} rotation years "
            f"(APEX recycles the rotation to fill NBYR).\n")
        n_years = MAX_ROTATION_YEARS

    for yr in range(1, n_years + 1):
        # Tillage before planting (160 = field cultivator; 151 not in TILLCOM.DAT)
        till_mon = pm - 1 if pm > 1 else 12
        lines.append(_op_line(yr, till_mon, 15, 160, 0, pid, 0))

        # Plant (136 = drill planter in APEX0806): OPV1=PHU, OPV5=plant pop
        lines.append(_op_line(yr, pm, pd, 136, 0, pid, 0,
                              opv1=float(phu), opv5=ppop))

        # Fertilize N: OPV=53 (Elem-N, 100%N in FERTCOM.DAT codes 1-72)
        # CRITICAL: do NOT use codes 92/93 — they are APEX1501 only and
        # cause a Fortran PAUSE that hangs the Wine subprocess.
        # P rate: from schedule["p_rate_kgha"] (NPKGRIDS) or fallback 25% of N.
        if n_kg > 0:
            lines.append(_op_line(yr, pm, pd, 261, 0, pid, 53,
                                  opv1=n_kg))
            # Elemental P: code 54 = Elem-P (100%P)
            p_kg = schedule.get("p_rate_kgha", n_kg * 0.25)
            lines.append(_op_line(yr, pm, pd, 261, 0, pid, 54,
                                  opv1=p_kg))

        # Harvest grain (292 in APEX0806): OPV7=0.0 fires on calendar date
        lines.append(_op_line(yr, hm, hd, 292, 0, pid, 0,
                              opv7=0.0))
        # Kill crop day after harvest — REQUIRED to prevent carry-over cascade
        # Without this, unharvested biomass persists and blocks year 3+ planting
        kill_day = hd + 1 if hd < 28 else 1
        kill_mon = hm if hd < 28 else (hm + 1 if hm < 12 else 1)
        lines.append(_op_line(yr, kill_mon, kill_day, 451, 0, pid, 0))

    # Write
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return output_path


def wire_management_list(workspace, opc_name="OPSC01.mgt"):
    """Point every subarea in OPSCCOM.DAT (APEX0806 management list) at ``opc_name``.

    THE MISSING LINK: s9.write_opc()/quickstart only WRITE the generated crop
    schedule (OPSC01.mgt); nothing repoints the management list at it, so the
    binary keeps reading the shipped Riesel-TX rotations (Y10/RNGE/Y6/Y8.OPC)
    and the new crop never runs. The validated China-corn workspaces in
    outputs/ (apex_harbin_corn_2010_2020, apex_bengbu_corn_ki_test) all have
    OPSCCOM.DAT rewritten so every subarea references the generated OPC — this
    function reproduces that wiring deterministically.

    OPSCCOM.DAT is a COM-style list file: ``<id> <opc filename>`` per line,
    one line per management schedule. APEX subareas select a schedule by the
    integer id in the SUB file, so we preserve the existing ids (1..N) and only
    swap the filename. CRLF is written (APEX0806 COM files require it).
    Both case variants of the OPC file are ensured to exist on disk.
    """
    ws = Path(workspace).expanduser().resolve()
    com = ws / "OPSCCOM.DAT"
    if not com.is_file():
        raise FileNotFoundError(f"OPSCCOM.DAT missing in workspace: {com}")

    # Ensure both case variants of the OPC exist (APEX is case-sensitive on Linux;
    # the list file may reference either case).
    stem, _dot, ext = opc_name.rpartition(".")
    src = ws / opc_name
    if src.is_file():
        for alt in {opc_name, f"{stem}.{ext.upper()}", f"{stem}.{ext.lower()}"}:
            if alt != opc_name:
                shutil.copy2(src, ws / alt)

    ids = []
    for ln in com.read_text(errors="ignore").splitlines():
        toks = ln.split()
        if toks and toks[0].lstrip("-").isdigit():
            ids.append(int(toks[0]))
    if not ids:
        ids = [1]
    new_lines = [f"{i:5d} {opc_name}" for i in ids]
    com.write_text("\r\n".join(new_lines) + "\r\n")
    return com


def list_crops(workspace):
    """List available crops from PLANTABLE.DAT."""
    plantable = os.path.join(workspace, "PLANTABLE.DAT")
    if not os.path.isfile(plantable):
        print("PLANTABLE.DAT not found")
        return

    crops = []
    with open(plantable) as f:
        for line in f:
            parts = line.split()
            if len(parts) > 2:
                try:
                    cid = int(parts[0])
                    name = parts[1]
                    crops.append((cid, name))
                except:
                    pass

    print(f"Available crops ({len(crops)} total):")
    for cid, name in crops:
        template = next((k for k, v in CROP_DB.items() if v["plant_id"] == cid), None)
        marker = f" ← template: '{template}'" if template else ""
        print(f"  ID={cid:<4} {name}{marker}")


def main():
    parser = argparse.ArgumentParser(description="Generate APEX0806 crop OPC schedule")
    parser.add_argument("--crop", help="Crop name (corn, wheat, soybean, rice, cotton, sorghum, pasture)")
    parser.add_argument("--lat", type=float, help="Latitude for schedule selection")
    parser.add_argument("--lon", type=float, default=None,
                        help="Longitude — required for GGCMI/NPKGRIDS lookups")
    parser.add_argument("--workspace", required=True, help="APEX workspace directory")
    parser.add_argument("--n-years", type=int, default=6, help="Number of rotation years")
    parser.add_argument("--output", help="Output OPC filename (default: OPSC01.mgt)")
    parser.add_argument("--list-crops", action="store_true", help="List available crops")
    parser.add_argument("--n-rate", type=float, help="Override N fertilizer rate (kg/ha)")
    parser.add_argument("--ggcmi-dir", default=None,
                        help="Path to GGCMI Phase 3 crop calendar directory "
                             "(e.g. /home/server/Crop_model_dataset/GGCMI_phase3_crop_calendar/). "
                             "When provided, overrides hardcoded planting/harvest dates.")
    parser.add_argument("--npkgrids-dir", default=None,
                        help="Path to NPKGRIDSv1.08 directory "
                             "(e.g. /home/server/Crop_model_dataset/24616050/). "
                             "When provided, overrides hardcoded N/P application rates.")
    args = parser.parse_args()

    if args.list_crops:
        list_crops(args.workspace)
        return

    if not args.crop or args.lat is None:
        parser.error("--crop and --lat required (or use --list-crops)")

    schedule = get_schedule(args.crop, args.lat)

    # Override dates from GGCMI if available
    if args.ggcmi_dir and args.lon is not None:
        cal = lookup_ggcmi_calendar(args.crop, args.lat, args.lon, args.ggcmi_dir)
        if cal:
            schedule["plant_month"]   = cal["plant_month"]
            schedule["plant_day"]     = cal["plant_day"]
            schedule["harvest_month"] = cal["harvest_month"]
            schedule["harvest_day"]   = cal["harvest_day"]
            schedule["calendar_source"] = cal["source"]
            print(f"  GGCMI calendar: plant={cal['plant_month']}/{cal['plant_day']} "
                  f"harvest={cal['harvest_month']}/{cal['harvest_day']} GSL={cal['gsl']}d")

    # Override NPK from NPKGRIDS if available
    if args.npkgrids_dir and args.lon is not None:
        npk = lookup_npkgrids(args.crop, args.lat, args.lon, args.npkgrids_dir)
        if npk:
            schedule["n_rate_kgha"] = npk["n_rate_kgha"]
            schedule["p_rate_kgha"] = npk["p_rate_kgha"]
            schedule["npk_source"] = npk["source"]
            print(f"  NPKGRIDS: N={npk['n_rate_kgha']:.1f} kg/ha  Elem-P={npk['p_rate_kgha']:.1f} kg/ha")

    if args.n_rate is not None:
        schedule["n_rate_kgha"] = args.n_rate

    output = args.output or os.path.join(args.workspace, "OPSC01.mgt")
    title = f"{schedule['crop_name']} at lat={args.lat:.1f} lon={args.lon or '?'} ({schedule.get('zone','?')})"

    write_opc(schedule, args.n_years, output, title=title)

    print(f"Generated OPC: {output}")
    print(f"  Crop: {schedule['crop_name']} (ID={schedule['plant_id']})")
    print(f"  Zone: {schedule.get('zone','?')}")
    print(f"  Plant: month={schedule['plant_month']} day={schedule['plant_day']}  "
          f"[{schedule.get('calendar_source','hardcoded')}]")
    print(f"  Harvest: month={schedule['harvest_month']} day={schedule['harvest_day']}")
    print(f"  N rate: {schedule['n_rate_kgha']} kg/ha  [{schedule.get('npk_source','hardcoded')}]")
    print(f"  Years: {args.n_years}")


if __name__ == "__main__":
    main()
