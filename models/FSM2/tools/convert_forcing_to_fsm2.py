#!/usr/bin/env python3
"""
Convert generic meteorological forcing data to FSM2 input format.

Supports: ERA5, MSWX, generic CSV with standard column names.
Target format: FSM2 DRIV1D=1 (year month day hour SW LW Sf Rf Ta RH Ua Ps)

Unit conversions applied:
  - Temperature: °C → K (add 273.15)
  - Pressure: hPa → Pa (multiply 100), kPa → Pa (multiply 1000)
  - Precipitation: mm/h → kg/m²/s (divide 3600), mm/day → kg/m²/s (divide 86400)
  - Relative humidity: fraction 0-1 → percent 0-100 (multiply 100)
  - Wind speed: enforced minimum 0.1 m/s

DERIVATIONS (added 2026-08-21 — no gridded reanalysis ships the two fields FSM2
DRIV1D=1 actually wants, so without these the documented "reanalysis → FSM2"
pipeline cannot be completed with KI tools alone):

  - Relative humidity from SPECIFIC humidity (`--shum-col`).  CMFD / MSWX /
    ERA5 / NASA POWER all publish specific humidity, never RH.  FSM2 immediately
    inverts RH back to Qa in FSM2_DRIVE.F90 with
        es = e0*exp(17.5043*Tc/(241.3 + Tc));  Qa = (RH/100)*eps*es/Ps
    so this tool uses THE SAME saturation formula and the same constants.  The
    q → RH → q round trip is therefore exact, not an approximation.

  - Snowfall/rainfall from TOTAL precipitation (`--precip-col`).  FSM2 does NOT
    partition precipitation for DRIV1D=1: FSM2_DRIVE.F90 reads Sf and Rf as two
    independent columns and only the ENSMBL==1 branch (an ensemble-perturbation
    option that is OFF in compil.sh) ever computes a phase split.  Feeding total
    precipitation into Sf gives a permanent snowpack; feeding it into Rf gives no
    snow at all.  The split applied here is FSM2's own ramp, copied from that
    ENSMBL branch:
        fs = clip(1 - 0.5*(Ta - 273.15), 0, 1)   ->  all snow at <=0 degC,
                                                     all rain at >=+2 degC
    Ménard et al. (2019, ESSD 11, 865-880, Fig. 4) show the same near-linear
    0-2 degC ramp fitted to the ESM-SnowMIP reference-site observations.

  - OPTIONAL ESM-SnowMIP site protocol (`--precip-scale`, `--phase-logistic`).
    Both are OFF by default and NEITHER touches partition_precip_fsm2(), whose
    two-argument signature and numerics are unchanged.  `--precip-scale` applies
    the site precipitation mean-bias multiplier that Ménard et al. (2019,
    Sect. 3) applied at ALL TEN reference sites, BEFORE the phase split;
    `--phase-logistic T0 T1` routes the split through the separate
    partition_precip_esm_snowmip() with that site's published Table 4 factors.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_input(df: pd.DataFrame, required_cols: list[str]) -> list[str]:
    """Check that all required columns exist. Return list of missing ones."""
    missing = [c for c in required_cols if c not in df.columns]
    return missing


def validate_output(df: pd.DataFrame) -> list[str]:
    """Run physical-range checks on the output dataframe."""
    issues = []
    if (df["Ta"] < 180).any() or (df["Ta"] > 340).any():
        issues.append(f"Ta out of range [180, 340] K: min={df['Ta'].min():.1f}, max={df['Ta'].max():.1f}")
    if (df["Ps"] < 30000).any() or (df["Ps"] > 110000).any():
        issues.append(f"Ps out of range [30000, 110000] Pa: min={df['Ps'].min():.0f}, max={df['Ps'].max():.0f}")
    if (df["RH"] < 0).any() or (df["RH"] > 100.5).any():
        issues.append(f"RH out of range [0, 100] %: min={df['RH'].min():.1f}, max={df['RH'].max():.1f}")
    if (df["SW"] < 0).any():
        issues.append(f"SW has negative values: min={df['SW'].min():.1f}")
    if (df["LW"] < 50).any() or (df["LW"] > 600).any():
        issues.append(f"LW out of range [50, 600] W/m²: min={df['LW'].min():.1f}, max={df['LW'].max():.1f}")
    if (df["Sf"] < 0).any() or (df["Rf"] < 0).any():
        issues.append("Negative precipitation detected")
    if (df["Sf"].max() > 0.01) or (df["Rf"].max() > 0.05):
        issues.append(f"Precipitation suspiciously large (Sf max={df['Sf'].max():.4e}, Rf max={df['Rf'].max():.4e} kg/m²/s). Check units.")
    if (df["Ua"] < 0).any():
        issues.append("Negative wind speed detected")
    return issues


# ---------------------------------------------------------------------------
# Unit conversion functions
# ---------------------------------------------------------------------------

def convert_temperature(series: pd.Series, unit: str) -> pd.Series:
    """Convert temperature to Kelvin."""
    if unit == "C":
        return series + 273.15
    elif unit == "K":
        return series.copy()
    else:
        raise ValueError(f"Unknown temperature unit: {unit}")


def convert_pressure(series: pd.Series, unit: str) -> pd.Series:
    """Convert pressure to Pa."""
    if unit == "hPa":
        return series * 100.0
    elif unit == "kPa":
        return series * 1000.0
    elif unit == "Pa":
        return series.copy()
    else:
        raise ValueError(f"Unknown pressure unit: {unit}")


def convert_precip(series: pd.Series, unit: str) -> pd.Series:
    """Convert precipitation to kg/m²/s."""
    if unit == "mm/h":
        return series / 3600.0
    elif unit == "mm/day":
        return series / 86400.0
    elif unit == "kg/m2/s":
        return series.copy()
    elif unit == "mm/s":
        return series.copy()  # 1 mm/s water = 1 kg/m²/s
    else:
        raise ValueError(f"Unknown precipitation unit: {unit}")


def convert_humidity(series: pd.Series, unit: str) -> pd.Series:
    """Convert relative humidity to percent 0-100."""
    if unit == "fraction":
        return series * 100.0
    elif unit == "percent":
        return series.copy()
    else:
        raise ValueError(f"Unknown humidity unit: {unit}")


# ---------------------------------------------------------------------------
# Derivations FSM2 needs but reanalyses never provide directly
# ---------------------------------------------------------------------------

# CONSTANTS.f90 / FSM2_MODULES.F90 — reproduced so the q -> RH -> q round trip
# through FSM2_DRIVE.F90 is exact.
_EPS = 0.622    # ratio of molecular weights of water and dry air
_E0 = 611.213   # saturation vapour pressure at Tm (Pa)
_TM = 273.15    # melting point (K)


def satvp_fsm2(Ta_K: pd.Series | np.ndarray) -> np.ndarray:
    """Saturation vapour pressure (Pa) using FSM2's own formula (FSM2_DRIVE.F90)."""
    Tc = np.asarray(Ta_K, dtype=float) - _TM
    return _E0 * np.exp(17.5043 * Tc / (241.3 + Tc))


def shum_to_rh(qa_kgkg, Ta_K, Ps_Pa) -> np.ndarray:
    """Specific humidity (kg/kg) -> relative humidity (%), inverse of FSM2_DRIVE.

    FSM2_DRIVE.F90 computes Qa = (RH/100)*eps*es/Ps, so RH = 100*Qa*Ps/(eps*es).
    Result is clipped to [0, 100]; FSM2 has no super-saturation branch.
    """
    qa = np.asarray(qa_kgkg, dtype=float)
    ps = np.asarray(Ps_Pa, dtype=float)
    es = satvp_fsm2(Ta_K)
    rh = 100.0 * qa * ps / (_EPS * es)
    return np.clip(rh, 0.0, 100.0)


# Menard et al. 2019 (ESSD 11, 865-880) Table 4: logistic precipitation-phase
# factors fitted to GSWP3 at the ten ESM-SnowMIP reference sites, (T0, T1) degC.
ESM_SNOWMIP_PHASE = {
    "CDP": (3.08, 1.13), "OAS": (-1.73, 1.63), "OBS": (-1.14, 1.81),
    "OJP": (-1.32, 1.76), "RME": (-2.00, 1.48), "SAP": (3.72, 1.48),
    "SNB": (-3.01, 2.05), "SWA": (-3.01, 2.05), "SOD": (2.52, 1.16),
    "WFJ": (0.39, 1.47),
}


def partition_precip_fsm2(pr_kgm2s, Ta_K) -> tuple[np.ndarray, np.ndarray]:
    """Split total precipitation into (Sf, Rf) with FSM2's own temperature ramp.

    Copied from the ENSMBL branch of FSM2_DRIVE.F90:
        fs = 1 - 0.5*(Ta - Tm); fs = min(1, max(fs, 0))
        Sf = fs*Pr;  Rf = (1 - fs)*Pr
    i.e. all snow at or below 0 degC, all rain at or above +2 degC.
    """
    pr = np.asarray(pr_kgm2s, dtype=float)
    Tc = np.asarray(Ta_K, dtype=float) - _TM
    fs = np.clip(1.0 - 0.5 * Tc, 0.0, 1.0)
    return fs * pr, (1.0 - fs) * pr


def partition_precip_esm_snowmip(pr_kgm2s, Ta_K, T0, T1) -> tuple[np.ndarray, np.ndarray]:
    """Split total precipitation into (Sf, Rf) with the ESM-SnowMIP logistic.

    A SEPARATE entry point.  partition_precip_fsm2() above is deliberately left
    untouched -- same two-argument signature, same numerics -- so every existing
    caller and every previously written met file is bit-identical.

    Menard et al. 2019 (ESSD 11, 865-880, Sect. 3) built the ESM-SnowMIP
    reference forcing -- the forcing FSM2 itself is benchmarked against -- with
    a site-fitted logistic rather than FSM2's generic ramp:
        fs = 1 / (1 + exp((Tc - T0)/T1)),   Tc = Ta - 273.15
    T0 and T1 are in degC and are BOTH REQUIRED: there is no defensible generic
    default, and the published per-site pairs are in ESM_SNOWMIP_PHASE above
    (SOD/Sodankyla = 2.52 / 1.16).  Mass is conserved exactly: Sf + Rf == Pr.
    """
    pr = np.asarray(pr_kgm2s, dtype=float)
    Tc = np.asarray(Ta_K, dtype=float) - _TM
    t1 = float(T1)
    if not t1 > 0:
        raise ValueError("ESM-SnowMIP phase T1 must be > 0 degC, got %r" % (T1,))
    # clip the EXPONENT, not the result: np.exp overflows to inf near |x| ~ 710
    fs = 1.0 / (1.0 + np.exp(np.clip((Tc - float(T0)) / t1, -500.0, 500.0)))
    return fs * pr, (1.0 - fs) * pr


# ---------------------------------------------------------------------------
# Auto-detect units from data ranges
# ---------------------------------------------------------------------------

def auto_detect_units(df: pd.DataFrame, col_map: dict) -> dict:
    """Heuristically detect units from data ranges."""
    units = {}

    # Temperature
    ta = df[col_map["Ta"]]
    if ta.median() < 100:
        units["Ta"] = "C"
        print("  Auto-detected Ta unit: °C (median < 100)")
    else:
        units["Ta"] = "K"
        print("  Auto-detected Ta unit: K (median >= 100)")

    # Pressure
    ps = df[col_map["Ps"]]
    if ps.median() < 200:
        units["Ps"] = "kPa"
        print("  Auto-detected Ps unit: kPa (median < 200)")
    elif ps.median() < 2000:
        units["Ps"] = "hPa"
        print("  Auto-detected Ps unit: hPa (median < 2000)")
    else:
        units["Ps"] = "Pa"
        print("  Auto-detected Ps unit: Pa (median >= 2000)")

    # Relative humidity (absent when RH is being derived from specific humidity)
    if col_map.get("RH") in df.columns:
        rh = df[col_map["RH"]]
        if rh.max() <= 1.1:
            units["RH"] = "fraction"
            print("  Auto-detected RH unit: fraction (max <= 1.1)")
        else:
            units["RH"] = "percent"
            print("  Auto-detected RH unit: percent (max > 1.1)")

    # Precipitation — check if already in kg/m²/s (very small) or mm/h.
    # "Pr" is the single total-precipitation column used when Sf/Rf are derived.
    for var in ["Sf", "Rf", "Pr"]:
        if col_map.get(var) not in df.columns:
            continue
        p = df[col_map[var]]
        pmax = p.max()
        if pmax < 0.1:
            units[var] = "kg/m2/s"
            print(f"  Auto-detected {var} unit: kg/m²/s (max < 0.1)")
        elif pmax < 50:
            units[var] = "mm/h"
            print(f"  Auto-detected {var} unit: mm/h (max < 50)")
        else:
            units[var] = "mm/day"
            print(f"  Auto-detected {var} unit: mm/day (max >= 50)")

    return units


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert_forcing(
    input_file: str,
    output_file: str,
    col_map: dict | None = None,
    units: dict | None = None,
    auto_detect: bool = True,
    dt_hours: float = 1.0,
    shum_col: str | None = None,
    precip_col: str | None = None,
    precip_scale: float = 1.0,
    phase_T0: float | None = None,
    phase_T1: float | None = None,
) -> dict:
    """
    Convert a CSV meteorological file to FSM2 format.

    Parameters
    ----------
    input_file : str
        Path to input CSV (comma, space, or tab delimited).
    output_file : str
        Path for output FSM2 met file.
    col_map : dict, optional
        Mapping from FSM2 names to input column names.
        Keys: year, month, day, hour, SW, LW, Sf, Rf, Ta, RH, Ua, Ps
    units : dict, optional
        Units for each variable. If None and auto_detect=True, units are guessed.
    auto_detect : bool
        Whether to auto-detect units from data ranges.
    dt_hours : float
        Timestep in hours for the output file.
    shum_col : str, optional
        Name of a SPECIFIC humidity column (kg/kg).  When given, RH is derived
        from it with FSM2's own saturation formula and no RH column is required.
    precip_col : str, optional
        Name of a TOTAL precipitation column.  When given, Sf and Rf are derived
        from it with FSM2's own temperature ramp and no Sf/Rf columns are
        required.  Its unit is auto-detected (or forced with units["Pr"]) exactly
        like Sf/Rf.

    Returns
    -------
    dict with keys: n_rows, issues, output_file
    """
    # Read input
    input_path = Path(input_file)
    if input_path.suffix == ".csv":
        df = pd.read_csv(input_file)
    else:
        df = pd.read_csv(input_file, sep=r"\s+", header=None)

    # Default column mapping (assume FSM2-like order if no headers)
    default_map = {
        "year": "year", "month": "month", "day": "day", "hour": "hour",
        "SW": "SW", "LW": "LW", "Sf": "Sf", "Rf": "Rf",
        "Ta": "Ta", "RH": "RH", "Ua": "Ua", "Ps": "Ps",
    }
    # Columns that are DERIVED rather than read: drop them from the requirement
    # list and register the source column instead.
    derive_rh = shum_col is not None
    derive_phase = precip_col is not None
    if col_map is None and (derive_rh or derive_phase):
        col_map = {k: v for k, v in default_map.items()}
        if derive_rh:
            col_map.pop("RH")
            col_map["Qa"] = shum_col
        if derive_phase:
            col_map.pop("Sf")
            col_map.pop("Rf")
            col_map["Pr"] = precip_col
    elif col_map is not None:
        col_map = dict(col_map)
        if derive_rh:
            col_map.pop("RH", None)
            col_map["Qa"] = shum_col
        if derive_phase:
            col_map.pop("Sf", None)
            col_map.pop("Rf", None)
            col_map["Pr"] = precip_col

    if col_map is None:
        if df.columns.dtype == np.int64:
            # No headers — assign positional names
            names = ["year", "month", "day", "hour", "SW", "LW", "Sf", "Rf", "Ta", "RH", "Ua", "Ps"]
            if len(df.columns) >= len(names):
                df.columns = names + [f"extra_{i}" for i in range(len(df.columns) - len(names))]
            else:
                raise ValueError(f"Input has {len(df.columns)} columns, need at least {len(names)}")
        col_map = default_map

    # Validate input columns
    required = list(col_map.values())
    missing = validate_input(df, required)
    if missing:
        raise ValueError(f"Missing columns in input: {missing}")

    # Rename to standard names
    inv_map = {v: k for k, v in col_map.items()}
    df = df.rename(columns=inv_map)

    # Auto-detect or apply units
    detect_map = {k: k for k in default_map}
    if derive_rh:
        detect_map.pop("RH", None)
    if derive_phase:
        detect_map.pop("Sf", None)
        detect_map.pop("Rf", None)
        detect_map["Pr"] = "Pr"
    if units is None and auto_detect:
        print("Auto-detecting units...")
        units = auto_detect_units(df, detect_map)
    elif units is None:
        units = {"Ta": "K", "Ps": "Pa", "RH": "percent", "Sf": "kg/m2/s", "Rf": "kg/m2/s"}

    # Apply conversions
    df["Ta"] = convert_temperature(df["Ta"], units.get("Ta", "K"))
    df["Ps"] = convert_pressure(df["Ps"], units.get("Ps", "Pa"))

    # RH: read, or derived from specific humidity with FSM2's own es formula.
    if derive_rh:
        df["RH"] = shum_to_rh(df["Qa"], df["Ta"], df["Ps"])
        print(f"  Derived RH from specific humidity '{shum_col}' "
              f"(FSM2_DRIVE.F90 saturation formula): "
              f"min={df['RH'].min():.1f}%, max={df['RH'].max():.1f}%")
    else:
        df["RH"] = convert_humidity(df["RH"], units.get("RH", "percent"))

    # Sf/Rf: read, or derived from total precipitation with FSM2's own ramp.
    if derive_phase:
        pr = convert_precip(df["Pr"], units.get("Pr", "kg/m2/s"))
        if float(precip_scale) != 1.0:
            if not float(precip_scale) > 0:
                raise ValueError("precip_scale must be > 0, got %r" % (precip_scale,))
            pr = pr * float(precip_scale)
            print(f"  Applied SITE PRECIPITATION BIAS CORRECTION x{float(precip_scale):.4f} "
                  f"(ESM-SnowMIP protocol, Menard et al. 2019 Sect. 3) BEFORE phase split")
        if phase_T0 is None:
            sf, rf = partition_precip_fsm2(pr, df["Ta"])
            split_name = "FSM2's 0-2 degC ramp"
        else:
            if phase_T1 is None:
                raise ValueError(
                    "phase_T0 was given without phase_T1: the ESM-SnowMIP logistic "
                    "needs BOTH site-fitted parameters (Menard et al. 2019 Table 4, "
                    "see ESM_SNOWMIP_PHASE). Pass --phase-logistic T0 T1.")
            sf, rf = partition_precip_esm_snowmip(pr, df["Ta"], phase_T0, phase_T1)
            split_name = (f"the ESM-SnowMIP logistic T0={float(phase_T0):.2f} degC, "
                          f"T1={float(phase_T1):.2f} degC")
            print(f"  Phase split: {split_name}")
        df["Sf"], df["Rf"] = sf, rf
        tot = float(pr.sum())
        print(f"  Partitioned total precipitation '{precip_col}' into Sf/Rf with "
              f"{split_name}: snowfall fraction = "
              f"{(float(np.sum(sf)) / tot if tot > 0 else 0.0):.3f}")
    else:
        df["Sf"] = convert_precip(df["Sf"], units.get("Sf", "kg/m2/s"))
        df["Rf"] = convert_precip(df["Rf"], units.get("Rf", "kg/m2/s"))

    # Enforce physical limits
    df["Ua"] = df["Ua"].clip(lower=0.1)
    df["SW"] = df["SW"].clip(lower=0.0)
    df["RH"] = df["RH"].clip(lower=0.0, upper=100.0)
    df["Sf"] = df["Sf"].clip(lower=0.0)
    df["Rf"] = df["Rf"].clip(lower=0.0)

    # Validate output
    issues = validate_output(df)
    if issues:
        print("WARNING: Output validation issues:")
        for iss in issues:
            print(f"  - {iss}")

    # Write FSM2 format
    out_cols = ["year", "month", "day", "hour", "SW", "LW", "Sf", "Rf", "Ta", "RH", "Ua", "Ps"]
    out = df[out_cols]
    # `hour` is written with 3 decimals, NOT rounded to an integer: FSM2 declares
    # it real (format 3(i4),f8.3) and SOLARPOS uses it directly, so a half-hour
    # timestamp centre (0.5, 1.5, ...) must survive.  The previous "%2.0f" silently
    # rounded 0.5 -> 0 and 1.5 -> 2 (banker's rounding), corrupting solar position
    # for any forcing that is not stamped on the whole hour.
    lines = (
        out["year"].astype(int).map("{:4d}".format) + "  "
        + out["month"].astype(int).map("{:2d}".format) + "  "
        + out["day"].astype(int).map("{:2d}".format) + "  "
        + out["hour"].astype(float).map("{:7.3f}".format) + "  "
        + out["SW"].map("{:8.1f}".format) + "  "
        + out["LW"].map("{:8.1f}".format) + "  "
        + out["Sf"].map("{:.3e}".format) + "  "
        + out["Rf"].map("{:.3e}".format) + "  "
        + out["Ta"].map("{:8.1f}".format) + "  "
        + out["RH"].map("{:8.1f}".format) + "  "
        + out["Ua"].map("{:5.1f}".format) + "  "
        + out["Ps"].map("{:.0f}".format)
    )
    with open(output_file, "w") as f:
        f.write("\n".join(lines.tolist()) + "\n")

    result = {
        "n_rows": len(df),
        "issues": issues,
        "output_file": output_file,
        "period": f"{int(df['year'].iloc[0])}-{int(df['month'].iloc[0]):02d} to "
                  f"{int(df['year'].iloc[-1])}-{int(df['month'].iloc[-1]):02d}",
    }
    print(f"Wrote {len(df)} timesteps to {output_file}")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Convert met forcing to FSM2 format")
    parser.add_argument("input", help="Input CSV file")
    parser.add_argument("output", help="Output FSM2 met file")
    parser.add_argument("--ta-unit", default=None, choices=["C", "K"], help="Temperature unit")
    parser.add_argument("--ps-unit", default=None, choices=["Pa", "hPa", "kPa"], help="Pressure unit")
    parser.add_argument("--rh-unit", default=None, choices=["percent", "fraction"], help="RH unit")
    parser.add_argument("--precip-unit", default=None, choices=["kg/m2/s", "mm/h", "mm/day"], help="Precip unit")
    parser.add_argument("--shum-col", default=None,
                        help="Derive RH from this SPECIFIC humidity column (kg/kg) "
                             "instead of requiring an RH column")
    parser.add_argument("--precip-col", default=None,
                        help="Derive Sf/Rf from this TOTAL precipitation column "
                             "using FSM2's own 0-2 degC ramp, instead of requiring "
                             "separate Sf and Rf columns")
    parser.add_argument("--precip-scale", type=float, default=1.0,
                        help="Multiply total precipitation by this site mean-bias "
                             "factor BEFORE the phase split (ESM-SnowMIP protocol, "
                             "Menard et al. 2019 Sect. 3). Correct against an "
                             "UNDERCATCH-CORRECTED reference, never a raw gauge normal.")
    parser.add_argument("--phase-logistic", type=float, nargs=2, default=None,
                        metavar=("T0", "T1"),
                        help="Use the ESM-SnowMIP logistic phase split with these "
                             "site-fitted T0/T1 in degC (Menard et al. 2019 Table 4; "
                             "SOD 2.52 1.16) instead of FSM2's generic 0-2 degC ramp")
    args = parser.parse_args()

    units = {}
    if args.ta_unit:
        units["Ta"] = args.ta_unit
    if args.ps_unit:
        units["Ps"] = args.ps_unit
    if args.rh_unit:
        units["RH"] = args.rh_unit
    if args.precip_unit:
        units["Sf"] = args.precip_unit
        units["Rf"] = args.precip_unit
        units["Pr"] = args.precip_unit

    convert_forcing(
        args.input, args.output,
        units=units if units else None,
        auto_detect=not bool(units),
        shum_col=args.shum_col,
        precip_col=args.precip_col,
        precip_scale=args.precip_scale,
        phase_T0=(args.phase_logistic[0] if args.phase_logistic else None),
        phase_T1=(args.phase_logistic[1] if args.phase_logistic else None),
    )


if __name__ == "__main__":
    main()
