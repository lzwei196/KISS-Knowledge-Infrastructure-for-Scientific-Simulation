#!/usr/bin/env python3
"""
Convert CMFD / MSWX / NASA POWER daily forcing into EPIC `.DLY`, `.WP1`, `.WND`.

Pattern: validate -> load via ki_tools_common -> convert units -> write fixed-width
         Fortran format -> validate ranges.

DLY column layout (epic0810 strict format I6,2I4,6F6.2):
  year(6) month(4) day(4) srad(6.2 MJ/m2/d) tmax(6.2 C) tmin(6.2 C)
  prcp(6.2 mm/d) rh(6.2 frac) ws(6.2 m/s)
"""

import os
import sys
from datetime import datetime, timedelta

import numpy as np

CMFD_PATH = "KISSPATH_DATA/forcing/Data_forcing_03hr_010deg"


def _try_load_forcing(source: str, lat: float, lon: float,
                      year1: int, year2: int) -> dict:
    """
    Use ki_tools_common.load_forcing.load_daily_forcing if available,
    otherwise raise a clear error so the user knows the dependency is missing.
    """
    try:
        from ki_tools_common.load_forcing import load_daily_forcing
    except ImportError as e:
        raise ImportError(
            "ki_tools_common.load_forcing is required. "
            "Add KISSPATH_INTERNAL_NOT_SHIPPED to PYTHONPATH "
            "or install the kdt-release package."
        ) from e

    if source.lower() == "cmfd":
        return load_daily_forcing("cmfd", lat, lon, year1, year2,
                                  forcing_dir=CMFD_PATH)
    return load_daily_forcing(source, lat, lon, year1, year2)


def validate_forcing_dict(data: dict) -> list:
    """Quick sanity check on the input dict."""
    errors = []
    required = {"year", "month", "day", "tmax", "tmin", "prcp", "srad", "rh", "ws"}
    missing = required - set(data.keys())
    if missing:
        errors.append(f"ERROR: missing keys from forcing data: {missing}")
        return errors
    n = len(data["year"])
    for k in ("month", "day", "tmax", "tmin", "prcp", "srad", "rh", "ws"):
        if len(data[k]) != n:
            errors.append(f"ERROR: length mismatch on {k}: {len(data[k])} != {n}")
    # Range checks
    if np.nanmin(data["tmax"]) < -60 or np.nanmax(data["tmax"]) > 60:
        errors.append(f"WARNING: tmax outside [-60,60]: {np.nanmin(data['tmax'])}..{np.nanmax(data['tmax'])}")
    if np.nanmin(data["prcp"]) < 0:
        errors.append(f"ERROR: negative precipitation values present")
    if np.nanmax(data["rh"]) > 1.5:
        errors.append(f"WARNING: rh max > 1.5; should be 0..1 fraction not %")
    if np.nanmax(data["srad"]) > 60:
        errors.append(f"WARNING: srad max > 60 MJ/m2/d (likely W/m2 not converted)")
    return errors


def write_dly(data: dict, dly_path: str, station_name: str = "SITE",
              station_id: int = 1, lat: float = 0.0, lon: float = 0.0,
              elev: float = 0.0) -> None:
    """
    Write data dict to fixed-width EPIC .DLY file.
    Format: I6 + 2I4 + 6F6.2.
    """
    n = len(data["year"])
    with open(dly_path, "w") as f:
        for i in range(n):
            y = int(data["year"][i])
            m = int(data["month"][i])
            d = int(data["day"][i])
            srad = float(data["srad"][i])
            tmax = float(data["tmax"][i])
            tmin = float(data["tmin"][i])
            prcp = float(data["prcp"][i])
            rh = float(data["rh"][i])
            ws = float(data["ws"][i])
            f.write(f"{y:6d}{m:4d}{d:4d}{srad:6.2f}{tmax:6.2f}{tmin:6.2f}"
                    f"{prcp:6.2f}{rh:6.2f}{ws:6.2f}\n")
        last = (datetime(int(data["year"][-1]), int(data["month"][-1]), int(data["day"][-1]))
                .strftime("%Y-%m-%d"))
        f.write(f"STATION = {station_name}  STA ID = {station_id}  STATE = NA  "
                f"CO = NA  LAT = {lat:.2f}  LONG = {lon:.2f}  "
                f"ELEV = {elev:.1f}  Y-M-D {last}\n")


def write_wp1(data: dict, wp1_path: str, station_name: str = "SITE",
              station_id: int = 1, lat: float = 0.0, lon: float = 0.0,
              elev: float = 0.0) -> None:
    """
    Write monthly weather statistics .WP1 from daily data.
    14 stats per month: OBMX OBMN RST2 OBSL RH UAVO SDTMX SDTMN
    RST2_std DAYP RST3 PRW1 PRW2 WI.
    """
    months = np.array(data["month"], dtype=int)
    tmax = np.array(data["tmax"], dtype=float)
    tmin = np.array(data["tmin"], dtype=float)
    prcp = np.array(data["prcp"], dtype=float)
    srad = np.array(data["srad"], dtype=float)
    rh = np.array(data["rh"], dtype=float)
    ws = np.array(data["ws"], dtype=float)

    obmx, obmn, rst2, obsl, rhm, uavo = [], [], [], [], [], []
    sdtmx, sdtmn, rst2s, dayp = [], [], [], []
    rst3, prw1, prw2, wi = [], [], [], []

    for m in range(1, 13):
        mask = months == m
        obmx.append(float(np.nanmean(tmax[mask])) if mask.any() else 0.0)
        obmn.append(float(np.nanmean(tmin[mask])) if mask.any() else 0.0)
        rst2.append(float(np.nansum(prcp[mask]) / max(np.unique(np.array(data["year"])[mask]).size, 1))
                    if mask.any() else 0.0)
        obsl.append(float(np.nanmean(srad[mask])) if mask.any() else 0.0)
        rhm.append(float(np.nanmean(rh[mask])) if mask.any() else 0.0)
        uavo.append(float(np.nanmean(ws[mask])) if mask.any() else 0.0)
        sdtmx.append(float(np.nanstd(tmax[mask])) if mask.any() else 0.0)
        sdtmn.append(float(np.nanstd(tmin[mask])) if mask.any() else 0.0)
        rst2s.append(float(np.nanstd(prcp[mask])) if mask.any() else 0.0)
        wet_days = (prcp[mask] > 0.1).sum() if mask.any() else 0
        dayp.append(float(wet_days))
        rst3.append(0.0)  # skewness (not used by simple sites)
        prw1.append(0.5)  # P(wet|dry)
        prw2.append(0.7)  # P(wet|wet)
        wi.append(0.0)

    rows = [obmx, obmn, rst2, obsl, rhm, uavo, sdtmx, sdtmn,
            rst2s, dayp, rst3, prw1, prw2, wi]

    with open(wp1_path, "w") as f:
        f.write(f"{station_id:5d} {station_name:15s}{lat:7.2f}{lon:8.2f}"
                f"{elev:12.2f}\n")
        for row in rows:
            f.write("".join(f"{v:7.2f}" for v in row) + "\n")


def write_wnd(wnd_path: str, station_name: str = "SITE",
              avg_wind_per_month: list = None) -> None:
    """
    Write a minimal .WND file: 16 wind directions × 12 monthly frequencies
    (uniform), then 12 monthly average wind speeds.
    """
    if avg_wind_per_month is None:
        avg_wind_per_month = [3.0] * 12  # m/s default
    with open(wnd_path, "w") as f:
        f.write(f"{station_name:15s}\n")
        # 16 directions × 12 months -> 16 lines of 12 values
        for d in range(16):
            f.write("".join(f"{1.0/16:7.4f}" for _ in range(12)) + "\n")
        f.write("".join(f"{v:7.2f}" for v in avg_wind_per_month) + "\n")


def convert(source: str, lat: float, lon: float, year1: int, year2: int,
            out_dir: str, station_name: str = "SITE",
            station_id: int = 1, elev: float = 100.0) -> dict:
    """
    Top-level pipeline: load forcing -> validate -> write DLY + WP1 + WND.
    Returns dict with paths and validation messages.
    """
    os.makedirs(out_dir, exist_ok=True)
    data = _try_load_forcing(source, lat, lon, year1, year2)

    errors = validate_forcing_dict(data)
    fatal = [e for e in errors if e.startswith("ERROR")]
    if fatal:
        raise ValueError(f"Forcing validation failed: {fatal}")

    dly_path = os.path.join(out_dir, f"{station_name}.DLY")
    wp1_path = os.path.join(out_dir, f"{station_name}.WP1")
    wnd_path = os.path.join(out_dir, f"{station_name}.WND")

    write_dly(data, dly_path, station_name, station_id, lat, lon, elev)
    write_wp1(data, wp1_path, station_name, station_id, lat, lon, elev)
    write_wnd(wnd_path, station_name)

    return {
        "dly": dly_path,
        "wp1": wp1_path,
        "wnd": wnd_path,
        "n_days": len(data["year"]),
        "warnings": [e for e in errors if e.startswith("WARNING")],
    }


def main():
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="cmfd")
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--year1", type=int, required=True)
    p.add_argument("--year2", type=int, required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--name", default="SITE")
    args = p.parse_args()

    result = convert(args.source, args.lat, args.lon, args.year1, args.year2,
                     args.out_dir, station_name=args.name)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
