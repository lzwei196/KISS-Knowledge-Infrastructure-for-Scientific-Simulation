#!/usr/bin/env python3
"""
End-to-end LDNDC GHG simulation pipeline for Bengbu basin using VIC forcing.

Converts VIC forcing → LDNDC climate, extracts HWSD soil → site.xml,
generates management (wheat-maize rotation), runs LDNDC, and parses output.

Usage:
    python run_ldndc_bengbu_ghg.py
    python run_ldndc_bengbu_ghg.py --lat 32.94 --lon 117.35
    python run_ldndc_bengbu_ghg.py --forcing_file /path/to/vic_forcing_file
"""

import argparse
import csv
import io
import json
import logging
import math
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path("/mnt/disk1/Hydrocraft_server")
LDNDC_BASE = PROJECT_ROOT / "model" / "ldndc" / "ldndc-1.37.linux64"
LDNDC_BIN = LDNDC_BASE / "bin" / "ldndc"
PROJECTS_DIR = LDNDC_BASE / "projects"
HWSD_RASTER = PROJECT_ROOT / "data" / "soil" / "HWSD_RASTER" / "hwsd.bil"
HWSD_MDB = PROJECT_ROOT / "data" / "forcing" / "huaihe_raw" / "soil" / "HWSD.mdb"
VIC_FORCING_DIR = (
    PROJECT_ROOT
    / "outputs"
    / "bengbu_2000-2005_025deg"
    / "vic_temp"
    / "forcing"
    / "forcing_final"
)

# Simulation defaults
DEFAULT_LAT = 32.94
DEFAULT_LON = 117.35
DEFAULT_ELEVATION = 20.0
START_YEAR = 2000
END_YEAR = 2005
STEPS_PER_DAY = 8  # VIC 3-hourly = 8 steps/day

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ldndc_bengbu")


# ── 1. Find nearest VIC forcing file ──────────────────────────────────────
def find_nearest_forcing(forcing_dir: Path, lat: float, lon: float) -> Path:
    """Find the VIC forcing file closest to the target lat/lon."""
    best_file = None
    best_dist = float("inf")
    # Auto-detect prefix from directory contents (e.g. bengbu_0.25deg_ or longpan_0.25deg_)
    prefix = "bengbu_0.25deg_"
    detected = [f.name for f in forcing_dir.iterdir() if "_0.25deg_" in f.name]
    if detected:
        prefix = detected[0].split("_0.25deg_")[0] + "_0.25deg_"

    for f in forcing_dir.iterdir():
        if not f.name.startswith(prefix):
            continue
        parts = f.name[len(prefix) :].split("_")
        if len(parts) != 2:
            continue
        try:
            flat, flon = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        dist = (flat - lat) ** 2 + (flon - lon) ** 2
        if dist < best_dist:
            best_dist = dist
            best_file = f

    if best_file is None:
        raise FileNotFoundError(
            f"No VIC forcing files found in {forcing_dir} with prefix {prefix}"
        )
    logger.info(
        f"Nearest forcing file: {best_file.name} (distance={math.sqrt(best_dist):.4f} deg)"
    )
    return best_file


# ── 2. Convert VIC forcing → LDNDC climate.txt ───────────────────────────
def vic_forcing_to_ldndc_climate(
    forcing_file: Path,
    output_path: Path,
    lat: float,
    lon: float,
    elevation: float,
    start_year: int,
) -> None:
    """
    Convert VIC 3-hourly 7-column forcing to LDNDC daily climate.txt.

    VIC columns: TEMP(C), PRECIP(mm/step), PRESSURE(kPa), SWDOWN(W/m2),
                 LWDOWN(W/m2), VP(kPa), WIND(m/s)

    LDNDC columns: prec(mm/d), tavg(C), tmax(C), tmin(C), grad(W/m2), wind(m/s)
    """
    logger.info(f"Reading VIC forcing: {forcing_file}")
    data = np.loadtxt(forcing_file)
    total_steps = data.shape[0]
    ndays = total_steps // STEPS_PER_DAY
    logger.info(f"Total steps: {total_steps}, days: {ndays}")

    if total_steps % STEPS_PER_DAY != 0:
        logger.warning(
            f"Steps ({total_steps}) not divisible by {STEPS_PER_DAY}; truncating."
        )
        data = data[: ndays * STEPS_PER_DAY]

    # Reshape to (ndays, steps_per_day, 7)
    daily = data.reshape(ndays, STEPS_PER_DAY, 7)

    # Aggregate to daily
    temp_all = daily[:, :, 0]       # already Celsius
    precip_all = daily[:, :, 1]     # mm per 3-hour step
    sw_all = daily[:, :, 3]         # W/m2 shortwave
    wind_all = daily[:, :, 6]       # m/s

    tavg = temp_all.mean(axis=1)
    tmin = temp_all.min(axis=1)
    tmax = temp_all.max(axis=1)
    prec = precip_all.sum(axis=1)  # sum over day
    grad = sw_all.mean(axis=1)     # mean daily shortwave (W/m2)
    wind = wind_all.mean(axis=1)

    # Compute annual statistics for header
    annual_precip = prec.sum() / (ndays / 365.25)
    temp_avg = tavg.mean()
    # Temperature amplitude: half the range between warmest and coldest monthly means
    monthly_means = []
    start_date = date(start_year, 1, 1)
    for m in range(1, 13):
        mask = []
        for d in range(ndays):
            dt = start_date + timedelta(days=d)
            if dt.month == m:
                mask.append(d)
        if mask:
            monthly_means.append(tavg[mask].mean())
    temp_amplitude = (max(monthly_means) - min(monthly_means)) / 2.0 if monthly_means else 15.0

    # Write LDNDC climate.txt
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("%global\n")
        f.write(f'\ttime = "{start_year}-01-01/1"\n')
        f.write("\n")
        f.write("%climate\n")
        f.write("\tid = 0\n")
        f.write("\n")
        f.write("%attributes\n")
        f.write(f'\televation = "{elevation:.1f}"\n')
        f.write(f'\tlatitude = "{lat:.2f}"\n')
        f.write(f'\tlongitude = "{lon:.2f}"\n')
        f.write(f'\tannual precipitation = "{annual_precip:.1f}"\n')
        f.write(f'\ttemperature average = "{temp_avg:.2f}"\n')
        f.write(f'\ttemperature amplitude = "{temp_amplitude:.0f}"\n')
        f.write("\n")
        f.write("%data\n")
        f.write("prec\ttavg\ttmax\ttmin\tgrad\twind\n")
        for i in range(ndays):
            f.write(
                f"{prec[i]:.2f}\t{tavg[i]:.2f}\t{tmax[i]:.2f}\t{tmin[i]:.2f}\t"
                f"{grad[i]:.2f}\t{wind[i]:.2f}\n"
            )

    logger.info(
        f"Climate file written: {output_path} ({ndays} days, "
        f"annual precip={annual_precip:.0f} mm, tavg={temp_avg:.1f} C)"
    )


# ── 3. Extract HWSD soil → LDNDC site.xml ────────────────────────────────
def get_hwsd_soil(lat: float, lon: float):
    """Query HWSD raster + MDB for soil properties at lat/lon."""
    import rasterio

    # Step 1: Read MU_GLOBAL from raster
    with rasterio.open(str(HWSD_RASTER)) as src:
        row, col = src.index(lon, lat)
        band = src.read(1)
        mu_global = int(band[row, col])

    logger.info(f"HWSD MU_GLOBAL at ({lat:.2f}, {lon:.2f}): {mu_global}")

    if mu_global <= 0:
        raise ValueError(f"Invalid HWSD mapping unit: {mu_global}")

    # Step 2: Query MDB for soil properties
    result = subprocess.run(
        ["mdb-export", str(HWSD_MDB), "HWSD_DATA"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mdb-export failed: {result.stderr}")

    reader = csv.DictReader(io.StringIO(result.stdout))
    soil_row = None
    for r in reader:
        if r.get("MU_GLOBAL") == str(mu_global) and r.get("SEQ") == "1":
            soil_row = r
            break

    if soil_row is None:
        raise ValueError(f"MU_GLOBAL {mu_global} not found in HWSD_DATA")

    if soil_row.get("ISSOIL") != "1":
        raise ValueError(f"MU {mu_global} is not soil (ISSOIL={soil_row.get('ISSOIL')})")

    def safe_float(val, default=0.0):
        try:
            return float(val) if val and val.strip() else default
        except (ValueError, TypeError):
            return default

    soil = {
        "mu_global": mu_global,
        "t_sand": safe_float(soil_row["T_SAND"]),
        "t_silt": safe_float(soil_row["T_SILT"]),
        "t_clay": safe_float(soil_row["T_CLAY"]),
        "t_bd": safe_float(soil_row["T_REF_BULK_DENSITY"], 1.35),
        "t_oc": safe_float(soil_row["T_OC"]),         # percentage
        "t_ph": safe_float(soil_row["T_PH_H2O"], 7.0),
        "t_gravel": safe_float(soil_row["T_GRAVEL"]),
        "s_sand": safe_float(soil_row["S_SAND"]),
        "s_silt": safe_float(soil_row["S_SILT"]),
        "s_clay": safe_float(soil_row["S_CLAY"]),
        "s_bd": safe_float(soil_row["S_REF_BULK_DENSITY"], 1.40),
        "s_oc": safe_float(soil_row["S_OC"]),         # percentage
        "s_ph": safe_float(soil_row["S_PH_H2O"], 7.0),
        "s_gravel": safe_float(soil_row["S_GRAVEL"]),
        "ref_depth": safe_float(soil_row["REF_DEPTH"], 100),
    }

    logger.info(
        f"HWSD soil: clay={soil['t_clay']}%, sand={soil['t_sand']}%, "
        f"silt={soil['t_silt']}%, BD={soil['t_bd']} g/cm3, OC={soil['t_oc']}%, pH={soil['t_ph']}"
    )
    return soil


def pedotransfer_sks(sand_pct, clay_pct, oc_pct, bd):
    """
    Estimate saturated hydraulic conductivity using Saxton & Rawls (2006).
    Returns Ksat in cm/min (LDNDC units).

    Saxton-Rawls gives Ksat in mm/hr; convert: mm/hr / 600 = cm/min.
    """
    S = sand_pct / 100.0
    C = clay_pct / 100.0
    OM = oc_pct * 1.724 / 100.0  # OC% -> OM fraction

    # Saxton-Rawls moisture constants
    theta_s = (
        0.278 * S + 0.034 * C + 0.022 * OM
        - 0.018 * S * OM - 0.027 * C * OM - 0.584 * S * C + 0.078
    )
    theta_s = theta_s + (0.636 * theta_s - 0.107)
    # Clamp
    theta_s = max(0.30, min(0.80, theta_s))

    # Ksat in mm/hr (Saxton-Rawls empirical)
    # Simplified Cosby et al. (1984): log10(Ksat_cm_hr) = -0.6 + 0.012*S_pct - 0.0064*C_pct
    log10_ksat_cm_hr = -0.6 + 0.012 * sand_pct - 0.0064 * clay_pct
    ksat_cm_hr = 10.0 ** log10_ksat_cm_hr
    ksat_cm_min = ksat_cm_hr / 60.0

    # Clamp to reasonable range
    ksat_cm_min = max(0.001, min(1.0, ksat_cm_min))
    return ksat_cm_min


def pedotransfer_wc(sand_pct, clay_pct, oc_pct, bd):
    """
    Estimate field capacity and wilting point using Rawls et al. (1982).
    Returns (wc_fc, wc_wp) in L/m3 (= mm water per m soil depth).

    Rawls: θ_fc (cm3/cm3) and θ_wp (cm3/cm3), then * 1000 for L/m3.
    """
    S = sand_pct / 100.0
    C = clay_pct / 100.0
    OM = oc_pct * 1.724  # OC% to OM%

    # Rawls et al. (1982) PTFs (simplified)
    theta_fc = 0.2576 - 0.0020 * sand_pct + 0.0036 * clay_pct + 0.0299 * OM
    theta_wp = 0.0260 + 0.0050 * clay_pct + 0.0158 * OM

    # Clamp
    theta_fc = max(0.10, min(0.55, theta_fc))
    theta_wp = max(0.02, min(0.35, theta_wp))
    if theta_wp >= theta_fc:
        theta_wp = theta_fc * 0.5

    # Convert cm3/cm3 to L/m3 (multiply by 1000)
    wc_fc = theta_fc * 1000.0
    wc_wp = theta_wp * 1000.0
    return wc_fc, wc_wp


def compute_usda_texture(sand, clay):
    """
    Return LDNDC soil type mnemonic from sand/clay percentages.

    Valid LDNDC mnemonics (from Lresources):
      SAND, LOSA, SALO, LOAM, SILO, SILT, SACL, SLCL, CLLO, SNCL, SICL, CLAY
    """
    silt = 100.0 - sand - clay
    if sand >= 85 and clay < 10:
        return "SAND"
    elif sand >= 70 and clay < 15:
        return "LOSA"
    elif (sand >= 43 and clay < 7 and silt < 50):
        return "SALO"
    elif (clay >= 7 and clay < 20 and sand > 52):
        return "SALO"
    elif (clay >= 7 and clay < 27 and silt >= 28 and silt < 50 and sand <= 52):
        return "LOAM"
    elif (silt >= 50 and clay >= 12 and clay < 27):
        return "SILO"
    elif (silt >= 50 and silt < 80 and clay < 12):
        return "SILO"
    elif silt >= 80 and clay < 12:
        return "SILT"
    elif (clay >= 20 and clay < 35 and silt < 28 and sand >= 45):
        return "SACL"
    elif (clay >= 20 and clay < 35 and silt >= 28):
        return "SLCL"
    elif (clay >= 27 and clay < 40 and sand >= 20 and sand <= 45):
        return "CLLO"
    elif (clay >= 35 and sand >= 45):
        return "SNCL"
    elif (clay >= 35 and clay < 60 and silt >= 40):
        return "SICL"
    elif clay >= 40:
        return "CLAY"
    else:
        return "LOAM"


def write_site_xml(soil: dict, output_path: Path) -> None:
    """Write LDNDC site.xml from HWSD soil data."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Topsoil: 0-30 cm (3 layers of 100 mm each)
    t_clay_frac = soil["t_clay"] / 100.0
    t_corg_frac = soil["t_oc"] / 100.0  # OC percentage → fraction
    t_sks = pedotransfer_sks(soil["t_sand"], soil["t_clay"], soil["t_oc"], soil["t_bd"])
    t_wc_fc, t_wc_wp = pedotransfer_wc(soil["t_sand"], soil["t_clay"], soil["t_oc"], soil["t_bd"])
    t_scel = soil["t_gravel"] / 100.0

    # Subsoil: 30-100 cm (4 layers of ~175 mm each, totalling 700 mm)
    s_clay_frac = soil["s_clay"] / 100.0
    # Fallback: if subsoil OC is NaN (common in alpine/HWSD sparse data), use 50% of topsoil OC
    import math
    if soil["s_oc"] is None or (isinstance(soil["s_oc"], float) and math.isnan(soil["s_oc"])):
        soil["s_oc"] = soil["t_oc"] * 0.5
    if soil["s_clay"] is None or (isinstance(soil["s_clay"], float) and math.isnan(soil["s_clay"])):
        soil["s_clay"] = soil["t_clay"]
    if soil["s_sand"] is None or (isinstance(soil["s_sand"], float) and math.isnan(soil["s_sand"])):
        soil["s_sand"] = soil["t_sand"]
    if soil["s_bd"] is None or (isinstance(soil["s_bd"], float) and math.isnan(soil["s_bd"])):
        soil["s_bd"] = soil["t_bd"]
    s_corg_frac = soil["s_oc"] / 100.0
    s_sks = pedotransfer_sks(soil["s_sand"], soil["s_clay"], soil["s_oc"], soil["s_bd"])
    s_wc_fc, s_wc_wp = pedotransfer_wc(soil["s_sand"], soil["s_clay"], soil["s_oc"], soil["s_bd"])
    s_scel = soil["s_gravel"] / 100.0

    # Deeper subsoil (100-200 cm): extrapolated, lower OC
    d_corg_frac = s_corg_frac * 0.5
    d_sks = s_sks * 0.8

    soil_type = compute_usda_texture(soil["t_sand"], soil["t_clay"])

    # Compute corg5 and corg30 for the general tag
    corg5 = t_corg_frac  # assume top 5cm same as topsoil
    corg30 = t_corg_frac * 0.9  # slight decrease over 0-30cm

    with open(output_path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write("<site>\n")
        f.write("  <description>\n")
        f.write(f"    <dataset>Bengbu-China-HWSD-MU{soil['mu_global']}</dataset>\n")
        f.write("  </description>\n")
        f.write("  <soil>\n")
        f.write(
            f'    <general usehistory="arable" corg5="{corg5:.4f}" '
            f'corg30="{corg30:.4f}" soil="{soil_type}" '
            f'humus="NONE" litterheight="0.0" />\n'
        )
        f.write("    <layers>\n")
        # Topsoil: 3 layers of 100 mm (0-30 cm)
        for i in range(3):
            depth_factor = 1.0 - 0.05 * i  # slight OC decrease with depth
            f.write(
                f'      <layer depth="100.0" bd="{soil["t_bd"]:.2f}" '
                f'clay="{t_clay_frac:.2f}" corg="{t_corg_frac * depth_factor:.4f}" '
                f'ph="{soil["t_ph"]:.1f}" scel="{t_scel:.2f}" '
                f'sks="{t_sks:.4f}" wc_fc="{t_wc_fc:.1f}" wc_wp="{t_wc_wp:.1f}" />\n'
            )
        # Subsoil: 4 layers of 175 mm (30-100 cm)
        for i in range(4):
            depth_factor = 1.0 - 0.1 * i
            f.write(
                f'      <layer depth="175.0" bd="{soil["s_bd"]:.2f}" '
                f'clay="{s_clay_frac:.2f}" corg="{s_corg_frac * depth_factor:.4f}" '
                f'ph="{soil["s_ph"]:.1f}" scel="{s_scel:.2f}" '
                f'sks="{s_sks:.4f}" wc_fc="{s_wc_fc:.1f}" wc_wp="{s_wc_wp:.1f}" />\n'
            )
        # Deep subsoil: 2 layers of 200 mm (100-140 cm)
        for i in range(2):
            f.write(
                f'      <layer depth="200.0" bd="{soil["s_bd"] + 0.05:.2f}" '
                f'clay="{s_clay_frac:.2f}" corg="{d_corg_frac:.4f}" '
                f'ph="{soil["s_ph"] + 0.2:.1f}" scel="{s_scel:.2f}" '
                f'sks="{d_sks:.4f}" wc_fc="{s_wc_fc - 10:.1f}" wc_wp="{s_wc_wp:.1f}" />\n'
            )
        f.write("    </layers>\n")
        f.write("  </soil>\n")
        f.write("</site>\n")

    logger.info(f"Site XML written: {output_path} (soil type={soil_type})")


# ── 4. Write setup.xml ────────────────────────────────────────────────────
def write_setup_xml(output_path: Path, lat: float, lon: float, elevation: float) -> None:
    """Write LDNDC setup.xml with standard arable modules."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write('<?xml version="1.0"?>\n')
        f.write("<ldndcsetup>\n")
        f.write(f'    <setup id="0" name="Bengbu_GHG">\n')
        f.write(
            f'        <location elevation="{elevation:.1f}" latitude="{lat:.2f}" '
            f'longitude="{lon:.2f}" slope="0" />\n'
        )
        f.write("        <models>\n")
        f.write('            <model id="_MoBiLE" />\n')
        f.write("        </models>\n")
        f.write("        <mobile>\n")
        f.write("            <modulelist>\n")
        f.write('                <module id="microclimate:canopyecm" timemode="subdaily" />\n')
        f.write('                <module id="watercycle:watercycledndc" timemode="subdaily" />\n')
        f.write('                <module id="airchemistry:airchemistrydndc" timemode="subdaily" />\n')
        f.write('                <module id="physiology:plamox" timemode="subdaily" />\n')
        f.write('                <module id="soilchemistry:metrx" timemode="subdaily" />\n')
        f.write("\n")
        f.write("                <!-- outputs -->\n")
        f.write('                <module id="output:microclimate:daily" />\n')
        f.write('                <module id="output:watercycle:daily" />\n')
        f.write('                <module id="output:physiology:daily" />\n')
        f.write('                <module id="output:soilchemistry:daily" />\n')
        f.write('                <module id="output:soilchemistry:yearly" />\n')
        f.write('                <module id="output:report:arable:harvest" timemode="subdaily" />\n')
        f.write('                <module id="output:report:arable:fertilize" timemode="subdaily" />\n')
        f.write("            </modulelist>\n")
        f.write("        </mobile>\n")
        f.write("    </setup>\n")
        f.write("</ldndcsetup>\n")

    logger.info(f"Setup XML written: {output_path}")


# ── 5. Write mana.xml (wheat-maize rotation for Bengbu) ──────────────────
def write_management_xml(output_path: Path, start_year: int, end_year: int) -> None:
    """
    Generate wheat-maize double cropping management for Bengbu.

    Typical Huai River Basin rotation:
      - Winter wheat: planted ~Oct 15-20, fertilized in spring, harvested ~Jun 5-10
      - Summer maize: planted ~Jun 12-15, fertilized in summer, harvested ~Oct 1-5

    N application: ~150-180 kgN/ha/yr wheat + ~150-180 kgN/ha/yr maize = ~300-360 kgN/ha/yr total
    (typical for intensive North China Plain agriculture)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write('<?xml version="1.0" ?>\n\n')
        f.write("<ldndcevent>\n")
        f.write('    <event id="0">\n')

        for yr in range(start_year, end_year + 1):
            f.write(f"\n        <!-- {yr} Winter Wheat season -->\n")

            # Till before wheat planting (previous autumn)
            if yr == start_year:
                # First year: till and plant wheat at start
                f.write(f'        <event type="till" time="{yr}-01-01">\n')
                f.write('            <till depth="0.15" />\n')
                f.write("        </event>\n")
                # Assume wheat was already planted previous Oct — just fertilize
                f.write(f'        <event type="plant" time="{yr}-01-02">\n')
                f.write('            <plant type="wiwh">\n')
                f.write('                <crop initialbiomass="150.0" />\n')
                f.write("            </plant>\n")
                f.write("        </event>\n")

            # Wheat spring topdressing — split application
            f.write(f'        <event type="fertilize" time="{yr}-03-10">\n')
            f.write('            <fertilize type="urea" amount="75" depth="0.05" />\n')
            f.write("        </event>\n")

            f.write(f'        <event type="fertilize" time="{yr}-04-20">\n')
            f.write('            <fertilize type="urea" amount="75" depth="0.05" />\n')
            f.write("        </event>\n")

            # Wheat harvest
            f.write(f'        <event type="harvest" time="{yr}-06-08">\n')
            f.write('            <harvest name="wiwh" remains="0.65" />\n')
            f.write("        </event>\n")

            # ── Summer maize season ──
            f.write(f"\n        <!-- {yr} Summer Maize season -->\n")

            # Till after wheat harvest
            f.write(f'        <event type="till" time="{yr}-06-10">\n')
            f.write('            <till depth="0.10" />\n')
            f.write("        </event>\n")

            # Maize planting + basal fertilizer
            f.write(f'        <event type="plant" time="{yr}-06-14">\n')
            f.write('            <plant type="CORN">\n')
            f.write('                <crop initialbiomass="150.0" />\n')
            f.write("            </plant>\n")
            f.write("        </event>\n")

            f.write(f'        <event type="fertilize" time="{yr}-06-15">\n')
            f.write('            <fertilize type="urea" amount="100" depth="0.05" />\n')
            f.write("        </event>\n")

            # Maize topdressing
            f.write(f'        <event type="fertilize" time="{yr}-07-20">\n')
            f.write('            <fertilize type="urea" amount="80" depth="0.05" />\n')
            f.write("        </event>\n")

            # Maize harvest
            f.write(f'        <event type="harvest" time="{yr}-10-01">\n')
            f.write('            <harvest name="CORN" remains="0.65" />\n')
            f.write("        </event>\n")

            # ── Prepare for next year's wheat ──
            if yr < end_year:
                f.write(f'\n        <!-- {yr} autumn — prepare for {yr + 1} wheat -->\n')
                f.write(f'        <event type="till" time="{yr}-10-10">\n')
                f.write('            <till depth="0.20" />\n')
                f.write("        </event>\n")

                # Wheat planting
                f.write(f'        <event type="plant" time="{yr}-10-18">\n')
                f.write('            <plant type="wiwh">\n')
                f.write('                <crop initialbiomass="150.0" />\n')
                f.write("            </plant>\n")
                f.write("        </event>\n")

                # Basal fertilizer for wheat
                f.write(f'        <event type="fertilize" time="{yr}-10-19">\n')
                f.write('            <fertilize type="nh4no3" amount="30" depth="0.05" />\n')
                f.write("        </event>\n")

        f.write("\n    </event>\n")
        f.write("</ldndcevent>\n")

    logger.info(f"Management XML written: {output_path} ({start_year}-{end_year})")


# ── 6. Write airchem.txt ─────────────────────────────────────────────────
def write_airchem(output_path: Path) -> None:
    """
    Write atmospheric chemistry file for eastern China.

    N deposition ~15-20 kgN/ha/yr for Huai River Basin (Liu et al. 2013).
    Split: ~60% NH4, ~40% NO3.
    LDNDC uses ug N/m3 for NH4 and NO3 in air.
    At 15 kgN/ha/yr: roughly NH4=1.2 ugN/m3, NO3=0.8 ugN/m3
    (depends on deposition velocity; use empirical values for eastern China)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        # Columns match Gebesee format
        f.write("nh4       no3       ch4     co2     o3      nh3     no2     no\n")
        # Higher deposition for eastern China (industrialized agriculture region)
        f.write("1.20      0.80      0.0     400.0   0.0     0.0     0.0     0.0\n")

    logger.info(f"Airchemistry file written: {output_path}")


# ── 7. Write project.ldndc ───────────────────────────────────────────────
def write_project_xml(output_path: Path, start_year: int, end_year: int, run_tag: str = "bengbu") -> None:
    """Write LDNDC project descriptor XML."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nyears = end_year - start_year + 1

    with open(output_path, "w") as f:
        f.write('<?xml version="1.0" ?>\n')
        f.write('<ldndcproject PackageMinimumVersionRequired="1.3">\n')
        f.write(
            f'    <schedule time="{start_year}-01-01/24 -> +{nyears}-0-0" />\n'
        )
        f.write("    <input>\n")
        f.write(f'        <sources sourceprefix="arable/{run_tag}/bengbu_">\n')
        f.write('            <setup source="setup.xml" />\n')
        f.write('            <site source="site.xml" />\n')
        f.write('            <airchemistry source="airchem.txt" format="txt" />\n')
        f.write('            <climate source="climate.txt" format="txt" />\n')
        f.write('            <event source="mana.xml" />\n')
        f.write("        </sources>\n")
        f.write('        <attributes use="0" endless="0">\n')
        f.write('            <airchemistry endless="yes" />\n')
        f.write('            <climate endless="1" />\n')
        f.write("        </attributes>\n")
        f.write("    </input>\n")
        f.write("    <output>\n")
        f.write(f'        <sinks sinkprefix="arable/{run_tag}/{run_tag}_output/bengbu_" />\n')
        f.write("    </output>\n")
        f.write("</ldndcproject>\n")

    logger.info(f"Project XML written: {output_path}")


# ── 8. Run LDNDC ─────────────────────────────────────────────────────────
def run_ldndc(project_file: Path) -> int:
    """Execute LDNDC binary with the project file."""
    logger.info(f"Running LDNDC: {LDNDC_BIN} {project_file.name}")
    logger.info(f"Working directory: {LDNDC_BASE}")

    # LDNDC expects to be run from its base directory so it can find
    # Lresources/, parameters/, and the dotfiles/.ldndc config
    result = subprocess.run(
        [str(LDNDC_BIN), str(project_file)],
        cwd=str(LDNDC_BASE),
        capture_output=True,
        text=True,
        timeout=3600,
    )

    if result.stdout:
        # Print last 3000 chars of stdout
        stdout_tail = result.stdout[-3000:]
        logger.info(f"LDNDC stdout (tail):\n{stdout_tail}")

    if result.stderr:
        stderr_tail = result.stderr[-2000:]
        logger.warning(f"LDNDC stderr (tail):\n{stderr_tail}")

    if result.returncode != 0:
        logger.error(f"LDNDC exited with code {result.returncode}")
        combined = result.stdout + result.stderr
        if "Cannot open" in combined or "not found" in combined:
            logger.error("File not found — check sourceprefix in project.ldndc")
        if "Segmentation fault" in combined:
            logger.error("Segfault — check site.xml for invalid soil parameters")
    else:
        logger.info("LDNDC completed successfully.")

    return result.returncode


# ── 9. Parse output ──────────────────────────────────────────────────────
def parse_output(output_dir: Path, start_year: int, end_year: int) -> dict:
    """
    Parse LDNDC soilchemistry output files and compute annual GHG budgets.

    Key columns in soilchemistry-daily.txt:
      dN_n2o_emis[kgNha-1]  — daily N2O emission (kgN/ha)
      dC_ch4_emis[kgCha-1]  — daily CH4 emission (kgC/ha)
      dC_co2_emis_hetero[kgCha-1] — daily heterotrophic CO2 (kgC/ha)
      dN_no3_leach[kgNha-1] — daily NO3 leaching (kgN/ha)
      dN_no_emis[kgNha-1]   — daily NO emission (kgN/ha)
      dN_n2_emis[kgNha-1]   — daily N2 emission (kgN/ha)
      dN_nh3_emis[kgNha-1]  — daily NH3 emission (kgN/ha)
    """
    results = {"years": {}, "totals": {}, "output_dir": str(output_dir)}

    # Find the soilchemistry daily file
    daily_files = list(output_dir.glob("*soilchemistry-daily.txt"))
    yearly_files = list(output_dir.glob("*soilchemistry-yearly.txt"))

    if not daily_files:
        logger.warning("No soilchemistry-daily.txt found")
        # Try to list what files exist
        existing = [f.name for f in output_dir.iterdir()] if output_dir.exists() else []
        logger.info(f"Files in output dir: {existing}")
        return results

    daily_file = daily_files[0]
    logger.info(f"Parsing: {daily_file}")

    # Read daily data
    with open(daily_file) as f:
        header = f.readline().strip().split("\t")
        data_lines = f.readlines()

    logger.info(f"Columns: {len(header)}, Data rows: {len(data_lines)}")

    # Find column indices
    col_map = {name: idx for idx, name in enumerate(header)}

    # Key GHG columns
    n2o_col = None
    ch4_col = None
    co2_hetero_col = None
    co2_auto_col = None
    no3_leach_col = None
    no_col = None
    n2_col = None
    nh3_col = None
    datetime_col = None

    for name, idx in col_map.items():
        if "n2o_emis" in name:
            n2o_col = idx
        if "ch4_emis" in name:
            ch4_col = idx
        if "co2_emis_hetero" in name:
            co2_hetero_col = idx
        if "co2_emis_auto" in name:
            co2_auto_col = idx
        if "no3_leach" in name:
            no3_leach_col = idx
        if "no_emis" in name and "n2o" not in name:
            no_col = idx
        if "n2_emis" in name and "n2o" not in name:
            n2_col = idx
        if "nh3_emis" in name:
            nh3_col = idx
        if "datetime" in name.lower():
            datetime_col = idx

    logger.info(
        f"Column indices: N2O={n2o_col}, CH4={ch4_col}, CO2h={co2_hetero_col}, "
        f"CO2a={co2_auto_col}, NO3={no3_leach_col}, NO={no_col}, datetime={datetime_col}"
    )

    # Aggregate by year
    annual = {}
    for line in data_lines:
        parts = line.strip().split("\t")
        if len(parts) < max(
            x for x in [n2o_col, ch4_col, co2_hetero_col, no3_leach_col, datetime_col]
            if x is not None
        ) + 1:
            continue

        # Extract year from datetime column
        try:
            dt_str = parts[datetime_col]
            year = int(dt_str[:4])
        except (ValueError, IndexError):
            continue

        if year not in annual:
            annual[year] = {
                "n2o_kgN_ha": 0.0,
                "ch4_kgC_ha": 0.0,
                "co2_hetero_kgC_ha": 0.0,
                "co2_auto_kgC_ha": 0.0,
                "no3_leach_kgN_ha": 0.0,
                "no_emis_kgN_ha": 0.0,
                "n2_emis_kgN_ha": 0.0,
                "nh3_emis_kgN_ha": 0.0,
                "days": 0,
            }

        def safe_val(idx):
            try:
                return float(parts[idx]) if idx is not None else 0.0
            except (ValueError, IndexError):
                return 0.0

        annual[year]["n2o_kgN_ha"] += safe_val(n2o_col)
        annual[year]["ch4_kgC_ha"] += safe_val(ch4_col)
        annual[year]["co2_hetero_kgC_ha"] += safe_val(co2_hetero_col)
        annual[year]["co2_auto_kgC_ha"] += safe_val(co2_auto_col)
        annual[year]["no3_leach_kgN_ha"] += safe_val(no3_leach_col)
        annual[year]["no_emis_kgN_ha"] += safe_val(no_col)
        annual[year]["n2_emis_kgN_ha"] += safe_val(n2_col)
        annual[year]["nh3_emis_kgN_ha"] += safe_val(nh3_col)
        annual[year]["days"] += 1

    # Compute CO2-equivalent GHG budget
    for yr, vals in sorted(annual.items()):
        # N2O: kgN/ha * 44/28 = kg N2O/ha; GWP100 = 298
        n2o_co2eq = vals["n2o_kgN_ha"] * (44.0 / 28.0) * 298.0
        # CH4: kgC/ha * 16/12 = kg CH4/ha; GWP100 = 25
        ch4_co2eq = vals["ch4_kgC_ha"] * (16.0 / 12.0) * 25.0
        # Net CO2: (heterotrophic - autotrophic) * 44/12
        net_co2 = (vals["co2_hetero_kgC_ha"] - vals["co2_auto_kgC_ha"]) * (44.0 / 12.0)

        vals["n2o_kg_ha"] = vals["n2o_kgN_ha"] * (44.0 / 28.0)
        vals["n2o_co2eq_kg_ha"] = n2o_co2eq
        vals["ch4_co2eq_kg_ha"] = ch4_co2eq
        vals["net_co2_kg_ha"] = net_co2
        vals["total_ghg_co2eq_kg_ha"] = n2o_co2eq + ch4_co2eq + net_co2

        results["years"][str(yr)] = vals

    # Compute period totals and averages
    all_years = sorted(annual.keys())
    if all_years:
        n = len(all_years)
        results["totals"] = {
            "period": f"{min(all_years)}-{max(all_years)}",
            "n_years": n,
            "avg_n2o_kgN_ha_yr": sum(annual[y]["n2o_kgN_ha"] for y in all_years) / n,
            "avg_n2o_kg_ha_yr": sum(annual[y].get("n2o_kg_ha", 0) for y in all_years) / n,
            "avg_ch4_kgC_ha_yr": sum(annual[y]["ch4_kgC_ha"] for y in all_years) / n,
            "avg_co2_hetero_kgC_ha_yr": sum(annual[y]["co2_hetero_kgC_ha"] for y in all_years) / n,
            "avg_no3_leach_kgN_ha_yr": sum(annual[y]["no3_leach_kgN_ha"] for y in all_years) / n,
            "avg_total_ghg_co2eq_kg_ha_yr": sum(
                annual[y].get("total_ghg_co2eq_kg_ha", 0) for y in all_years
            ) / n,
        }

    return results


# ── 10. Also parse yearly output if available ────────────────────────────
def parse_yearly_output(output_dir: Path) -> dict:
    """Parse soilchemistry-yearly.txt for a quick summary."""
    yearly_files = list(output_dir.glob("*soilchemistry-yearly.txt"))
    if not yearly_files:
        return {}

    yearly_file = yearly_files[0]
    logger.info(f"Parsing yearly file: {yearly_file}")

    with open(yearly_file) as f:
        header = f.readline().strip().split("\t")
        data_lines = f.readlines()

    col_map = {name: idx for idx, name in enumerate(header)}
    yearly_data = {}

    for line in data_lines:
        parts = line.strip().split("\t")
        if len(parts) < 5:
            continue
        try:
            dt_col = col_map.get("datetime", 2)
            year = int(parts[dt_col][:4])
        except (ValueError, IndexError):
            continue

        def safe_val(col_name):
            idx = col_map.get(col_name)
            if idx is None:
                return None
            try:
                return float(parts[idx])
            except (ValueError, IndexError):
                return None

        yearly_data[year] = {
            "n2o_kgN_ha": safe_val("aN_n2o_emis[kgNha-1]"),
            "ch4_kgC_ha": safe_val("aC_ch4_emis[kgCha-1]"),
            "co2_hetero_kgC_ha": safe_val("aC_co2_emis_hetero[kgCha-1]"),
            "no3_leach_kgN_ha": safe_val("aN_no3_leach[kgNha-1]"),
            "n_plant_uptake_kgN_ha": safe_val("aN_plant_uptake[kgNha-1]"),
            "n_fertilize_kgN_ha": safe_val("aN_fertilize[kgNha-1]"),
            "c_soil_kgC_ha": safe_val("C_soil[kgCha-1]"),
        }

    return yearly_data


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Run LDNDC GHG simulation for Bengbu using VIC forcing"
    )
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT, help="Latitude")
    parser.add_argument("--lon", type=float, default=DEFAULT_LON, help="Longitude")
    parser.add_argument("--elevation", type=float, default=DEFAULT_ELEVATION, help="Elevation (m)")
    parser.add_argument(
        "--forcing_file",
        type=str,
        default=None,
        help="Path to VIC forcing file (auto-detected if not set)",
    )
    parser.add_argument(
        "--forcing_dir",
        type=str,
        default=str(VIC_FORCING_DIR),
        help="Directory with VIC forcing files",
    )
    parser.add_argument("--start_year", type=int, default=START_YEAR)
    parser.add_argument("--end_year", type=int, default=END_YEAR)
    parser.add_argument("--scenario_tag", type=str, default="", help="Optional scenario tag appended to run_tag (e.g. ssp245)")
    parser.add_argument("--dry_run", action="store_true", help="Generate files but do not run LDNDC")
    args = parser.parse_args()

    lat = args.lat
    lon = args.lon
    elevation = args.elevation
    start_year = args.start_year
    end_year = args.end_year

    logger.info("=" * 60)
    logger.info("LDNDC Bengbu GHG Simulation Pipeline")
    logger.info(f"Location: ({lat}, {lon}), Elevation: {elevation} m")
    logger.info(f"Period: {start_year}-{end_year}")
    logger.info("=" * 60)

    # ── Step 1: Find forcing file ──
    if args.forcing_file:
        forcing_file = Path(args.forcing_file)
        if not forcing_file.exists():
            logger.error(f"Forcing file not found: {forcing_file}")
            sys.exit(1)
    else:
        forcing_dir = Path(args.forcing_dir)
        if not forcing_dir.exists():
            logger.error(f"Forcing directory not found: {forcing_dir}")
            sys.exit(1)
        forcing_file = find_nearest_forcing(forcing_dir, lat, lon)

    # ── Set up project directory (unique per lat/lon/year to allow parallel runs) ──
    scen_suffix = f"_{args.scenario_tag}" if args.scenario_tag else ""
    run_tag = f"longpan_{lat:.4f}_{lon:.4f}_{start_year}{scen_suffix}"
    project_dir = PROJECTS_DIR / "arable" / run_tag
    output_dir = project_dir / f"{run_tag}_output"
    project_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 2: Convert VIC forcing → LDNDC climate ──
    logger.info("\n--- Step 2: Convert VIC forcing to LDNDC climate ---")
    climate_path = project_dir / "bengbu_climate.txt"
    vic_forcing_to_ldndc_climate(forcing_file, climate_path, lat, lon, elevation, start_year)

    # ── Step 3: Extract HWSD soil → site.xml ──
    logger.info("\n--- Step 3: Extract HWSD soil data ---")
    soil = get_hwsd_soil(lat, lon)
    site_path = project_dir / "bengbu_site.xml"
    write_site_xml(soil, site_path)
    # Post-process: replace corg=0.0000 with minimum floor to prevent CN initialization failure
    import re as _re
    _site_txt = site_path.read_text()
    _site_txt = _re.sub(r'corg="0\.0000"', 'corg="0.0005"', _site_txt)
    site_path.write_text(_site_txt)
    logger.info("  Applied corg floor: replaced corg=0.0000 → 0.0005 in site.xml")

    # ── Step 4: Write setup.xml ──
    logger.info("\n--- Step 4: Write setup.xml ---")
    setup_path = project_dir / "bengbu_setup.xml"
    write_setup_xml(setup_path, lat, lon, elevation)

    # ── Step 5: Write management ──
    logger.info("\n--- Step 5: Write management (wheat-maize rotation) ---")
    mana_path = project_dir / "bengbu_mana.xml"
    write_management_xml(mana_path, start_year, end_year)

    # ── Step 6: Write airchemistry ──
    logger.info("\n--- Step 6: Write airchemistry ---")
    airchem_path = project_dir / "bengbu_airchem.txt"
    write_airchem(airchem_path)

    # ── Step 7: Write project.ldndc ──
    logger.info("\n--- Step 7: Write project.ldndc ---")
    project_xml_path = project_dir / "bengbu.ldndc"
    write_project_xml(project_xml_path, start_year, end_year, run_tag=run_tag)

    # Summary of generated files
    logger.info("\n--- Generated files ---")
    for p in [climate_path, site_path, setup_path, mana_path, airchem_path, project_xml_path]:
        size = p.stat().st_size if p.exists() else 0
        logger.info(f"  {p.name}: {size:,} bytes")

    if args.dry_run:
        logger.info("\n--- DRY RUN: Skipping LDNDC execution ---")
        print(json.dumps({"status": "dry_run", "project_dir": str(project_dir)}, indent=2))
        return

    # ── Step 8: Run LDNDC ──
    logger.info("\n--- Step 8: Run LDNDC ---")
    # Project path relative to LDNDC base (since ldndc.conf sets input_path=projects)
    project_rel = project_xml_path.relative_to(LDNDC_BASE)
    exit_code = run_ldndc(project_rel)

    if exit_code != 0:
        logger.error(f"LDNDC failed with exit code {exit_code}")
        # Check log file
        log_file = output_dir / "bengbu_ldndc.log"
        if log_file.exists():
            logger.info(f"Check log: {log_file}")
            with open(log_file) as f:
                tail = f.readlines()[-30:]
            for line in tail:
                logger.info(f"  LOG: {line.rstrip()}")
        sys.exit(exit_code)

    # ── Step 9: Parse output ──
    logger.info("\n--- Step 9: Parse LDNDC output ---")
    results = parse_output(output_dir, start_year, end_year)

    # Also parse yearly summary
    yearly = parse_yearly_output(output_dir)
    if yearly:
        results["yearly_summary"] = {
            str(k): v for k, v in sorted(yearly.items())
        }

    # ── Print results ──
    logger.info("\n" + "=" * 60)
    logger.info("ANNUAL GHG BUDGET SUMMARY")
    logger.info("=" * 60)

    for yr_str, vals in sorted(results.get("years", {}).items()):
        yr = yr_str
        logger.info(f"\n  Year {yr} ({vals.get('days', '?')} days):")
        logger.info(f"    N2O emission:    {vals['n2o_kgN_ha']:.3f} kgN/ha "
                     f"({vals.get('n2o_kg_ha', 0):.3f} kg N2O/ha)")
        logger.info(f"    CH4 emission:    {vals['ch4_kgC_ha']:.6f} kgC/ha")
        logger.info(f"    CO2 hetero resp: {vals['co2_hetero_kgC_ha']:.1f} kgC/ha")
        logger.info(f"    NO3 leaching:    {vals['no3_leach_kgN_ha']:.2f} kgN/ha")
        logger.info(f"    NO emission:     {vals['no_emis_kgN_ha']:.3f} kgN/ha")
        logger.info(f"    GHG total:       {vals.get('total_ghg_co2eq_kg_ha', 0):.1f} kg CO2eq/ha")

    if results.get("totals"):
        t = results["totals"]
        logger.info(f"\n  Period averages ({t['period']}, {t['n_years']} years):")
        logger.info(f"    N2O: {t['avg_n2o_kgN_ha_yr']:.3f} kgN/ha/yr "
                     f"({t['avg_n2o_kg_ha_yr']:.3f} kg N2O/ha/yr)")
        logger.info(f"    CH4: {t['avg_ch4_kgC_ha_yr']:.6f} kgC/ha/yr")
        logger.info(f"    CO2 (Rh): {t['avg_co2_hetero_kgC_ha_yr']:.1f} kgC/ha/yr")
        logger.info(f"    NO3 leach: {t['avg_no3_leach_kgN_ha_yr']:.2f} kgN/ha/yr")
        logger.info(f"    Total GHG: {t['avg_total_ghg_co2eq_kg_ha_yr']:.1f} kg CO2eq/ha/yr")

    # Output JSON
    json_path = output_dir / f"{run_tag}_ghg_summary.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"\nJSON summary written: {json_path}")

    # Also print compact JSON to stdout
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
