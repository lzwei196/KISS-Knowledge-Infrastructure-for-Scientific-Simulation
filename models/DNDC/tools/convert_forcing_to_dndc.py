#!/usr/bin/env python3
"""Convert gridded forcing data (CMFD, MSWX, NASA POWER) to DNDC climate text files.

Follows the validate-process-validate pattern:
  1. Validate inputs (paths, coordinates, date ranges)
  2. Process: read forcing, unit-convert, write DNDC climate .txt
  3. Validate outputs (physical plausibility checks on written files)

DNDC climate file format (one line per day):
    Jday  MaxT(C)  MinT(C)  Prec(cm)  Rad(MJ/m2/day)  Wind(m/s)  Hum(%)

Critical unit conversions:
  - Precipitation: mm -> cm  (divide by 10)
  - Temperature:   K  -> C   (subtract 273.15)
  - Radiation:     W/m2 -> MJ/m2/day (multiply by 0.0864)
"""

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Physical plausibility bounds
# ---------------------------------------------------------------------------
VALID_RANGES = {
    "prec_cm":  (0.0, 10.0),    # cm/day
    "tmax_c":   (-60.0, 60.0),
    "tmin_c":   (-60.0, 60.0),
    "rad_mj":   (0.0, 50.0),    # MJ/m2/day
    "wind":     (0.0, 50.0),    # m/s
    "hum":      (0.0, 100.0),   # %
}

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_inputs(forcing_dir: str, lat: float, lon: float,
                    start_year: int, end_year: int, source: str) -> dict:
    """Validate all inputs before processing.

    Returns a dict with validated/normalised values.

    Raises
    ------
    ValueError  on any invalid parameter
    FileNotFoundError  if forcing_dir does not exist
    """
    errors = []

    forcing_path = Path(forcing_dir)
    if not forcing_path.is_dir():
        raise FileNotFoundError(f"Forcing directory not found: {forcing_dir}")

    if not (-90.0 <= lat <= 90.0):
        errors.append(f"Latitude {lat} outside [-90, 90]")
    if not (-180.0 <= lon <= 180.0):
        errors.append(f"Longitude {lon} outside [-180, 180]")
    if start_year > end_year:
        errors.append(f"start_year ({start_year}) > end_year ({end_year})")
    if start_year < 1900 or end_year > 2100:
        errors.append(f"Year range [{start_year}, {end_year}] outside [1900, 2100]")

    valid_sources = ("cmfd", "mswx", "power")
    if source.lower() not in valid_sources:
        errors.append(f"Unknown source '{source}'. Must be one of {valid_sources}")

    if errors:
        raise ValueError("Input validation failed:\n  " + "\n  ".join(errors))

    return {
        "forcing_dir": forcing_path,
        "lat": float(lat),
        "lon": float(lon),
        "start_year": int(start_year),
        "end_year": int(end_year),
        "source": source.lower(),
    }


# ---------------------------------------------------------------------------
# Unit conversion helpers
# ---------------------------------------------------------------------------

def mm_to_cm(val_mm: float) -> float:
    """Convert precipitation from mm to cm (DNDC uses cm!)."""
    return val_mm / 10.0


def kelvin_to_celsius(val_k: float) -> float:
    """Convert temperature from Kelvin to degrees Celsius."""
    return val_k - 273.15


def wm2_to_mjm2day(val_wm2: float) -> float:
    """Convert irradiance W/m2 to daily radiation MJ/m2/day."""
    return val_wm2 * 0.0864


# ---------------------------------------------------------------------------
# Source-specific readers
# ---------------------------------------------------------------------------

def _read_cmfd(forcing_dir: Path, lat: float, lon: float,
               year: int) -> list[dict]:
    """Read CMFD forcing for one year.

    CMFD variables (per-file netCDF or CSV):
        prec  (mm/day)  -> cm
        temp  (K)       -> C  (used for both max and min if only one field)
        srad  (W/m2)    -> MJ/m2/day
        wind  (m/s)
        rhum  (%)

    Returns list of daily dicts with keys:
        jday, tmax_c, tmin_c, prec_cm, rad_mj, wind, hum
    """
    records: list[dict] = []
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    ndays = (end - start).days + 1

    # Attempt to load from netCDF files first, then fall back to CSV
    try:
        import netCDF4 as nc

        # CMFD typically stores data in yearly files per variable
        prec_file = _find_forcing_file(forcing_dir, "prec", year)
        temp_file = _find_forcing_file(forcing_dir, "temp", year)
        srad_file = _find_forcing_file(forcing_dir, "srad", year)
        wind_file = _find_forcing_file(forcing_dir, "wind", year)
        rhum_file = _find_forcing_file(forcing_dir, "rhum", year)

        prec = _extract_nearest_nc(prec_file, "prec", lat, lon)  # mm/day
        temp = _extract_nearest_nc(temp_file, "temp", lat, lon)  # K
        srad = _extract_nearest_nc(srad_file, "srad", lat, lon)  # W/m2
        wind_data = _extract_nearest_nc(wind_file, "wind", lat, lon)
        rhum_data = _extract_nearest_nc(rhum_file, "rhum", lat, lon)

        for d in range(min(ndays, len(prec))):
            current = start + timedelta(days=d)
            jday = current.timetuple().tm_yday
            t_c = kelvin_to_celsius(float(temp[d]))
            records.append({
                "jday": jday,
                "tmax_c": t_c + 3.0,   # approx diurnal range if only mean
                "tmin_c": t_c - 3.0,
                "prec_cm": mm_to_cm(float(prec[d])),
                "rad_mj": wm2_to_mjm2day(float(srad[d])),
                "wind": float(wind_data[d]),
                "hum": float(rhum_data[d]),
            })
    except (ImportError, FileNotFoundError):
        logger.info("netCDF4 not available or files not found; trying CSV fallback for CMFD")
        records = _read_csv_fallback(forcing_dir, year, source="cmfd")

    if not records:
        raise RuntimeError(f"No CMFD data loaded for year {year}")
    return records


def _read_mswx(forcing_dir: Path, lat: float, lon: float,
               year: int) -> list[dict]:
    """Read MSWX forcing for one year.

    MSWX variables:
        P       (mm/3hr)  -> sum to mm/day -> cm
        Tair    (K)       -> C
        SWd     (W/m2)    -> MJ/m2/day
        wind    (m/s)
        Pres    (Pa)  — not directly needed
        spechum (kg/kg) -> approximate RH
    """
    records: list[dict] = []
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    ndays = (end - start).days + 1

    try:
        import netCDF4 as nc

        p_file = _find_forcing_file(forcing_dir, "P", year)
        t_file = _find_forcing_file(forcing_dir, "Tair", year)
        sw_file = _find_forcing_file(forcing_dir, "SWd", year)
        w_file = _find_forcing_file(forcing_dir, "wind", year)
        sh_file = _find_forcing_file(forcing_dir, "spechum", year)
        pr_file = _find_forcing_file(forcing_dir, "Pres", year)

        # P is 3-hourly; sum 8 timesteps per day to get mm/day
        p_3hr = _extract_nearest_nc(p_file, "P", lat, lon)
        t_data = _extract_nearest_nc(t_file, "Tair", lat, lon)
        sw_data = _extract_nearest_nc(sw_file, "SWd", lat, lon)
        w_data = _extract_nearest_nc(w_file, "wind", lat, lon)
        sh_data = _extract_nearest_nc(sh_file, "spechum", lat, lon)
        pr_data = _extract_nearest_nc(pr_file, "Pres", lat, lon)

        # Aggregate 3-hourly precip to daily
        steps_per_day = 8
        daily_prec_mm = []
        for d in range(ndays):
            i0 = d * steps_per_day
            i1 = i0 + steps_per_day
            if i1 <= len(p_3hr):
                daily_prec_mm.append(float(np.sum(p_3hr[i0:i1])))
            else:
                daily_prec_mm.append(0.0)

        for d in range(ndays):
            current = start + timedelta(days=d)
            jday = current.timetuple().tm_yday
            t_c = kelvin_to_celsius(float(t_data[d]))
            # Approximate RH from specific humidity and pressure
            rh = _spechum_to_rh(float(sh_data[d]), float(pr_data[d]),
                                float(t_data[d]))
            records.append({
                "jday": jday,
                "tmax_c": t_c + 3.0,
                "tmin_c": t_c - 3.0,
                "prec_cm": mm_to_cm(daily_prec_mm[d]),
                "rad_mj": wm2_to_mjm2day(float(sw_data[d])),
                "wind": float(w_data[d]),
                "hum": np.clip(rh, 0.0, 100.0),
            })
    except (ImportError, FileNotFoundError):
        logger.info("netCDF4 not available or files not found; trying CSV fallback for MSWX")
        records = _read_csv_fallback(forcing_dir, year, source="mswx")

    if not records:
        raise RuntimeError(f"No MSWX data loaded for year {year}")
    return records


def _read_power(forcing_dir: Path, lat: float, lon: float,
                year: int) -> list[dict]:
    """Read NASA POWER daily data (typically CSV downloads).

    Expected columns (daily):
        T2M_MAX (C), T2M_MIN (C), PRECTOTCORR (mm/day),
        ALLSKY_SFC_SW_DWN (MJ/m2/day already), WS2M (m/s), RH2M (%)
    """
    records: list[dict] = []
    csv_path = forcing_dir / f"POWER_{year}.csv"
    if not csv_path.exists():
        csv_path = forcing_dir / f"power_{year}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"NASA POWER CSV not found: {csv_path}")

    import csv
    with open(csv_path, "r") as fh:
        # Skip header lines starting with '-END HEADER-' or comments
        reader_lines = fh.readlines()

    data_start = 0
    for i, line in enumerate(reader_lines):
        if "YEAR" in line and "DOY" in line:
            data_start = i
            break

    header = reader_lines[data_start].strip().split(",")
    for line in reader_lines[data_start + 1:]:
        parts = line.strip().split(",")
        if len(parts) < len(header):
            continue
        row = dict(zip(header, parts))
        try:
            jday = int(row.get("DOY", row.get("DY", 0)))
            tmax = float(row.get("T2M_MAX", 0))
            tmin = float(row.get("T2M_MIN", 0))
            prec_mm = float(row.get("PRECTOTCORR", row.get("PRECTOT", 0)))
            rad = float(row.get("ALLSKY_SFC_SW_DWN", 0))
            wind = float(row.get("WS2M", 0))
            hum = float(row.get("RH2M", 50))
            records.append({
                "jday": jday,
                "tmax_c": tmax,           # already C
                "tmin_c": tmin,           # already C
                "prec_cm": mm_to_cm(prec_mm),
                "rad_mj": rad,            # already MJ/m2/day
                "wind": wind,
                "hum": hum,
            })
        except (ValueError, KeyError) as exc:
            logger.warning("Skipping malformed POWER row: %s", exc)

    if not records:
        raise RuntimeError(f"No NASA POWER data loaded for year {year}")
    return records


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _find_forcing_file(directory: Path, varname: str, year: int) -> Path:
    """Locate a forcing file by variable name and year with common naming."""
    candidates = [
        directory / f"{varname}_{year}.nc",
        directory / f"{varname.lower()}_{year}.nc",
        directory / f"{varname.upper()}_{year}.nc",
        directory / f"{varname}/{year}.nc",
        directory / f"{varname}" / f"{varname}_{year}.nc",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        f"Cannot find forcing file for variable '{varname}', year {year} "
        f"in {directory}. Tried: {[str(c) for c in candidates]}"
    )


def _extract_nearest_nc(nc_path: Path, varname: str,
                         lat: float, lon: float) -> np.ndarray:
    """Extract the time series at the nearest grid point from a netCDF file."""
    import netCDF4 as nc

    ds = nc.Dataset(str(nc_path), "r")
    try:
        lat_var = ds.variables.get("lat", ds.variables.get("latitude"))
        lon_var = ds.variables.get("lon", ds.variables.get("longitude"))
        if lat_var is None or lon_var is None:
            raise KeyError("Cannot find lat/lon variables in " + str(nc_path))

        lat_idx = int(np.argmin(np.abs(lat_var[:] - lat)))
        lon_idx = int(np.argmin(np.abs(lon_var[:] - lon)))

        data_var = ds.variables.get(varname)
        if data_var is None:
            # Try lowercase / uppercase
            for key in ds.variables:
                if key.lower() == varname.lower():
                    data_var = ds.variables[key]
                    break
        if data_var is None:
            raise KeyError(f"Variable '{varname}' not found in {nc_path}")

        # Assume dimensions are (time, lat, lon) or (time, y, x)
        ndim = len(data_var.dimensions)
        if ndim == 3:
            data = data_var[:, lat_idx, lon_idx]
        elif ndim == 1:
            data = data_var[:]
        else:
            data = data_var[:, lat_idx, lon_idx]

        return np.array(data, dtype=np.float64)
    finally:
        ds.close()


def _spechum_to_rh(q: float, p_pa: float, t_k: float) -> float:
    """Approximate relative humidity from specific humidity, pressure, temperature."""
    # Saturation vapour pressure (Tetens formula)
    t_c = t_k - 273.15
    es = 610.78 * np.exp(17.27 * t_c / (t_c + 237.3))  # Pa
    # Actual vapour pressure from specific humidity
    e = q * p_pa / (0.622 + 0.378 * q)
    rh = 100.0 * e / es
    return float(np.clip(rh, 0.0, 100.0))


def _read_csv_fallback(forcing_dir: Path, year: int,
                       source: str) -> list[dict]:
    """Read a simple CSV fallback with pre-processed daily columns.

    Expected CSV name: {source}_{year}.csv
    Expected columns: jday, tmax, tmin, prec_mm, srad_wm2, wind, hum
    Units follow source conventions; conversions applied here.
    """
    import csv

    csv_path = forcing_dir / f"{source}_{year}.csv"
    if not csv_path.exists():
        return []

    records = []
    with open(csv_path, "r") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                prec_mm = float(row["prec_mm"])
                tmax_raw = float(row["tmax"])
                tmin_raw = float(row["tmin"])
                srad = float(row["srad_wm2"])

                # Apply conversions depending on source
                if source in ("cmfd", "mswx"):
                    tmax_c = kelvin_to_celsius(tmax_raw)
                    tmin_c = kelvin_to_celsius(tmin_raw)
                else:
                    tmax_c = tmax_raw
                    tmin_c = tmin_raw

                records.append({
                    "jday": int(row["jday"]),
                    "tmax_c": tmax_c,
                    "tmin_c": tmin_c,
                    "prec_cm": mm_to_cm(prec_mm),
                    "rad_mj": wm2_to_mjm2day(srad),
                    "wind": float(row["wind"]),
                    "hum": float(row["hum"]),
                })
            except (ValueError, KeyError) as exc:
                logger.warning("Skipping CSV row: %s", exc)
    return records


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_daily_record(rec: dict, day_index: int) -> list[str]:
    """Check a single daily record against physical bounds.

    Returns list of warning strings (empty if all OK).
    """
    warnings: list[str] = []
    lo, hi = VALID_RANGES["prec_cm"]
    if not (lo <= rec["prec_cm"] <= hi):
        warnings.append(
            f"Day {rec['jday']}: Prec {rec['prec_cm']:.4f} cm outside [{lo}, {hi}]"
        )
    for tkey in ("tmax_c", "tmin_c"):
        lo, hi = VALID_RANGES[tkey]
        if not (lo <= rec[tkey] <= hi):
            warnings.append(
                f"Day {rec['jday']}: {tkey} {rec[tkey]:.2f} outside [{lo}, {hi}]"
            )
    lo, hi = VALID_RANGES["rad_mj"]
    if not (lo <= rec["rad_mj"] <= hi):
        warnings.append(
            f"Day {rec['jday']}: Rad {rec['rad_mj']:.2f} outside [{lo}, {hi}]"
        )
    if rec["tmin_c"] > rec["tmax_c"]:
        warnings.append(
            f"Day {rec['jday']}: Tmin ({rec['tmin_c']:.2f}) > Tmax ({rec['tmax_c']:.2f})"
        )
    lo, hi = VALID_RANGES["wind"]
    if not (lo <= rec["wind"] <= hi):
        warnings.append(
            f"Day {rec['jday']}: Wind {rec['wind']:.2f} outside [{lo}, {hi}]"
        )
    lo, hi = VALID_RANGES["hum"]
    if not (lo <= rec["hum"] <= hi):
        warnings.append(
            f"Day {rec['jday']}: Hum {rec['hum']:.1f} outside [{lo}, {hi}]"
        )
    return warnings


def validate_output_file(filepath: Path, expected_days: int) -> list[str]:
    """Re-read a written climate file and validate contents.

    Returns list of warning/error strings.
    """
    issues: list[str] = []
    if not filepath.exists():
        issues.append(f"Output file does not exist: {filepath}")
        return issues

    line_count = 0
    with open(filepath, "r") as fh:
        for lineno, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) != 7:
                issues.append(f"Line {lineno}: expected 7 columns, got {len(parts)}")
                continue
            try:
                jday = int(parts[0])
                tmax = float(parts[1])
                tmin = float(parts[2])
                prec = float(parts[3])
                rad = float(parts[4])
                wind = float(parts[5])
                hum = float(parts[6])
            except ValueError as exc:
                issues.append(f"Line {lineno}: parse error: {exc}")
                continue

            if prec < 0 or prec > 10:
                issues.append(f"Line {lineno}: Prec {prec} cm suspect")
            if tmax < -60 or tmax > 60:
                issues.append(f"Line {lineno}: Tmax {tmax} C suspect")
            if tmin < -60 or tmin > 60:
                issues.append(f"Line {lineno}: Tmin {tmin} C suspect")
            if rad < 0:
                issues.append(f"Line {lineno}: Rad {rad} negative")
            line_count += 1

    if line_count != expected_days:
        issues.append(
            f"Expected {expected_days} daily records, found {line_count}"
        )
    return issues


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def write_climate_file(records: list[dict], output_path: Path) -> None:
    """Write daily records to a DNDC-format climate text file."""
    with open(output_path, "w") as fh:
        for rec in records:
            fh.write(
                f"{rec['jday']:3d} "
                f"{rec['tmax_c']:7.2f} "
                f"{rec['tmin_c']:7.2f} "
                f"{rec['prec_cm']:8.4f} "
                f"{rec['rad_mj']:7.2f} "
                f"{rec['wind']:6.2f} "
                f"{rec['hum']:6.1f}\n"
            )


def process(forcing_dir: str, lat: float, lon: float,
            start_year: int, end_year: int, source: str,
            output_dir: str) -> list[str]:
    """End-to-end: validate inputs -> convert -> validate outputs.

    Parameters
    ----------
    forcing_dir : str
        Path to directory containing forcing data files.
    lat, lon : float
        Target coordinates.
    start_year, end_year : int
        Year range (inclusive).
    source : str
        One of 'cmfd', 'mswx', 'power'.
    output_dir : str
        Directory to write climate .txt files.

    Returns
    -------
    list[str]
        Paths to all created climate files.
    """
    # --- Phase 1: Validate inputs ---
    params = validate_inputs(forcing_dir, lat, lon, start_year, end_year, source)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    logger.info("Input validation passed. Source: %s, years: %d-%d",
                source, start_year, end_year)

    reader_map = {
        "cmfd":  _read_cmfd,
        "mswx":  _read_mswx,
        "power": _read_power,
    }
    reader = reader_map[params["source"]]

    created_files: list[str] = []
    all_warnings: list[str] = []

    # --- Phase 2: Process each year ---
    for year in range(params["start_year"], params["end_year"] + 1):
        logger.info("Processing year %d ...", year)
        records = reader(params["forcing_dir"], params["lat"],
                         params["lon"], year)

        # Pre-write validation of daily records
        for i, rec in enumerate(records):
            w = validate_daily_record(rec, i)
            all_warnings.extend(w)

        outfile = out_path / f"climate_{year}.txt"
        write_climate_file(records, outfile)
        logger.info("Wrote %s (%d days)", outfile, len(records))

        # --- Phase 3: Validate output ---
        is_leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
        expected_days = 366 if is_leap else 365
        out_issues = validate_output_file(outfile, expected_days)
        all_warnings.extend(out_issues)

        created_files.append(str(outfile))

    if all_warnings:
        logger.warning("Completed with %d warnings:", len(all_warnings))
        for w in all_warnings[:50]:  # cap log noise
            logger.warning("  %s", w)
    else:
        logger.info("All output validations passed.")

    return created_files


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Convert gridded forcing data to DNDC climate text files."
    )
    parser.add_argument("--forcing-dir", required=True,
                        help="Directory with forcing data files")
    parser.add_argument("--lat", type=float, required=True,
                        help="Latitude of target site")
    parser.add_argument("--lon", type=float, required=True,
                        help="Longitude of target site")
    parser.add_argument("--start-year", type=int, required=True,
                        help="First year to process (inclusive)")
    parser.add_argument("--end-year", type=int, required=True,
                        help="Last year to process (inclusive)")
    parser.add_argument("--source", required=True,
                        choices=["cmfd", "mswx", "power"],
                        help="Forcing data source type")
    parser.add_argument("--output-dir", required=True,
                        help="Directory for output climate .txt files")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        files = process(
            forcing_dir=args.forcing_dir,
            lat=args.lat,
            lon=args.lon,
            start_year=args.start_year,
            end_year=args.end_year,
            source=args.source,
            output_dir=args.output_dir,
        )
        print(f"Created {len(files)} climate file(s):")
        for f in files:
            print(f"  {f}")
    except Exception:
        logger.exception("Fatal error during forcing conversion")
        sys.exit(1)


if __name__ == "__main__":
    main()
