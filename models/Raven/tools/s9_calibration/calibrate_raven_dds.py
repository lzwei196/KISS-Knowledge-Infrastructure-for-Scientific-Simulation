#!/usr/bin/env python3
"""
calibrate_raven_dds.py — DDS (Dynamically Dimensioned Search) calibration for Raven.

Implements the DDS algorithm (Tolson & Shoemaker, 2007) natively in Python,
consistent with HydroCraft's AI calibration approach. No external Ostrich dependency.

Modifies parameters in the .rvp file, runs Raven, reads Diagnostics.csv,
and iterates to maximize NSE (or minimize any objective function).

Usage:
    python calibrate_raven_dds.py \
        --run_dir outputs/chaohe_raven/ \
        --basin_name chaohe \
        --template hbv_ec \
        --n_iterations 100 \
        --objective NSE \
        --raven_exe /mnt/disk1/Hydrocraft_server/model/raven/Raven.exe
"""

import argparse
import json
import os
import sys
import subprocess
import shutil
import time
import re
from datetime import datetime

try:
    import numpy as np
    import pandas as pd
except ImportError:
    print(json.dumps({"status": "error", "message": "numpy and pandas required"}))
    sys.exit(1)

# The calendar-dated series reader and the Diagnostics.csv parser live in the s7
# tool; import them rather than re-deriving Raven's period-ending convention or
# its diagnostics layout here (dt_rav_034 and dt_rav_037 were each reintroduced
# once already by a local re-implementation).
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "s7_output"))
from parse_raven_output import load_discharge_series, parse_diagnostics  # noqa: E402

RAVEN_EXE_DEFAULT = "/mnt/disk1/Hydrocraft_server/model/raven/Raven.exe"

# Calibration parameter definitions per template
# name: (min, max, default, description)
CALIBRATION_PARAMS = {
    "gr4j": {
        "GR4J_X1": (1.0, 1500.0, 350.0, "Production store capacity (mm)"),
        "GR4J_X2": (-10.0, 5.0, 0.0, "GW exchange coefficient (mm/d)"),
        "GR4J_X3": (1.0, 500.0, 90.0, "Routing store capacity (mm)"),
        "GR4J_X4": (0.5, 10.0, 1.5, "Unit hydrograph time base (d)"),
    },
    "hbv_ec": {
        "MELT_FACTOR": (1.0, 10.0, 4.0, "Degree-day snowmelt factor (LandUse)"),
        "MIN_MELT_FACTOR": (0.5, 5.0, 2.0, "Minimum (winter) melt factor (LandUse)"),
        "REFREEZE_FACTOR": (0.5, 6.0, 2.0, "Refreeze factor (LandUse)"),
        "HBV_MELT_FOR_CORR": (0.3, 1.2, 0.70, "Forest melt correction (LandUse)"),
        "HBV_BETA": (0.5, 6.0, 2.0, "Soil moisture nonlinearity (Soil)"),
        "MAX_PERC_RATE": (0.1, 10.0, 2.0, "Max percolation rate mm/d (Soil)"),
        "MAX_CAP_RISE_RATE": (0.0, 5.0, 1.0, "Max capillary rise rate (Soil)"),
        "BASEFLOW_COEFF": (0.001, 0.5, 0.05, "Baseflow recession 1/d (Soil)"),
        "BASEFLOW_N": (1.0, 3.0, 1.0, "Baseflow power-law exponent (Soil)"),
        "FIELD_CAPACITY": (0.1, 0.55, 0.31, "Field capacity (Soil)"),
        "SAT_WILT": (0.01, 0.25, 0.155, "Wilting point saturation (Soil)"),
        "POROSITY": (0.30, 0.60, 0.451, "Soil porosity (Soil)"),
    },
    # HMETS calibration set — only parameters actually emitted by
    # build_rvp_parameters.py for the hmets template (verified present in the
    # generated .rvp). The previous set used DEGREE_DAY_MELT_FACTOR /
    # DD_MELT_TEMP which do not appear in the .rvp, so DDS optimised nothing.
    "hmets": {
        "HMETS_RUNOFF_COEFF": (0.02, 0.9, 0.3, "Direct-runoff coefficient (LandUse)"),
        "GAMMA_SHAPE": (1.0, 12.0, 3.0, "Routing gamma shape (LandUse)"),
        "GAMMA_SCALE": (0.05, 4.0, 0.5, "Routing gamma scale (LandUse)"),
        "GAMMA_SHAPE2": (1.0, 12.0, 3.0, "Delayed-runoff gamma shape (LandUse)"),
        "GAMMA_SCALE2": (0.05, 4.0, 0.5, "Delayed-runoff gamma scale (LandUse)"),
        # HMETS has NO MELT_FACTOR — it uses a seasonally varying min/max pair
        # plus a snow-aggradation term. Leaving these fixed left HMETS melt
        # entirely uncalibrated (dt_rav_043).
        "MIN_MELT_FACTOR": (0.5, 5.0, 2.0, "Minimum (winter) melt factor (LandUse)"),
        "MAX_MELT_FACTOR": (2.0, 12.0, 6.0, "Maximum (spring) melt factor (LandUse)"),
        "DD_AGGRADATION": (0.0, 0.5, 0.05, "Melt-factor aggradation rate (LandUse)"),
        "REFREEZE_FACTOR": (0.5, 6.0, 2.0, "Refreeze factor (LandUse)"),
        "POROSITY": (0.30, 0.60, 0.451, "Soil porosity (Soil)"),
        "PERC_COEFF": (0.001, 0.5, 0.05, "Percolation coefficient (Soil)"),
        "BASEFLOW_COEFF": (0.001, 0.30, 0.05, "Baseflow recession (Soil)"),
    },
    "hymod": {
        "HYMOD_CMAX": (1.0, 1000.0, 200.0, "Max soil moisture capacity"),
        "HYMOD_B": (0.0, 2.0, 0.5, "Spatial variability index"),
        "HYMOD_ALPHA": (0.0, 1.0, 0.7, "Quick/slow flow partition"),
        "HYMOD_KS": (0.001, 0.1, 0.01, "Slow reservoir rate"),
        "HYMOD_KQ": (0.1, 0.99, 0.3, "Quick reservoir rate"),
        "PDM_B": (0.1, 2.0, 0.5, "PDM storage-distribution shape (LandUse)"),
        "POROSITY": (0.30, 0.60, 0.451, "Soil porosity (Soil)"),
        "BASEFLOW_COEFF": (0.001, 0.30, 0.05, "Baseflow recession (Soil)"),
    },
    # SAC-SMA as emitted by build_rvp_parameters.py: Raven's SOILEVAP_SACSMA /
    # PERC_SACRAMENTO emulation declares SAC_PERC_* + UNAVAIL_FRAC, NOT the
    # SAC_UZTWM/SAC_LZPK names of the standalone NWSRFS code. Those names never
    # appear in the .rvp, so DDS optimised nothing (dt_rav_037).
    "sac_sma": {
        "SAC_PERC_ALPHA": (1.0, 250.0, 50.0, "Percolation alpha (Soil)"),
        "SAC_PERC_EXPON": (0.5, 5.0, 2.0, "Percolation exponent (Soil)"),
        "SAC_PERC_PFREE": (0.0, 0.8, 0.06, "Free-water percolation fraction (Soil)"),
        "UNAVAIL_FRAC": (0.0, 0.5, 0.1, "Unavailable soil-water fraction (Soil)"),
        "BASEFLOW_COEFF": (0.001, 0.3, 0.05, "Baseflow recession (Soil)"),
        "POROSITY": (0.30, 0.60, 0.451, "Soil porosity (Soil)"),
        "MAX_SAT_AREA_FRAC": (0.0, 0.5, 0.1, "Max saturated area fraction (LandUse)"),
        "BF_LOSS_FRACTION": (0.0, 0.4, 0.10, "Baseflow loss fraction (LandUse)"),
    },
    # Snowmelt is the DOMINANT process in a cold/alpine basin, so each
    # template's own melt controls must be free. The generic MELT_FACTOR /
    # DD_MELT_TEMP of SHARED_PARAMS only exist for degree-day templates; UBCWM,
    # HMETS and HBV each expose a different melt parameterisation, and leaving
    # those at their defaults left the dominant process UNCALIBRATED (dt_rav_043).
    "ubc": {
        "RAIN_MELT_MULT": (0.2, 3.0, 1.0, "Rain-on-snow melt multiplier (LandUse)"),
        "CONV_MELT_MULT": (0.2, 3.0, 1.0, "Convective melt multiplier (LandUse)"),
        "COND_MELT_MULT": (0.2, 3.0, 1.0, "Condensation melt multiplier (LandUse)"),
        "CC_DECAY_COEFF": (0.0, 0.5, 0.05, "Cold-content decay coefficient (LandUse)"),
        "UBC_GW_SPLIT": (0.0, 1.0, 0.5, "Deep/shallow GW split (Global)"),
        "UBC_FLASH_PONDING": (10.0, 120.0, 36.0, "Flash-runoff ponding depth (Global)"),
        "UBC_EVAP_SOIL_DEF": (10.0, 300.0, 100.0, "Soil deficit at which AET->0 (Soil)"),
        "UBC_INFIL_SOIL_DEF": (10.0, 300.0, 100.0, "Soil deficit controlling infiltration (Soil)"),
        "MAX_PERC_RATE": (0.1, 20.0, 2.0, "Max percolation rate (Soil)"),
        "PERC_COEFF": (0.001, 0.5, 0.05, "Percolation coefficient (Soil)"),
        "BASEFLOW_COEFF": (0.001, 0.3, 0.05, "Baseflow recession (Soil)"),
        "POROSITY": (0.30, 0.60, 0.451, "Soil porosity (Soil)"),
    },
    "mohyse": {
        "HBV_BETA": (0.5, 6.0, 2.0, "Soil moisture nonlinearity (Soil)"),
        "PERC_COEFF": (0.001, 0.5, 0.05, "Percolation coefficient (Soil)"),
        "BASEFLOW_COEFF": (0.001, 0.3, 0.05, "Baseflow recession (Soil)"),
        "POROSITY": (0.30, 0.60, 0.451, "Soil porosity (Soil)"),
        "AET_COEFF": (0.1, 3.0, 1.0, "AET coefficient (LandUse)"),
    },
    "hypr": {
        "HBV_BETA": (0.5, 6.0, 2.0, "Soil moisture nonlinearity (Soil)"),
        "FIELD_CAPACITY": (0.10, 0.55, 0.31, "Field capacity (Soil)"),
        "SAT_WILT": (0.01, 0.25, 0.155, "Wilting point saturation (Soil)"),
        "PERC_COEFF": (0.001, 0.5, 0.05, "Percolation coefficient (Soil)"),
        "BASEFLOW_COEFF": (0.001, 0.3, 0.05, "Baseflow recession (Soil)"),
        "BASEFLOW_N": (1.0, 3.0, 1.0, "Baseflow power-law exponent (Soil)"),
        "POROSITY": (0.30, 0.60, 0.451, "Soil porosity (Soil)"),
        "REFREEZE_FACTOR": (0.5, 6.0, 2.0, "Refreeze factor (LandUse)"),
    },
}

# Parameters shared across templates. Appended to every set, then filtered
# against the .rvp Raven actually declared (see filter_present_parameters):
# every emulation needs its PET scaled and its precipitation phase / melt
# threshold set, and any run with orographic corrections ON exposes the two
# lapse rates as free parameters. Calibrating a name that is ABSENT from the
# .rvp silently wastes a DDS dimension, so absent names are dropped and
# reported rather than optimised.
SHARED_PARAMS = {
    "PET_CORRECTION": (0.4, 2.5, 1.0, "PET multiplier (Soil)"),
    "MELT_FACTOR": (1.0, 10.0, 4.0, "Degree-day melt factor (LandUse)"),
    "DD_MELT_TEMP": (-3.0, 3.0, 0.0, "Degree-day melt threshold (LandUse)"),
    "RAINSNOW_TEMP": (-3.0, 3.0, 0.0, "Rain/snow partition temperature (Global)"),
    # dt_rav_040: with :OroTempCorrect/:OroPrecipCorrect SIMPLELAPSE active these
    # two set the elevation gradient across the HRU bands. They dominate snow
    # accumulation and melt timing in an alpine basin.
    "ADIABATIC_LAPSE": (3.0, 9.8, 6.5, "Temperature lapse rate C/km (Global)"),
    "PRECIP_LAPSE": (0.0, 3.0, 0.0, "Precipitation lapse rate mm/d/km (Global)"),
}


# dt_rav_045: ONE emulation parameter is read by Raven from the :SoilProfiles
# LAYER THICKNESS instead of from a named parameter column -- the GR4J
# production-store capacity X1.  The .rvi declares ":Alias PRODUCT_STORE
# SOIL[0]" and drives INF_GR4J / SOILEVAP_GR4J / PERC_GR4J off that store, whose
# capacity is thickness_m * POROSITY * 1000.  build_rvp_parameters.py emits it as
#     thickness = TEMPLATE_LAYER_STORAGE_MM["gr4j"][i] / 1000.0 / porosity
# (build_rvp_parameters.py:299; gr4j caps = [350.0, 300.0, 1000.0, 1000.0]).
# There is no GR4J_X1 column anywhere in the generated .rvp, so
# parameter_in_rvp() -- which scanned only :GlobalParameter lines and
# ":Parameters," headers -- dropped it into skipped_parameters_absent_from_rvp
# and the production store stayed frozen at the generic 350 mm default for all
# 1000 DDS evaluations, leaving X2/X3 pinned at their bounds to compensate.
#
# SCOPE (reviewer note, 2026-07-27): X3 is deliberately NOT in this table.
# Although the ROUTING_STORE (SOIL[1]) thickness also carries a capacity, GR4J_X3
# IS emitted as a named :SoilParameterList column in this KI's .rvp
#     :Parameters, POROSITY, PET_CORRECTION, ALBEDO_WET, ALBEDO_DRY, GR4J_X2, GR4J_X3,
# and Raven reads it from there for BASE_GR4J / PERC_GR4JEXCH.  It was never in
# skipped_parameters (result.json calibrated_parameters lists GR4J_X3), so it
# needs no unblocking here, and RavenPy's GR4J emulator likewise keeps SOIL[1]
# thickness FIXED (0.3 m) while exposing X3 through SoilParameterList.  Adding it
# would rewrite fixed routing-layer geometry rather than unblock a dropped search
# dimension.
PROFILE_ENCODED_PARAMS = {
    "GR4J_X1": 0,   # -> SOIL[0] PRODUCT_STORE thickness (no named .rvp column)
}


def _rvp_porosity(lines, default=0.451):
    """POROSITY from the first numeric row of a *ParameterList carrying it."""
    col = None
    for raw in lines:
        t = raw.strip()
        if t.startswith("#"):
            continue
        if t.startswith(":Parameters"):
            toks = [x.strip() for x in t.split(",")]
            col = toks.index("POROSITY") if "POROSITY" in toks else None
            continue
        if t.startswith(":End"):
            col = None
            continue
        if col is not None and "," in t and not t.startswith(":"):
            parts = t.split(",")
            if col < len(parts):
                try:
                    v = float(parts[col].strip())
                except ValueError:
                    continue
                if v > 0:
                    return v
    return default


def update_soil_profile_thickness(lines, layer_index, capacity_mm):
    """Rewrite layer `layer_index` thickness in every :SoilProfiles data row.

    Row layout: NAME, nlayers, class0, thick0, class1, thick1, ...
    Inverse of build_rvp_parameters.py: thickness_m = capacity_mm/1000/POROSITY.
    """
    porosity = _rvp_porosity(lines)
    if porosity <= 0:
        return False
    thickness = float(capacity_mm) / 1000.0 / porosity
    in_block = False
    changed = False
    for i, raw in enumerate(lines):
        t = raw.strip()
        if t.startswith(":SoilProfiles"):
            in_block = True
            continue
        if t.startswith(":EndSoilProfiles"):
            in_block = False
            continue
        if not in_block or not t or t.startswith("#") or t.startswith(":"):
            continue
        parts = raw.split(",")
        col = 3 + 2 * layer_index
        if col >= len(parts):
            continue
        try:
            n_layers = int(parts[1].strip())
        except (ValueError, IndexError):
            continue
        if layer_index >= n_layers:
            continue
        try:
            float(parts[col].strip())
        except ValueError:
            continue
        lead = parts[col][:len(parts[col]) - len(parts[col].lstrip())]
        parts[col] = "%s%.4f" % (lead, thickness)
        lines[i] = ",".join(parts)
        if not lines[i].endswith("\n"):
            lines[i] += "\n"
        changed = True
    return changed


def apply_profile_encoded_params(rvp_path, values):
    """Write every profile-encoded capacity ONCE, after the whole vector is set.

    dt_rav_045.  Must be called AFTER all named parameters have been written for
    an iteration, because thickness = capacity_mm/1000/POROSITY reads POROSITY
    back out of the .rvp and POROSITY is a calibrated parameter in several
    templates.  Doing it here (rather than inside update_rvp_parameter) makes the
    written geometry independent of parameter write order.

    Returns the list of parameter names actually written, for reporting.
    """
    encoded = {k: v for k, v in values.items() if k in PROFILE_ENCODED_PARAMS}
    if not encoded:
        return []
    with open(rvp_path) as f:
        lines = f.readlines()
    written = []
    for pname in sorted(encoded):
        if update_soil_profile_thickness(lines, PROFILE_ENCODED_PARAMS[pname],
                                         encoded[pname]):
            written.append(pname)
    if written:
        with open(rvp_path, "w") as f:
            f.writelines(lines)
    return written


def parameter_in_rvp(rvp_text, param_name):
    """True if `param_name` is a name Raven will actually read from this .rvp."""
    for raw in rvp_text.splitlines():
        s = raw.strip()
        if s.startswith("#"):
            continue
        if s.startswith(":GlobalParameter"):
            toks = s.split()
            if len(toks) >= 2 and toks[1] == param_name:
                return True
        elif s.startswith(":Parameters"):
            if param_name in [t.strip() for t in s.split(",")]:
                return True
    # Case 3 (dt_rav_045): capacity encoded as a :SoilProfiles layer thickness.
    if param_name in PROFILE_ENCODED_PARAMS and ":SoilProfiles" in rvp_text:
        return True
    return False


def filter_present_parameters(params, rvp_path):
    """Split a candidate parameter set into (present, absent) against the .rvp."""
    try:
        text = open(rvp_path).read()
    except OSError:
        return params, []
    present = {k: v for k, v in params.items() if parameter_in_rvp(text, k)}
    absent = [k for k in params if k not in present]
    return present, absent


def objective_on_window(run_dir, basin_name, objective, cal_start, cal_end):
    """Objective computed on the CALIBRATION WINDOW only, via the KI s7 tool.

    Raven's own Diagnostics.csv scores the WHOLE simulation, spin-up and
    held-out years included. Optimising that number makes the held-out score a
    fitted statistic and destroys the cal/val split. This reads the calendar-
    dated pair from parse_raven_output.load_discharge_series (so the
    period-ending convention of dt_rav_034 is applied once, in one place) and
    scores only cal_start..cal_end.
    """
    sim, obs = load_discharge_series(os.path.join(run_dir, "output"), basin_name)
    if obs is None or sim is None:
        return None, "Hydrographs.csv carries no observed column"
    pair = pd.concat([obs.rename("obs"), sim.rename("sim")], axis=1).dropna()
    if cal_start:
        pair = pair[pair.index >= pd.Timestamp(cal_start)]
    if cal_end:
        pair = pair[pair.index <= pd.Timestamp(cal_end)]
    if len(pair) < 2:
        return None, f"only {len(pair)} paired days in {cal_start}..{cal_end}"

    o, s = pair["obs"].values, pair["sim"].values
    denom = float(((o - o.mean()) ** 2).sum())
    if denom <= 0:
        return None, "zero observed variance in the calibration window"
    nse = 1.0 - float(((s - o) ** 2).sum()) / denom
    if objective == "NSE":
        return nse, None
    if objective == "RMSE":
        return -float(np.sqrt(((s - o) ** 2).mean())), None
    if objective == "KGE":
        r = float(np.corrcoef(s, o)[0, 1])
        alpha = float(np.std(s) / np.std(o)) if np.std(o) > 0 else 1.0
        beta = float(np.mean(s) / np.mean(o)) if np.mean(o) > 0 else 1.0
        return 1.0 - float(np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)), None
    return None, f"unsupported objective {objective}"


def dds_perturbation(x, x_min, x_max, sigma=0.2):
    """DDS perturbation: Gaussian with reflection at bounds."""
    x_new = x + sigma * (x_max - x_min) * np.random.standard_normal()
    # Reflect at bounds
    if x_new < x_min:
        x_new = x_min + (x_min - x_new)
        if x_new > x_max:
            x_new = x_min
    if x_new > x_max:
        x_new = x_max - (x_new - x_max)
        if x_new < x_min:
            x_new = x_max
    return float(x_new)


def update_rvp_parameter(rvp_path, param_name, value):
    """Update a parameter value in the .rvp file.

    Handles two layouts:
      1. `:GlobalParameter NAME value`  (name and value on the same line)
      2. Tabular *ParameterList blocks where the parameter NAME lives on a
         `:Parameters, A, B, C,` header line and the numeric VALUE lives in
         the matching column of each class/`[DEFAULT]` data row below it.
    The original implementation only handled case 1 and silently failed on
    the columnar layout used by Soil/LandUse/Vegetation parameter lists —
    so HMETS_RUNOFF_COEFF, POROSITY, etc. could never be calibrated.
    """
    with open(rvp_path) as f:
        lines = f.readlines()

    changed = False

    # --- Case 1: :GlobalParameter NAME value ---
    gp_pat = re.compile(rf"^(\s*:GlobalParameter\s+{re.escape(param_name)}\s+)([\d\.\-eE\+]+)")
    for i, line in enumerate(lines):
        m = gp_pat.match(line)
        if m:
            lines[i] = f"{m.group(1)}{value:.6f}\n"
            changed = True

    # --- Case 2: tabular *ParameterList (column under :Parameters header) ---
    col_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(":Parameters"):
            # tokens after the ":Parameters" keyword, comma-separated
            toks = [t.strip() for t in stripped.split(",")]
            # toks[0] == ":Parameters"; data columns start at index 1
            col_idx = None
            for j in range(1, len(toks)):
                if toks[j] == param_name:
                    col_idx = j
                    break
            continue
        if stripped.startswith(":End"):
            col_idx = None
            continue
        if col_idx is not None and "," in stripped and not stripped.startswith(":"):
            # data row: "CLASSNAME, v1, v2, ..."  (col j aligns with header tok j)
            parts = line.split(",")
            if col_idx < len(parts):
                # preserve trailing content; only replace the numeric token
                try:
                    float(parts[col_idx].strip())
                except ValueError:
                    continue
                lead = parts[col_idx][:len(parts[col_idx]) - len(parts[col_idx].lstrip())]
                parts[col_idx] = f"{lead}{value:.6f}"
                lines[i] = ",".join(parts)
                if not lines[i].endswith("\n"):
                    lines[i] += "\n"
                changed = True

    # NOTE (dt_rav_045): profile-encoded capacities are NOT written here.  Their
    # thickness depends on POROSITY, which is itself a calibrated parameter in
    # several templates, so writing them inside this per-parameter call would
    # make the result depend on the order the caller happens to iterate the
    # parameter dict.  apply_profile_encoded_params() does it once, afterwards.
    if changed:
        with open(rvp_path, "w") as f:
            f.writelines(lines)


def run_raven_once(run_dir, basin_name, raven_exe, timeout=600):
    """Run Raven once and return the objective function value."""
    output_dir = os.path.join(run_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Clean old output
    for f in os.listdir(output_dir) if os.path.isdir(output_dir) else []:
        os.remove(os.path.join(output_dir, f))

    cmd = [
        os.path.abspath(raven_exe),
        basin_name,
        "-o", os.path.abspath(output_dir) + "/",
    ]

    try:
        result = subprocess.run(
            cmd, cwd=os.path.abspath(run_dir),
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as e:
        return None, str(e)

    if result.returncode != 0:
        return None, f"returncode={result.returncode}: {result.stderr[-200:]}"

    # Parse Diagnostics.csv
    diag_file = None
    for f in os.listdir(output_dir) if os.path.isdir(output_dir) else []:
        if "diagnostic" in f.lower():
            diag_file = os.path.join(output_dir, f)
            break

    if not diag_file:
        return None, "No Diagnostics.csv found"

    # Canonical parser (s7): Diagnostics.csv is a header row plus one data row
    # per observation series, NOT name,value pairs. Parsing it row-wise yielded
    # {} and let DDS "optimise" the -999 fallback forever (dt_rav_037).
    metrics = parse_diagnostics(diag_file)
    if not metrics:
        return None, f"no diagnostics parsed from {os.path.basename(diag_file)}"

    return metrics, None


def process(args):
    """Run DDS calibration."""
    template = args.template
    if template not in CALIBRATION_PARAMS:
        return {"status": "error", "message": f"No calibration parameters defined for template: {template}"}

    rvp_path = os.path.join(args.run_dir, f"{args.basin_name}.rvp")

    # Template set + shared set, then keep only what the .rvp really declares.
    candidate = dict(CALIBRATION_PARAMS[template])
    for k, v in SHARED_PARAMS.items():
        candidate.setdefault(k, v)
    params, absent = filter_present_parameters(candidate, rvp_path)
    if not params:
        return {"status": "error",
                "message": f"none of the {len(candidate)} candidate parameters for "
                           f"{template} appear in {rvp_path}"}
    param_names = list(params.keys())
    n_params = len(param_names)

    if args.seed is not None:
        np.random.seed(int(args.seed))

    # Initialize with defaults
    x_current = {p: info[2] for p, info in params.items()}
    x_best = x_current.copy()
    best_obj = -999.0

    # DDS parameters
    n_iter = args.n_iterations
    r = 0.2  # perturbation radius

    history = []

    # Backup original .rvp
    rvp_backup = rvp_path + ".backup"
    shutil.copy2(rvp_path, rvp_backup)

    print(f"Starting DDS calibration: {n_iter} iterations, {n_params} parameters", flush=True)
    print(f"Template: {template}", flush=True)
    print(f"Objective: maximize {args.objective}", flush=True)

    t0 = time.time()

    for i in range(n_iter):
        # DDS: probability of perturbing each parameter decreases with iteration
        p_perturb = 1.0 - np.log(i + 1) / np.log(n_iter + 1)

        # Select parameters to perturb
        x_candidate = x_current.copy()
        perturbed_any = False
        for pname in param_names:
            if np.random.random() < p_perturb:
                pmin, pmax, pdef, _ = params[pname]
                x_candidate[pname] = dds_perturbation(x_current[pname], pmin, pmax, sigma=r)
                perturbed_any = True

        # If nothing perturbed, perturb one random parameter
        if not perturbed_any:
            pname = param_names[np.random.randint(n_params)]
            pmin, pmax, pdef, _ = params[pname]
            x_candidate[pname] = dds_perturbation(x_current[pname], pmin, pmax, sigma=r)

        # Update .rvp with candidate parameters
        shutil.copy2(rvp_backup, rvp_path)
        for pname, pval in x_candidate.items():
            update_rvp_parameter(rvp_path, pname, pval)
        # dt_rav_045: profile-encoded capacities last, so they see the final
        # POROSITY regardless of the order the dict above was iterated.
        apply_profile_encoded_params(rvp_path, x_candidate)

        # Run model
        metrics, error = run_raven_once(args.run_dir, args.basin_name, args.raven_exe)

        if error:
            history.append({"iter": i + 1, "status": "error", "error": error})
            continue

        # Get objective value.
        # With a calibration window the objective is recomputed on THAT window
        # only; Raven's own Diagnostics.csv covers the whole simulation
        # (spin-up + held-out years) and must not drive the search (dt_rav_038).
        if args.cal_start or args.cal_end:
            obj_compare, obj_err = objective_on_window(
                args.run_dir, args.basin_name, args.objective,
                args.cal_start, args.cal_end)
            if obj_compare is None:
                history.append({"iter": i + 1, "status": "error", "error": obj_err})
                continue
            obj_value = obj_compare if args.objective != "RMSE" else -obj_compare
        else:
            obj_map = {
                "NSE": "NASH_SUTCLIFFE",
                "KGE": "KLING_GUPTA",
                "RMSE": "RMSE",
            }
            obj_key = obj_map.get(args.objective, args.objective)
            if obj_key not in metrics:
                # Fail closed: a metric Raven did not emit is a MISSING
                # measurement, not a bad score. Substituting -999 here let DDS
                # "converge" on a constant sentinel and still report success.
                history.append({
                    "iter": i + 1, "status": "error",
                    "error": f"{obj_key} absent from Diagnostics.csv "
                             f"(present: {sorted(k for k in metrics if not k.startswith('DIAG_'))}); "
                             f"add it to :EvaluationMetrics in the .rvi",
                })
                continue
            obj_value = metrics[obj_key]
            obj_compare = -obj_value if args.objective == "RMSE" else obj_value

        # Accept if better
        if obj_compare > best_obj:
            best_obj = obj_compare
            x_best = x_candidate.copy()
            x_current = x_candidate.copy()

        history.append({
            "iter": i + 1,
            "objective": obj_value,
            "best_so_far": best_obj if args.objective != "RMSE" else -best_obj,
            "params": {k: round(v, 4) for k, v in x_candidate.items()},
        })

        if (i + 1) % 10 == 0:
            best_display = best_obj if args.objective != "RMSE" else -best_obj
            print(f"  Iter {i+1}/{n_iter}: best {args.objective} = {best_display:.4f}", flush=True)

    elapsed = time.time() - t0

    # Fail closed: if not one iteration produced a real objective value there is
    # nothing to promote — reporting "success" with the -999 initialiser is how a
    # broken diagnostics read used to pass as a finished calibration.
    n_evaluated = sum(1 for h in history if "objective" in h)
    if n_evaluated == 0:
        shutil.copy2(rvp_backup, rvp_path)
        return {
            "status": "error",
            "message": f"no objective value could be computed in {n_iter} iterations "
                       f"— .rvp restored, parameters unchanged",
            "template": template,
            "objective": args.objective,
            "n_iterations": n_iter,
            "elapsed_seconds": round(elapsed, 1),
            "calibrated_parameters": param_names,
            "skipped_parameters_absent_from_rvp": absent,
            "iteration_errors": history[-5:],
        }

    # Apply best parameters
    shutil.copy2(rvp_backup, rvp_path)
    for pname, pval in x_best.items():
        update_rvp_parameter(rvp_path, pname, pval)
    profile_encoded_written = apply_profile_encoded_params(rvp_path, x_best)

    # Run final model with best params
    final_metrics, _ = run_raven_once(args.run_dir, args.basin_name, args.raven_exe)

    best_display = best_obj if args.objective != "RMSE" else -best_obj

    results = {
        "status": "success",
        "template": template,
        "objective": args.objective,
        "n_iterations": n_iter,
        "n_evaluated_iterations": n_evaluated,
        "elapsed_seconds": round(elapsed, 1),
        "best_parameters": {k: round(v, 6) for k, v in x_best.items()},
        "parameters_at_bounds": [
            p for p in param_names
            if (params[p][1] - params[p][0]) > 0
            and min(abs(x_best[p] - params[p][0]), abs(params[p][1] - x_best[p]))
                <= 0.01 * (params[p][1] - params[p][0])
        ],
        "best_objective": round(best_display, 4),
        "calibrated_parameters": param_names,
        "skipped_parameters_absent_from_rvp": absent,
        # dt_rav_045: names written as a :SoilProfiles layer thickness rather
        # than a named .rvp column, so the audit trail shows they were not
        # silently frozen.
        "profile_encoded_parameters": profile_encoded_written,
        "calibration_window": [args.cal_start, args.cal_end],
        "objective_source": ("calibration window via parse_raven_output"
                             if (args.cal_start or args.cal_end)
                             else "Raven Diagnostics.csv (whole simulation)"),
        "seed": args.seed,
        "final_metrics": final_metrics or {},
        "convergence_history": history[-20:],  # last 20 for brevity
    }

    # Save full history
    history_path = os.path.join(args.run_dir, "calibration_history.json")
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)
    results["history_file"] = history_path

    return results


def main():
    parser = argparse.ArgumentParser(description="DDS calibration for Raven")
    parser.add_argument("--run_dir", required=True, help="Raven run directory")
    parser.add_argument("--basin_name", required=True, help="Basin name")
    parser.add_argument("--template", required=True, help="Model template name")
    parser.add_argument("--n_iterations", type=int, default=100, help="Number of DDS iterations")
    parser.add_argument("--objective", default="NSE", help="Objective: NSE, KGE, RMSE")
    parser.add_argument("--raven_exe", default=RAVEN_EXE_DEFAULT, help="Raven executable path")
    parser.add_argument("--seed", type=int, default=None,
                        help="Seed for the DDS search (reproducible calibration)")
    parser.add_argument("--cal_start", default=None,
                        help="Calibration window start (YYYY-MM-DD). Restricts the "
                             "objective to this window so the held-out score stays honest")
    parser.add_argument("--cal_end", default=None,
                        help="Calibration window end (YYYY-MM-DD)")

    args = parser.parse_args()

    try:
        results = process(args)
    except Exception as e:
        import traceback
        print(json.dumps({"status": "error", "message": str(e), "traceback": traceback.format_exc()}))
        sys.exit(2)

    print(json.dumps(results, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
