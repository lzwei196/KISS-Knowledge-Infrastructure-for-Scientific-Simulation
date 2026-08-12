#!/usr/bin/env python3
"""
validate_weather_file.py - Validates a DSSAT .WTH weather file.

Checks header format, daily record integrity, date sequence continuity,
physical range constraints on weather variables, and missing value flags.

DSSAT Weather File Format Reference:
    Header line 1: *WEATHER DATA : <description>
    Header line 2: @INSI LAT LONG ELEV TAV AMP REFHT WNDHT
    Header line 3: <values for above>
    Data header:   @DATE SRAD TMAX TMIN RAIN ...
    Data records:  YYDDD <values>

Exit codes:
    0 = success (validation complete, may have warnings)
    1 = input error (file not found, not readable)
    2 = processing error (unparseable file format)
    3 = output error (validation failed with errors)
"""

import sys
import os
import logging
import json
import math
from datetime import datetime, timedelta
from collections import OrderedDict

# ---------------------------------------------------------------------------
# INPUT VARIABLES (agent sets these before invocation)
# ---------------------------------------------------------------------------
WEATHER_FILE_PATH = ""      # Path to .WTH file (required)
STRICT_MODE = False         # If True, treat warnings as errors
OUTPUT_JSON = True          # If True, print JSON report to stdout

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s"
)
logger = logging.getLogger("validate_weather_file")


def yyddd_to_date(yyddd_str):
    """Convert YYDDD or YYYYDDD string to a datetime.date object.

    DSSAT Y2K convention:
        YY 0-70  -> 2000-2070
        YY 71-99 -> 1971-1999
        YYYY     -> used directly if 4+ digit year

    Args:
        yyddd_str: String like '82001' (YYDDD) or '1982001' (YYYYDDD).

    Returns:
        datetime.date or None if unparseable.
    """
    s = yyddd_str.strip()
    try:
        val = int(s)
    except ValueError:
        return None

    if val > 9999999 or val < 0:
        return None

    if len(s) <= 5:
        yy = val // 1000
        ddd = val % 1000
        if yy <= 70:
            year = 2000 + yy
        else:
            year = 1900 + yy
    elif len(s) <= 7:
        year = val // 1000
        ddd = val % 1000
    else:
        return None

    if ddd < 1 or ddd > 366:
        return None

    try:
        return datetime(year, 1, 1).date() + timedelta(days=ddd - 1)
    except (ValueError, OverflowError):
        return None


def parse_header_line(line, headers):
    """Parse a whitespace-delimited data line using header column names.

    Args:
        line: The data line string.
        headers: List of header column names.

    Returns:
        dict mapping header names to string values.
    """
    parts = line.split()
    result = {}
    for i, h in enumerate(headers):
        if i < len(parts):
            result[h] = parts[i]
        else:
            result[h] = None
    return result


def is_missing(val_str):
    """Check if a value string represents DSSAT missing data (-99 variants)."""
    if val_str is None:
        return True
    s = val_str.strip()
    try:
        v = float(s)
        return v == -99.0 or v == -99
    except ValueError:
        return s == "-99" or s == "-99.0" or s == "-99."


def validate():
    """Run all validation checks on the weather file.

    Returns:
        dict with keys:
            passed (bool): True if no errors found.
            errors (list[str]): Critical problems that would cause DSSAT failure.
            warnings (list[str]): Non-fatal issues that may affect simulation quality.
            info (dict): Summary statistics and metadata.
            missing_value_counts (dict): Count of -99 values per variable.
    """
    errors = []
    warnings = []
    info = OrderedDict()
    missing_counts = {}

    # -----------------------------------------------------------------------
    # INPUT VALIDATION
    # -----------------------------------------------------------------------
    if not WEATHER_FILE_PATH:
        logger.error("WEATHER_FILE_PATH is empty.")
        return {"passed": False, "errors": ["WEATHER_FILE_PATH not specified"],
                "warnings": [], "info": {}, "missing_value_counts": {}}

    if not os.path.isfile(WEATHER_FILE_PATH):
        logger.error("File not found: %s", WEATHER_FILE_PATH)
        return {"passed": False,
                "errors": [f"File not found: {WEATHER_FILE_PATH}"],
                "warnings": [], "info": {}, "missing_value_counts": {}}

    try:
        with open(WEATHER_FILE_PATH, "r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()
    except IOError as e:
        logger.error("Cannot read file: %s", e)
        return {"passed": False, "errors": [f"Cannot read file: {e}"],
                "warnings": [], "info": {}, "missing_value_counts": {}}

    if len(raw_lines) == 0:
        errors.append("File is empty.")
        return {"passed": False, "errors": errors,
                "warnings": warnings, "info": info,
                "missing_value_counts": missing_counts}

    info["file_path"] = os.path.abspath(WEATHER_FILE_PATH)
    info["total_lines"] = len(raw_lines)

    # -----------------------------------------------------------------------
    # HEADER VALIDATION
    # -----------------------------------------------------------------------
    # Find the weather header line starting with *WEATHER or first non-blank
    first_content_line = None
    for line in raw_lines:
        stripped = line.strip()
        if stripped:
            first_content_line = stripped
            break

    if first_content_line is None:
        errors.append("File contains only blank lines.")
        return {"passed": False, "errors": errors,
                "warnings": warnings, "info": info,
                "missing_value_counts": missing_counts}

    if first_content_line.startswith("*WEATHER"):
        info["description"] = first_content_line.replace("*WEATHER DATA :", "").strip()
    else:
        warnings.append(
            f"File does not start with *WEATHER DATA header. "
            f"First line: '{first_content_line[:60]}'"
        )

    # Find station header (@INSI line)
    station_header_idx = None
    station_data_idx = None
    daily_header_idx = None
    expected_station_cols = ["INSI", "LAT", "LONG", "ELEV", "TAV", "AMP",
                             "REFHT", "WNDHT"]

    for i, line in enumerate(raw_lines):
        stripped = line.strip()
        if stripped.startswith("@") and "INSI" in stripped:
            station_header_idx = i
            # The data line immediately follows (next non-blank, non-comment)
            for j in range(i + 1, len(raw_lines)):
                sj = raw_lines[j].strip()
                if sj and not sj.startswith("!") and not sj.startswith("@"):
                    station_data_idx = j
                    break
            break

    if station_header_idx is None:
        errors.append(
            "Missing station header line (@INSI LAT LONG ELEV TAV AMP REFHT WNDHT)."
        )
    else:
        # Parse header columns
        header_line = raw_lines[station_header_idx].strip()
        # Remove leading @
        header_cols = header_line.lstrip("@ ").split()
        info["station_header_columns"] = header_cols

        # Check required columns present
        for col in expected_station_cols:
            if col not in header_cols:
                warnings.append(f"Station header missing expected column: {col}")

        # Parse station data
        if station_data_idx is not None:
            station_vals = parse_header_line(
                raw_lines[station_data_idx].strip(), header_cols
            )
            info["station_data"] = station_vals

            # Extract and validate TAV / AMP
            tav_str = station_vals.get("TAV")
            amp_str = station_vals.get("AMP")

            if tav_str is not None and not is_missing(tav_str):
                try:
                    tav = float(tav_str)
                    info["TAV"] = tav
                    if tav <= 0:
                        warnings.append(
                            f"TAV = {tav} <= 0. Check if this is realistic for the location."
                        )
                except ValueError:
                    errors.append(f"TAV value is not numeric: '{tav_str}'")
            else:
                warnings.append("TAV is missing (-99) in station header.")

            if amp_str is not None and not is_missing(amp_str):
                try:
                    amp = float(amp_str)
                    info["AMP"] = amp
                    if amp <= 0:
                        warnings.append(
                            f"AMP = {amp} <= 0. Check if this is realistic for the location."
                        )
                except ValueError:
                    errors.append(f"AMP value is not numeric: '{amp_str}'")
            else:
                warnings.append("AMP is missing (-99) in station header.")

            # Validate LAT, LONG, ELEV
            lat_str = station_vals.get("LAT")
            lon_str = station_vals.get("LONG")
            elev_str = station_vals.get("ELEV")

            if lat_str and not is_missing(lat_str):
                try:
                    lat = float(lat_str)
                    if lat < -90 or lat > 90:
                        errors.append(f"LAT = {lat} out of range [-90, 90].")
                    info["LAT"] = lat
                except ValueError:
                    errors.append(f"LAT is not numeric: '{lat_str}'")

            if lon_str and not is_missing(lon_str):
                try:
                    lon = float(lon_str)
                    if lon < -180 or lon > 360:
                        errors.append(f"LONG = {lon} out of range [-180, 360].")
                    info["LONG"] = lon
                except ValueError:
                    errors.append(f"LONG is not numeric: '{lon_str}'")

            if elev_str and not is_missing(elev_str):
                try:
                    elev = float(elev_str)
                    if elev < -500 or elev > 9000:
                        warnings.append(
                            f"ELEV = {elev} seems unusual (range check: -500 to 9000 m)."
                        )
                    info["ELEV"] = elev
                except ValueError:
                    warnings.append(f"ELEV is not numeric: '{elev_str}'")
        else:
            errors.append("Station data line not found after station header.")

    # -----------------------------------------------------------------------
    # DAILY DATA HEADER
    # -----------------------------------------------------------------------
    for i, line in enumerate(raw_lines):
        stripped = line.strip()
        if stripped.startswith("@DATE"):
            daily_header_idx = i
            break

    if daily_header_idx is None:
        errors.append("Missing daily data header line (starting with @DATE).")
        return {"passed": len(errors) == 0, "errors": errors,
                "warnings": warnings, "info": info,
                "missing_value_counts": missing_counts}

    daily_header_cols = raw_lines[daily_header_idx].strip().lstrip("@").split()
    # First column is DATE
    info["daily_columns"] = daily_header_cols

    # Required daily columns
    required_daily = ["DATE", "SRAD", "TMAX", "TMIN", "RAIN"]
    for col in required_daily:
        if col not in daily_header_cols:
            errors.append(f"Required daily data column missing: {col}")

    # -----------------------------------------------------------------------
    # PARSE DAILY RECORDS
    # -----------------------------------------------------------------------
    daily_records = []
    parse_errors = 0

    for i in range(daily_header_idx + 1, len(raw_lines)):
        line = raw_lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("!") or stripped.startswith("*") or stripped.startswith("@"):
            continue

        parts = stripped.split()
        if len(parts) < len(required_daily):
            parse_errors += 1
            if parse_errors <= 5:
                errors.append(
                    f"Line {i + 1}: insufficient columns ({len(parts)} < {len(required_daily)}). "
                    f"Content: '{stripped[:60]}'"
                )
            continue

        record = {}
        for j, col in enumerate(daily_header_cols):
            if j < len(parts):
                record[col] = parts[j]
            else:
                record[col] = None

        daily_records.append((i + 1, record))  # (line_number, record_dict)

    if parse_errors > 5:
        errors.append(f"... and {parse_errors - 5} more lines with insufficient columns.")

    info["daily_record_count"] = len(daily_records)

    if len(daily_records) == 0:
        errors.append("No daily data records found.")
        return {"passed": len(errors) == 0, "errors": errors,
                "warnings": warnings, "info": info,
                "missing_value_counts": missing_counts}

    # -----------------------------------------------------------------------
    # VALIDATE DATES (YYDDD format and continuity)
    # -----------------------------------------------------------------------
    dates = []
    date_errors = 0

    for line_num, rec in daily_records:
        date_str = rec.get("DATE")
        if date_str is None:
            date_errors += 1
            if date_errors <= 5:
                errors.append(f"Line {line_num}: DATE field is missing.")
            continue

        d = yyddd_to_date(date_str)
        if d is None:
            date_errors += 1
            if date_errors <= 5:
                errors.append(
                    f"Line {line_num}: invalid YYDDD date '{date_str}'."
                )
        else:
            dates.append((line_num, d))

    if date_errors > 5:
        errors.append(f"... and {date_errors - 5} more date parsing errors.")

    if dates:
        info["date_range_start"] = str(dates[0][1])
        info["date_range_end"] = str(dates[-1][1])

        # Check for missing days
        missing_days = []
        for k in range(1, len(dates)):
            prev_date = dates[k - 1][1]
            curr_date = dates[k][1]
            gap = (curr_date - prev_date).days
            if gap != 1:
                if gap == 0:
                    warnings.append(
                        f"Duplicate date {curr_date} at lines "
                        f"{dates[k - 1][0]} and {dates[k][0]}."
                    )
                elif gap < 0:
                    errors.append(
                        f"Dates not in chronological order: {prev_date} (line {dates[k - 1][0]}) "
                        f"-> {curr_date} (line {dates[k][0]})."
                    )
                else:
                    # gap > 1: missing days
                    for offset in range(1, gap):
                        missing_days.append(prev_date + timedelta(days=offset))

        if missing_days:
            if len(missing_days) <= 10:
                warnings.append(
                    f"{len(missing_days)} missing day(s) in date sequence: "
                    f"{', '.join(str(d) for d in missing_days)}"
                )
            else:
                warnings.append(
                    f"{len(missing_days)} missing day(s) in date sequence. "
                    f"First 5: {', '.join(str(d) for d in missing_days[:5])}"
                )
        info["missing_day_count"] = len(missing_days)

    # -----------------------------------------------------------------------
    # VALIDATE VARIABLE RANGES AND MISSING VALUES
    # -----------------------------------------------------------------------
    # Initialize missing counts for all daily columns
    for col in daily_header_cols:
        missing_counts[col] = 0

    nan_count = 0
    srad_errors = 0
    tmax_tmin_errors = 0
    tmax_tmin_warnings_count = 0
    rain_errors = 0

    for line_num, rec in daily_records:
        # Count missing values (-99)
        for col in daily_header_cols:
            val_str = rec.get(col)
            if is_missing(val_str):
                missing_counts[col] = missing_counts.get(col, 0) + 1

        # Check for NaN values (would cause silent failure in DSSAT)
        for col in daily_header_cols:
            val_str = rec.get(col)
            if val_str is not None:
                try:
                    v = float(val_str)
                    if math.isnan(v) or math.isinf(v):
                        nan_count += 1
                        if nan_count <= 5:
                            errors.append(
                                f"Line {line_num}: NaN/Inf value in column {col} = '{val_str}'."
                            )
                except ValueError:
                    # Non-numeric; skip unless it's a required column
                    if col in required_daily and col != "DATE":
                        errors.append(
                            f"Line {line_num}: non-numeric value in column {col} = '{val_str}'."
                        )

        # SRAD range check: 0 < SRAD < 100 MJ/m^2/day
        srad_str = rec.get("SRAD")
        if srad_str and not is_missing(srad_str):
            try:
                srad = float(srad_str)
                if not math.isnan(srad):
                    if srad <= 0:
                        srad_errors += 1
                        if srad_errors <= 5:
                            errors.append(
                                f"Line {line_num}: SRAD = {srad} <= 0 MJ/m2/day."
                            )
                    elif srad >= 100:
                        srad_errors += 1
                        if srad_errors <= 5:
                            errors.append(
                                f"Line {line_num}: SRAD = {srad} >= 100 MJ/m2/day (unrealistic)."
                            )
            except ValueError:
                pass  # Already caught above

        # TMAX >= TMIN check
        tmax_str = rec.get("TMAX")
        tmin_str = rec.get("TMIN")
        if (tmax_str and not is_missing(tmax_str) and
                tmin_str and not is_missing(tmin_str)):
            try:
                tmax = float(tmax_str)
                tmin = float(tmin_str)
                if not (math.isnan(tmax) or math.isnan(tmin)):
                    if tmax < tmin:
                        tmax_tmin_errors += 1
                        if tmax_tmin_errors <= 5:
                            errors.append(
                                f"Line {line_num}: TMAX ({tmax}) < TMIN ({tmin})."
                            )
                    elif (tmax - tmin) < 0.05 and (tmax - tmin) >= 0:
                        tmax_tmin_warnings_count += 1
                        if tmax_tmin_warnings_count <= 5:
                            warnings.append(
                                f"Line {line_num}: TMAX - TMIN = {tmax - tmin:.3f} < 0.05 degC "
                                f"(potential data issue)."
                            )
            except ValueError:
                pass

        # RAIN >= 0 check
        rain_str = rec.get("RAIN")
        if rain_str and not is_missing(rain_str):
            try:
                rain = float(rain_str)
                if not math.isnan(rain) and rain < 0:
                    rain_errors += 1
                    if rain_errors <= 5:
                        errors.append(
                            f"Line {line_num}: RAIN = {rain} < 0 mm."
                        )
            except ValueError:
                pass

    # Summarize overflow error counts
    if srad_errors > 5:
        errors.append(f"... and {srad_errors - 5} more SRAD range errors.")
    if tmax_tmin_errors > 5:
        errors.append(f"... and {tmax_tmin_errors - 5} more TMAX < TMIN errors.")
    if tmax_tmin_warnings_count > 5:
        warnings.append(
            f"... and {tmax_tmin_warnings_count - 5} more TMAX ~ TMIN warnings."
        )
    if rain_errors > 5:
        errors.append(f"... and {rain_errors - 5} more negative RAIN errors.")
    if nan_count > 5:
        errors.append(f"... and {nan_count - 5} more NaN/Inf value errors.")

    # Report total missing values
    total_missing = sum(missing_counts.values())
    info["total_missing_values"] = total_missing
    if total_missing > 0:
        warnings.append(
            f"Total -99 (missing) values across all columns: {total_missing}. "
            f"Breakdown: {dict(missing_counts)}"
        )

    # -----------------------------------------------------------------------
    # STRICT MODE: promote warnings to errors
    # -----------------------------------------------------------------------
    if STRICT_MODE:
        errors.extend(warnings)
        warnings = []

    # -----------------------------------------------------------------------
    # OUTPUT VALIDATION
    # -----------------------------------------------------------------------
    passed = len(errors) == 0
    report = {
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
        "info": dict(info),
        "missing_value_counts": missing_counts,
    }

    return report


def main():
    """Entry point: run validation and output results.

    The target may be supplied on the command line
    (``validate_weather_file.py /path/to/SITE0001.WTH``) so a batch driver can
    validate many .WTH files without rewriting the module. The module global
    WEATHER_FILE_PATH stays the default when no argument is given, so existing
    set-the-global callers are unaffected.
    """
    global WEATHER_FILE_PATH
    _pos = [a for a in sys.argv[1:] if not a.startswith("-")]
    if _pos:
        WEATHER_FILE_PATH = _pos[0]

    # -----------------------------------------------------------------------
    # PRECONDITIONS
    # -----------------------------------------------------------------------
    if not WEATHER_FILE_PATH:
        logger.error("WEATHER_FILE_PATH must be set before running.")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # CORE PROCESSING
    # -----------------------------------------------------------------------
    try:
        report = validate()
    except Exception as e:
        logger.error("Unexpected processing error: %s", e, exc_info=True)
        sys.exit(2)

    # -----------------------------------------------------------------------
    # POSTCONDITIONS
    # -----------------------------------------------------------------------
    # Verify report structure
    required_keys = {"passed", "errors", "warnings", "info", "missing_value_counts"}
    if not required_keys.issubset(report.keys()):
        logger.error(
            "Report missing required keys: %s",
            required_keys - report.keys()
        )
        sys.exit(3)

    if not isinstance(report["passed"], bool):
        logger.error("report['passed'] must be bool, got %s", type(report["passed"]))
        sys.exit(3)

    if not isinstance(report["errors"], list):
        logger.error("report['errors'] must be list, got %s", type(report["errors"]))
        sys.exit(3)

    # -----------------------------------------------------------------------
    # OUTPUT
    # -----------------------------------------------------------------------
    if report["passed"]:
        logger.info("VALIDATION PASSED for %s", WEATHER_FILE_PATH)
    else:
        logger.warning(
            "VALIDATION FAILED for %s (%d errors)",
            WEATHER_FILE_PATH, len(report["errors"])
        )

    if report["warnings"]:
        logger.info("%d warning(s) generated.", len(report["warnings"]))

    if OUTPUT_JSON:
        print(json.dumps(report, indent=2, default=str))

    if not report["passed"]:
        sys.exit(3)
    sys.exit(0)


if __name__ == "__main__":
    main()
