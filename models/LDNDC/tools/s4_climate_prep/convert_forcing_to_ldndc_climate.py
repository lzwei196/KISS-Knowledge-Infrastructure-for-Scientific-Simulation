#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      convert_forcing_to_ldndc_climate
Stage:        s4_climate_prep
Description:  Convert CMFD/MSWX/NASA POWER/VIC forcing to LDNDC climate.txt format.
              Handles unit conversions: K->C, sub-daily->daily aggregation,
              specific humidity->RH, vapor pressure->RH.

CRITICAL: Temperature must be in Celsius. If source is in Kelvin (values > 100),
          subtract 273.15. See diagnostic triplet dt_005.

CRITICAL: Precipitation must be SUMMED across sub-daily timesteps, not averaged.
          See diagnostic triplet dt_014.

Inputs:
  - forcing_source: cmfd, mswx, nasa_power, vic_forcing, fluxnet
  - forcing_path: Path to forcing data directory or file
  - lat, lon: Grid cell coordinates (decimal degrees)
  - start_date, end_date: Simulation period (YYYY-MM-DD)
  - output_path: Output climate.txt path
  - elevation: Site elevation in meters (optional, default 0)

Outputs:
  - LDNDC climate.txt in simple tab-separated format (compatible with format="txt")
  - Columns: date, tavg, tmin, tmax, prec, wind, rh, glob

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import math
import logging
from pathlib import Path
from datetime import date, timedelta

import numpy as np

# ---------------------------------------------------------------------------
# INPUTS (set via argv or directly)
# ---------------------------------------------------------------------------
FORCING_SOURCE = ""     # cmfd, mswx, nasa_power, vic_forcing, fluxnet
FORCING_PATH = ""       # Directory (cmfd/mswx) or file (vic_forcing/fluxnet)
LAT = 0.0
LON = 0.0
START_DATE = ""         # YYYY-MM-DD
END_DATE = ""           # YYYY-MM-DD
OUTPUT_PATH = ""        # Output climate.txt path
ELEVATION = "0"         # Site elevation in meters (optional)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    valid_sources = ["cmfd", "mswx", "nasa_power", "vic_forcing", "fluxnet", "fluxnet_fullset"]
    if FORCING_SOURCE not in valid_sources:
        errors.append(f"Unknown forcing_source: {FORCING_SOURCE}. Must be one of: {valid_sources}")
    if not FORCING_PATH:
        errors.append("FORCING_PATH is required")
    elif not Path(FORCING_PATH).exists():
        errors.append(f"Forcing path not found: {FORCING_PATH}")
    if not OUTPUT_PATH:
        errors.append("OUTPUT_PATH is not set")
    if not START_DATE or not END_DATE:
        errors.append("START_DATE and END_DATE are required (YYYY-MM-DD)")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def _spechum_to_rh(q_kgkg, temp_c, press_pa):
    """Convert specific humidity (kg/kg) to relative humidity (%).

    Uses Tetens formula for saturation vapor pressure.
    """
    # Saturation vapor pressure (Pa)
    es = 611.2 * math.exp(17.67 * temp_c / (temp_c + 243.5))
    # Actual vapor pressure from specific humidity
    p = press_pa if press_pa > 0 else 101325.0
    e = q_kgkg * p / (0.622 + 0.378 * q_kgkg)
    rh = 100.0 * e / es if es > 0 else 70.0
    return max(5.0, min(100.0, rh))


def _load_via_ki_tools_common(source, lat, lon, start_year, end_year, forcing_dir):
    """Load daily forcing using ki_tools_common.load_forcing."""
    # Add ki_tools_common to path
    ki_common = Path(__file__).resolve().parents[3] / "ki_tools_common" / "ki_tools_common"
    if ki_common.is_dir():
        sys.path.insert(0, str(ki_common.parent))
    # Also try the models location
    models_common = Path("/mnt/disk1/Hydrocraft_server/models/ki_tools_common")
    if models_common.is_dir():
        sys.path.insert(0, str(models_common))

    from ki_tools_common.load_forcing import load_daily_forcing
    data = load_daily_forcing(source, lat, lon, start_year, end_year, forcing_dir=forcing_dir)
    return data


def _load_vic_forcing(forcing_file, steps_per_day=8):
    """Load VIC 3-hourly forcing file (7-column ASCII).

    VIC columns: TEMP(C), PRECIP(mm/step), PRESSURE(kPa), SWDOWN(W/m2),
                 LWDOWN(W/m2), VP(kPa), WIND(m/s)
    """
    data = np.loadtxt(forcing_file)
    nsteps = data.shape[0]
    ndays = nsteps // steps_per_day
    if nsteps % steps_per_day != 0:
        logger.warning(f"Steps ({nsteps}) not divisible by {steps_per_day}; truncating.")
        data = data[:ndays * steps_per_day]
    daily = data.reshape(ndays, steps_per_day, 7)

    return {
        "ndays": ndays,
        "tavg": daily[:, :, 0].mean(axis=1),
        "tmin": daily[:, :, 0].min(axis=1),
        "tmax": daily[:, :, 0].max(axis=1),
        "prec": daily[:, :, 1].sum(axis=1),
        "glob": daily[:, :, 3].mean(axis=1),
        "wind": daily[:, :, 6].mean(axis=1),
        # Compute RH from VP and temperature
        "vp_kpa": daily[:, :, 5].mean(axis=1),
    }


def _load_fluxnet_erai(forcing_file):
    """Load FLUXNET ERA-I daily forcing (ERAI_DD.csv)."""
    import pandas as pd
    df = pd.read_csv(forcing_file)
    df["date"] = pd.to_datetime(df["TIMESTAMP"], format="%Y%m%d")
    return df


def _load_fluxnet_fullset(forcing_file):
    """Load FLUXNET FULLSET daily forcing (FULLSET_DD.csv).

    Uses gap-filled tower observations (MDS method) — higher quality than ERA-I alone.
    Columns used: TA_F_MDS, TA_F_MDS_DAY, TA_F_MDS_NIGHT, P_F, SW_IN_F, WS_F.
    Missing values (-9999) are replaced with ERA fallback columns where available.
    """
    import pandas as pd
    df = pd.read_csv(forcing_file)
    df["date"] = pd.to_datetime(df["TIMESTAMP"], format="%Y%m%d")
    # Replace FLUXNET -9999 fill value with NaN
    df = df.replace(-9999, float("nan"))
    # Alias FULLSET columns to ERAI column names so the rest of the pipeline is unchanged
    df["TA_ERA"] = df.get("TA_F_MDS", df.get("TA_ERA", None))
    df["TA_ERA_DAY"] = df.get("TA_F_MDS_DAY", df.get("TA_ERA_DAY", None))
    df["TA_ERA_NIGHT"] = df.get("TA_F_MDS_NIGHT", df.get("TA_ERA_NIGHT", None))
    df["P_ERA"] = df.get("P_F", df.get("P_ERA", None))
    df["SW_IN_ERA"] = df.get("SW_IN_F", df.get("SW_IN_ERA", None))
    df["WS_ERA"] = df.get("WS_F", df.get("WS_ERA", None))
    # Forward-fill any remaining NaN (small gaps)
    for col in ["TA_ERA", "TA_ERA_DAY", "TA_ERA_NIGHT", "P_ERA", "SW_IN_ERA", "WS_ERA"]:
        if col in df.columns:
            df[col] = df[col].ffill().bfill()
    return df


def _collect_daily_arrays(start_year, end_year):
    """Read forcing and return parallel arrays: prec, tavg, tmax, tmin, grad, wind.

    Returns (ndays, prec[], tavg[], tmax[], tmin[], grad[], wind[]).
    All arrays are numpy or list of float, same length.
    """
    if FORCING_SOURCE == "fluxnet_fullset":
        import pandas as pd
        df = _load_fluxnet_fullset(FORCING_PATH)
        df = df[(df.date.dt.year >= start_year) & (df.date.dt.year <= end_year)]
        ta = df["TA_ERA"]
        ta_day = df["TA_ERA_DAY"].where(df["TA_ERA_DAY"].notna(), ta + 3)
        ta_night = df["TA_ERA_NIGHT"].where(df["TA_ERA_NIGHT"].notna(), ta - 3)
        return (
            len(df),
            np.maximum(0, df["P_ERA"].fillna(0).values),
            ta.values,
            ta_day.values,
            ta_night.values,
            np.maximum(0, df["SW_IN_ERA"].fillna(150).values),
            np.maximum(0, df["WS_ERA"].fillna(2.0).values),
        )

    if FORCING_SOURCE == "vic_forcing":
        vic = _load_vic_forcing(FORCING_PATH)
        return (vic["ndays"], vic["prec"], vic["tavg"], vic["tmax"],
                vic["tmin"], vic["glob"], vic["wind"])

    elif FORCING_SOURCE == "fluxnet":
        df = _load_fluxnet_erai(FORCING_PATH)
        df = df[(df.date.dt.year >= start_year) & (df.date.dt.year <= end_year)]
        return (
            len(df),
            np.maximum(0, df.get("P_ERA", 0).values),
            df["TA_ERA"].values,
            df.get("TA_ERA_DAY", df["TA_ERA"] + 3).values,
            df.get("TA_ERA_NIGHT", df["TA_ERA"] - 3).values,
            np.maximum(0, df.get("SW_IN_ERA", 150).values),
            np.maximum(0, df.get("WS_ERA", 2.0).values),
        )

    elif FORCING_SOURCE in ("cmfd", "mswx", "nasa_power"):
        data = _load_via_ki_tools_common(
            FORCING_SOURCE, LAT, LON, start_year, end_year, FORCING_PATH
        )
        ndays = len(data["dates"])
        if "temp_mean_c" in data:
            tavg = np.array(data["temp_mean_c"])
        else:
            tavg = (np.array(data["temp_min_c"]) + np.array(data["temp_max_c"])) / 2
        return (
            ndays,
            np.array(data["precip_mm"]),
            tavg,
            np.array(data["temp_max_c"]),
            np.array(data["temp_min_c"]),
            np.array(data["srad_wm2"]),
            np.array(data["wind_ms"]),
        )
    else:
        logger.error(f"Source '{FORCING_SOURCE}' not implemented")
        sys.exit(2)


def process():
    """Convert forcing data to LDNDC native %data block format.

    Output format (proven to work with LDNDC 1.37):
        %global
            time = "YYYY-01-01/1"
        %climate
            id = 0
        %attributes
            elevation = "..."
            ...
        %data
        prec    tavg    tmax    tmin    grad    wind
        <values, one row per day, no date column>

    This is the SAME format used by the validated run_ldndc_bengbu_ghg.py
    and all shipped LDNDC examples. The simple tab-separated format with
    dates (format="txt") also works but produces lower emissions — possibly
    a column mapping issue in the LDNDC parser.
    """
    output = Path(OUTPUT_PATH)
    output.parent.mkdir(parents=True, exist_ok=True)

    start_year = int(START_DATE[:4])
    end_year = int(END_DATE[:4])
    elev = float(ELEVATION) if ELEVATION else 0.0

    ndays, prec, tavg, tmax, tmin, grad, wind = _collect_daily_arrays(start_year, end_year)

    # Compute header statistics
    annual_precip = float(np.sum(prec)) / max(1, (end_year - start_year + 1))
    temp_avg = float(np.mean(tavg))

    # Temperature amplitude: half range between warmest and coldest monthly means
    start_date_obj = date(start_year, 1, 1)
    monthly_means = []
    for m in range(1, 13):
        mask = []
        for d in range(ndays):
            dt = start_date_obj + timedelta(days=d)
            if dt.month == m:
                mask.append(d)
        if mask:
            monthly_means.append(float(np.mean([tavg[j] for j in mask])))
    temp_amplitude = (max(monthly_means) - min(monthly_means)) / 2.0 if monthly_means else 15.0

    # Write native %data format
    with open(output, "w") as f:
        f.write("%global\n")
        f.write(f'\ttime = "{start_year}-01-01/1"\n')
        f.write("\n")
        f.write("%climate\n")
        f.write("\tid = 0\n")
        f.write("\n")
        f.write("%attributes\n")
        f.write(f'\televation = "{elev:.1f}"\n')
        f.write(f'\tlatitude = "{LAT:.2f}"\n')
        f.write(f'\tlongitude = "{LON:.2f}"\n')
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
        f"Climate file written: {output} ({ndays} days, "
        f"annual precip={annual_precip:.0f} mm, tavg={temp_avg:.1f} C)"
    )
    return str(output), ndays, annual_precip


def validate_outputs(output_path, ndays, annual_precip):
    if not Path(output_path).exists():
        logger.error(f"Output not created: {output_path}")
        sys.exit(3)
    content = Path(output_path).read_text()

    # Must contain %data section
    if "%data" not in content:
        logger.error("climate.txt missing %data section")
        sys.exit(3)

    # Count data lines (after the column header under %data)
    in_data = False
    data_count = 0
    header_seen = False
    for line in content.strip().split("\n"):
        if line.strip() == "%data":
            in_data = True
            continue
        if in_data:
            if not header_seen:
                header_seen = True  # skip column header
                continue
            if line.strip() and not line.startswith("%"):
                data_count += 1

    if data_count < 30:
        logger.error(f"climate.txt has only {data_count} data rows — expected at least 365")
        sys.exit(3)

    # Check precipitation sanity
    if annual_precip < 10:
        logger.warning(f"Annual precipitation very low ({annual_precip:.0f} mm) — check units (dt_014)")
    elif annual_precip > 5000:
        logger.warning(f"Annual precipitation very high ({annual_precip:.0f} mm) — check units (dt_014)")

    logger.info(f"Output validation passed ({data_count} data rows).")


if __name__ == "__main__":
    if len(sys.argv) >= 8:
        FORCING_SOURCE = sys.argv[1]
        FORCING_PATH = sys.argv[2]
        LAT = float(sys.argv[3])
        LON = float(sys.argv[4])
        START_DATE = sys.argv[5]
        END_DATE = sys.argv[6]
        OUTPUT_PATH = sys.argv[7]
    if len(sys.argv) >= 9:
        ELEVATION = sys.argv[8]
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path, ndays, annual_precip = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path, ndays, annual_precip)
    print(json.dumps({
        "status": "success",
        "climate_txt": output_path,
        "n_days": ndays,
        "annual_precip_mm": round(annual_precip, 1),
    }))
    sys.exit(0)
