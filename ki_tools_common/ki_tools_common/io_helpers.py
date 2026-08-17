"""
io_helpers.py -- Common I/O patterns: JSON output formatting, date parsing, and
standardised data readers.

Consolidates patterns used across 326+ model tool scripts.

Examples::

    >>> from ki_tools_common.io_helpers import standard_result, parse_date_flexible
    >>> result = standard_result("success", outputs={"discharge_file": "out.csv"})
    >>> result['status']
    'success'
    >>> parse_date_flexible("2000-01-15")
    datetime.datetime(2000, 1, 15, 0, 0)
"""

from __future__ import annotations

import csv
import datetime
import json
import os
import warnings
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np


def standard_result(
    status: str,
    errors: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
    outputs: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a standardised JSON-serialisable result dictionary.

    This is the canonical output format shared by all KI tool scripts.

    Args:
        status: Overall status string, typically ``'success'`` or ``'error'``.
        errors: List of error messages (default empty).
        warnings: List of warning messages (default empty).
        outputs: Arbitrary dict of output paths / values (default empty).
        metrics: Arbitrary dict of computed metrics (default empty).

    Returns:
        Dict ready for ``json.dumps()``.

    Example::

        >>> r = standard_result("success", metrics={"NSE": 0.85})
        >>> r['status']
        'success'
        >>> r['metrics']['NSE']
        0.85
    """
    result: Dict[str, Any] = {"status": status}
    result["errors"] = list(errors) if errors else []
    result["warnings"] = list(warnings) if warnings else []
    result["outputs"] = dict(outputs) if outputs else {}
    result["metrics"] = _make_serialisable(dict(metrics) if metrics else {})
    return result


def _make_serialisable(obj: Any) -> Any:
    """Recursively convert numpy types to Python natives for JSON serialisation."""
    if isinstance(obj, dict):
        return {k: _make_serialisable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serialisable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, np.ndarray):
        return _make_serialisable(obj.tolist())
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


# ---------------------------------------------------------------------------
# Flexible date parsing
# ---------------------------------------------------------------------------

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y%m%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y%m%d%H%M",
    "%Y-%m",
    "%Y",
]


def parse_date_flexible(date_str: str) -> datetime.datetime:
    """Parse a date string by trying multiple common formats.

    Tries the following formats in order:
    ``YYYY-MM-DD``, ``YYYY/MM/DD``, ``YYYYMMDD``, ``DD-MM-YYYY``,
    ``DD/MM/YYYY``, ``YYYY-MM-DD HH:MM:SS``, ``YYYY/MM/DD HH:MM:SS``,
    ``YYYY-MM-DDTHH:MM:SS``, ``YYYY-MM-DDTHH:MM:SSZ``, ``YYYYMMDDHHMM``,
    ``YYYY-MM``, ``YYYY``.

    Args:
        date_str: Date string to parse.

    Returns:
        ``datetime.datetime`` object.

    Raises:
        ValueError: If none of the known formats match.

    Example::

        >>> parse_date_flexible("2000-01-15")
        datetime.datetime(2000, 1, 15, 0, 0)
        >>> parse_date_flexible("15/01/2000")
        datetime.datetime(2000, 1, 15, 0, 0)
    """
    date_str = date_str.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Cannot parse date string '{date_str}'. "
        f"Tried formats: {_DATE_FORMATS}"
    )


# ---------------------------------------------------------------------------
# Generic observation data reader
# ---------------------------------------------------------------------------

def read_obs_discharge(
    path: str,
    date_col: str = "date",
    discharge_col: str = "discharge",
    sep: str = ",",
) -> Dict[str, np.ndarray]:
    """Read observed discharge data from a CSV or delimited text file.

    Handles common file layouts:
      - CSV with ``date`` and ``discharge`` columns.
      - Whitespace- or comma-delimited.
      - Dates in various formats (handled by :func:`parse_date_flexible`).

    Args:
        path: Path to the observation file.
        date_col: Column name for dates (case-insensitive matching).
        discharge_col: Column name for discharge (case-insensitive matching).
        sep: Column separator (default ``','``).

    Returns:
        Dict with ``'dates'`` (numpy datetime64 array) and ``'discharge'``
        (numpy float64 array, units assumed m3/s).

    Raises:
        FileNotFoundError: If *path* does not exist.
        KeyError: If required columns are not found.

    Example::

        >>> data = read_obs_discharge("station_daily.csv")
        >>> data['dates'].shape == data['discharge'].shape
        True
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Observation file not found: {path}")

    dates_list: list = []
    q_list: list = []

    with open(path, "r", encoding="utf-8-sig") as f:
        # Sniff the delimiter
        sample = f.read(4096)
        f.seek(0)
        if "\t" in sample and sep == ",":
            sep = "\t"

        reader = csv.DictReader(f, delimiter=sep)
        # Normalise header names to lowercase
        if reader.fieldnames is None:
            raise KeyError("File has no header row.")

        col_map = {col.strip().lower(): col for col in reader.fieldnames}
        date_key = col_map.get(date_col.lower())
        q_key = col_map.get(discharge_col.lower())

        # Try common aliases
        if date_key is None:
            for alias in ("date", "time", "datetime", "day"):
                if alias in col_map:
                    date_key = col_map[alias]
                    break
        if q_key is None:
            for alias in ("discharge", "q", "flow", "streamflow", "q_m3s"):
                if alias in col_map:
                    q_key = col_map[alias]
                    break

        if date_key is None or q_key is None:
            raise KeyError(
                f"Required columns not found. Available: {list(col_map.keys())}. "
                f"Looking for date='{date_col}', discharge='{discharge_col}'."
            )

        for row in reader:
            try:
                dt = parse_date_flexible(row[date_key])
                q_val = float(row[q_key])
                dates_list.append(np.datetime64(dt))
                q_list.append(q_val)
            except (ValueError, TypeError):
                continue

    return {
        "dates": np.array(dates_list, dtype="datetime64[D]"),
        "discharge": np.array(q_list, dtype=np.float64),
    }


# ---------------------------------------------------------------------------
# FLUXNET site reader
# ---------------------------------------------------------------------------

_FLUXNET_COL_MAP = {
    "GPP": ["GPP_NT_VUT_REF", "GPP_DT_VUT_REF", "GPP_NT_CUT_REF"],
    "NEE": ["NEE_VUT_REF", "NEE_CUT_REF", "NEE_VUT_MEAN"],
    "LE": ["LE_F_MDS", "LE_CORR"],
    "H": ["H_F_MDS", "H_CORR"],
    "RECO": ["RECO_NT_VUT_REF", "RECO_DT_VUT_REF"],
    "SW_IN": ["SW_IN_F_MDS", "SW_IN_F"],
    "TA": ["TA_F_MDS", "TA_F"],
    "P": ["P_F", "P"],
    "VPD": ["VPD_F_MDS", "VPD_F"],
}


def read_fluxnet_site(
    path: str,
    variables: Optional[List[str]] = None,
) -> Dict[str, np.ndarray]:
    """Read a FLUXNET site CSV file into a standardised dictionary.

    Handles common column name variations across FLUXNET2015 products.
    Missing-data sentinel values (-9999) are replaced with NaN.

    Args:
        path: Path to the FLUXNET CSV file.
        variables: List of variable short names to extract (e.g.
            ``['GPP', 'NEE', 'LE', 'H']``). Default extracts all known
            variables present in the file.

    Returns:
        Dict mapping variable names to numpy float64 arrays. Always includes
        a ``'dates'`` key with numpy datetime64 values, and a
        ``'TIMESTAMP_START'`` key with raw timestamp strings.

    Raises:
        FileNotFoundError: If *path* does not exist.

    Example::

        >>> data = read_fluxnet_site("FLX_US-Ha1_DD.csv", variables=['GPP', 'NEE'])
        >>> 'GPP' in data and 'NEE' in data
        True
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"FLUXNET file not found: {path}")

    if variables is None:
        variables = list(_FLUXNET_COL_MAP.keys())

    result: Dict[str, list] = {v: [] for v in variables}
    dates_list: list = []
    timestamps_list: list = []

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return {"dates": np.array([], dtype="datetime64[D]")}

        available = set(reader.fieldnames)

        # Resolve actual column names
        col_resolve: Dict[str, Optional[str]] = {}
        for var in variables:
            col_resolve[var] = None
            candidates = _FLUXNET_COL_MAP.get(var, [var])
            for cand in candidates:
                if cand in available:
                    col_resolve[var] = cand
                    break

        # Detect timestamp column
        ts_col = None
        for cand in ("TIMESTAMP_START", "TIMESTAMP", "Date", "date"):
            if cand in available:
                ts_col = cand
                break

        for row in reader:
            # Parse timestamp
            ts_str = row.get(ts_col, "") if ts_col else ""
            timestamps_list.append(ts_str)
            try:
                dt = parse_date_flexible(ts_str)
                dates_list.append(np.datetime64(dt, "D"))
            except ValueError:
                dates_list.append(np.datetime64("NaT"))

            # Extract variables
            for var in variables:
                col = col_resolve[var]
                if col is None:
                    result[var].append(float("nan"))
                    continue
                raw = row.get(col, "")
                try:
                    val = float(raw)
                    # FLUXNET sentinel
                    if val == -9999.0 or val == -9999:
                        val = float("nan")
                    result[var].append(val)
                except (ValueError, TypeError):
                    result[var].append(float("nan"))

    output: Dict[str, np.ndarray] = {
        "dates": np.array(dates_list, dtype="datetime64[D]"),
        "TIMESTAMP_START": np.array(timestamps_list),
    }
    for var in variables:
        output[var] = np.array(result[var], dtype=np.float64)

    return output
