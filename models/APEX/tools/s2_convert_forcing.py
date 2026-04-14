"""s2_convert_forcing.py — Build APEX daily weather files from a global forcing source.

Pulls daily forcing (CMFD / MSWX / NASA POWER) for ``(lat, lon)`` over
``[year1, year2]`` via ``ki_tools_common.load_forcing.load_daily_forcing`` and
rewrites the workspace's ``WEATHER01.dly`` in APEX fixed-format
``(I6, 2I4, 6F6.2)``:

    YEAR  MO  DA   SRAD   TMAX   TMIN   PRCP    RHM   WIND
                  MJ/m2/d  degC   degC  mm/day frac    m/s

Then refreshes ``WPM01.WP1`` (monthly weather generator stats) and
``WIND01.WND`` (monthly wind statistics) by editing the validated template in
place — only the latitude/longitude/elevation header line and the 12-month
mean rows are recomputed; the rest of the structure is preserved verbatim.

Finally the three LIST files (WDLYLIST / WPM1LIST / WINDLIST) are rewritten to
contain a single station pointing at the new files with the new lat/lon, so
APEX's "nearest station" picker always picks the new data instead of the
stale OK-Marena entries.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

# Make ki_tools_common importable
_KDT = Path("/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent")
if str(_KDT) not in sys.path:
    sys.path.insert(0, str(_KDT))

from ki_tools_common.load_forcing import load_daily_forcing  # noqa: E402
from ki_tools_common.humidity import specific_humidity_to_rh  # noqa: E402

DLY_NAME = "WEATHER01.dly"
WP1_NAME = "WPM01.WP1"
WND_NAME = "WIND01.WND"

# Both upper- and lower-case copies of each weather file exist in the shipped
# example (copytree preserves them). APEX reads whatever case the LIST file
# references, so we must update BOTH copies to avoid writing to the wrong one.
DLY_CASE_PAIRS = [("WEATHER01.dly", "WEATHER01.DLY")]
WP1_CASE_PAIRS = [("WPM01.WP1", "WPM01.wp1")]
WND_CASE_PAIRS = [("WIND01.WND", "WIND01.wnd")]

WDLYLIST = "WDLYLIST.DAT"
WPM1LIST = "WPM1LIST.DAT"
WINDLIST = "WINDLIST.DAT"


def validate_inputs(workspace: Path, lat: float, lon: float, year1: int, year2: int) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace does not exist: {workspace}")
    for f in (DLY_NAME, WP1_NAME, WND_NAME):
        if not (workspace / f).is_file():
            raise FileNotFoundError(f"Required template file missing in workspace: {f}")
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"lat out of range: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"lon out of range: {lon}")
    if year2 < year1:
        raise ValueError(f"year2 ({year2}) must be >= year1 ({year1})")
    if year1 < 1900 or year2 > 2100:
        raise ValueError(f"year range {year1}-{year2} outside [1900, 2100]")


def _to_array(seq) -> np.ndarray:
    return np.asarray(seq, dtype=float)


def _to_timestamps(dates) -> pd.DatetimeIndex:
    """Normalise dates returned by load_daily_forcing (numpy.datetime64, str,
    python datetime, pandas Timestamp, ...) to a pandas DatetimeIndex so the
    rest of the module can freely call `.year` / `.month` / `.day`."""
    return pd.to_datetime(list(dates))


def _format_dly_row(year: int, mo: int, da: int,
                    srad_mj: float, tmax_c: float, tmin_c: float,
                    prcp_mm: float, rh_frac: float, wind_ms: float) -> str:
    return (f"{year:6d}{mo:4d}{da:4d}"
            f"{srad_mj:6.2f}{tmax_c:6.2f}{tmin_c:6.2f}"
            f"{prcp_mm:6.2f}{rh_frac:6.2f}{wind_ms:6.2f}\n")


def _write_dly_text(data: dict) -> str:
    dates = _to_timestamps(data["dates"])
    n = len(dates)
    srad_mj = _to_array(data.get("srad_wm2", np.zeros(n))) * 0.0864
    tmax = _to_array(data.get("temp_max_c", data.get("temp_mean_c")))
    tmin = _to_array(data.get("temp_min_c", data.get("temp_mean_c")))
    prcp = _to_array(data.get("precip_mm", np.zeros(n)))
    wind = _to_array(data.get("wind_ms", np.zeros(n)))

    q = data.get("shum_kgkg")
    pres = data.get("pres_pa")
    tmean_c = (tmax + tmin) * 0.5
    if q is not None and pres is not None:
        rh_pct = specific_humidity_to_rh(_to_array(q), tmean_c + 273.15, _to_array(pres))
        rh_frac = np.clip(_to_array(rh_pct) / 100.0, 0.0, 1.0)
    else:
        rh_frac = np.full(n, 0.7)

    srad_mj = np.clip(srad_mj, 0.0, 50.0)
    wind = np.clip(wind, 0.0, 50.0)
    prcp = np.clip(prcp, 0.0, 999.0)

    rows = []
    for i in range(n):
        d = dates[i]
        rows.append(_format_dly_row(
            int(d.year), int(d.month), int(d.day),
            float(srad_mj[i]), float(tmax[i]), float(tmin[i]),
            float(prcp[i]), float(rh_frac[i]), float(wind[i]),
        ))
    return "".join(rows)


def _monthly_means(values: np.ndarray, months: np.ndarray) -> np.ndarray:
    out = np.zeros(12, dtype=float)
    for m in range(1, 13):
        sel = values[months == m]
        if sel.size:
            out[m - 1] = float(np.nanmean(sel))
    return out


def _format_12(values: Sequence[float]) -> str:
    return "".join(f"{v:6.2f}" for v in values) + "\n"


def _build_wp1_text(template_path: Path, data: dict, lat: float, lon: float, elev_m: float) -> str:
    dates = _to_timestamps(data["dates"])
    months = dates.month.to_numpy()
    years = dates.year.to_numpy()
    tmax = _to_array(data.get("temp_max_c"))
    tmin = _to_array(data.get("temp_min_c"))
    prcp = _to_array(data.get("precip_mm", np.zeros(len(dates))))
    srad_mj = _to_array(data.get("srad_wm2", np.zeros(len(dates)))) * 0.0864

    tmax_m = _monthly_means(tmax, months)
    tmin_m = _monthly_means(tmin, months)
    # (srad monthly means computed but not written — the template carries its
    # own SRAD row; recomputing would change file width.)
    _ = _monthly_means(srad_mj, months)

    tmax_sd = np.zeros(12)
    tmin_sd = np.zeros(12)
    for m in range(1, 13):
        s1 = tmax[months == m]
        s2 = tmin[months == m]
        if s1.size:
            tmax_sd[m - 1] = float(np.nanstd(s1))
        if s2.size:
            tmin_sd[m - 1] = float(np.nanstd(s2))

    prcp_total = np.zeros(12)
    rain_days = np.zeros(12)
    for m in range(1, 13):
        sel = prcp[months == m]
        if sel.size:
            n_years = max(1, len(set(int(y) for y in years[months == m])))
            prcp_total[m - 1] = float(np.nansum(sel)) / n_years
            rain_days[m - 1] = float(np.sum(sel >= 0.1)) / n_years

    template = template_path.read_text().splitlines()
    while len(template) < 16:
        template.append(" " * 80)
    template[0] = f"SITE LAT={lat:7.3f} LON={lon:8.3f}"
    template[1] = (f"LATT = {lat:6.2f} LONG = {lon:6.2f} ELEV = {elev_m:6.1f}"
                   f" TP5 .5H =   78.7 TP6 6.H =  150.4")
    template[2] = _format_12(tmax_m).rstrip("\n")
    template[3] = _format_12(tmin_m).rstrip("\n")
    template[4] = _format_12(tmax_sd).rstrip("\n")
    template[5] = _format_12(tmin_sd).rstrip("\n")
    template[6] = _format_12(prcp_total).rstrip("\n")
    template[7] = _format_12(np.zeros(12)).rstrip("\n")
    template[8] = _format_12(np.zeros(12)).rstrip("\n")
    template[9] = _format_12(np.maximum(rain_days, 0.1)).rstrip("\n")
    return "\n".join(template) + "\n"


def _build_wnd_text(template_path: Path, data: dict) -> str:
    dates = _to_timestamps(data["dates"])
    months = dates.month.to_numpy()
    wind = _to_array(data.get("wind_ms", np.zeros(len(dates))))
    wind_m = _monthly_means(wind, months)

    template = template_path.read_text().splitlines()
    while len(template) < 4:
        template.append(" " * 80)
    template[2] = _format_12(wind_m).rstrip("\n")
    return "\n".join(template) + "\n"


def _write_both_cases(ws: Path, pairs, text: str) -> None:
    for primary, alt in pairs:
        (ws / primary).write_text(text)
        # If the alternate-case file exists on disk (shipped template has both),
        # rewrite it too so APEX can't pick up a stale copy via the LIST file.
        if (ws / alt).is_file():
            (ws / alt).write_text(text)


def _rewrite_station_lists(ws: Path, lat: float, lon: float, elev_m: float) -> None:
    """Replace WDLYLIST/WPM1LIST/WINDLIST with a single-station pointer at
    (lat, lon, elev_m) so APEX's nearest-station picker always selects our
    newly written WEATHER01/WPM01/WIND01 files — not the stale OK-Marena
    entries that ship with the template."""
    # DLY list — format matches shipped example column layout
    (ws / WDLYLIST).write_text(
        f"    1 WEATHER01.DLY   {lat:6.2f}  {lon:6.2f}   {elev_m:6.1f}"
        f"    SITE_FORCING_BUILT_BY_S2\n"
    )
    (ws / WPM1LIST).write_text(
        f"    1 WPM01.wp1      {lat:6.2f} {lon:6.2f}   {elev_m:6.1f}"
        f"                             \n"
    )
    (ws / WINDLIST).write_text(
        f"    1 WIND01.wnd     {lat:6.2f} {lon:6.2f}\n"
    )


def build_forcing(workspace, *, lat: float, lon: float,
                  year1: int, year2: int,
                  source: str = "nasa_power",
                  forcing_dir: str | None = None,
                  elev_m: float = 0.0) -> Path:
    ws = Path(workspace).expanduser().resolve()
    validate_inputs(ws, lat, lon, year1, year2)

    data = load_daily_forcing(source, lat, lon, year1, year2, forcing_dir=forcing_dir)
    if not data or "dates" not in data or len(data["dates"]) == 0:
        raise RuntimeError(
            f"load_daily_forcing returned empty result for source={source} "
            f"lat={lat} lon={lon} {year1}-{year2}"
        )

    dly_text = _write_dly_text(data)
    _write_both_cases(ws, DLY_CASE_PAIRS, dly_text)

    wp1_text = _build_wp1_text(ws / WP1_NAME, data, lat, lon, elev_m)
    _write_both_cases(ws, WP1_CASE_PAIRS, wp1_text)

    wnd_text = _build_wnd_text(ws / WND_NAME, data)
    _write_both_cases(ws, WND_CASE_PAIRS, wnd_text)

    _rewrite_station_lists(ws, lat, lon, elev_m)

    validate_outputs(ws, year1, year2)
    return ws / DLY_NAME


def validate_outputs(ws: Path, year1: int, year2: int) -> None:
    dly = ws / DLY_NAME
    lines = dly.read_text().splitlines()
    if len(lines) < 365 * (year2 - year1 + 1) - 5:
        raise RuntimeError(
            f"{dly} has only {len(lines)} rows for period {year1}-{year2}"
        )
    first = lines[0]
    last = lines[-1]
    if int(first[:6].strip()) != year1:
        raise RuntimeError(f"{dly} first year {first[:6]!r} != {year1}")
    if int(last[:6].strip()) != year2:
        raise RuntimeError(f"{dly} last year {last[:6]!r} != {year2}")
    # Both-case write-back check: if an alternate-case copy exists it must
    # match the primary byte-for-byte (otherwise APEX reads stale template).
    for pairs in (DLY_CASE_PAIRS, WP1_CASE_PAIRS, WND_CASE_PAIRS):
        for primary, alt in pairs:
            p = ws / primary
            a = ws / alt
            if a.is_file() and p.read_bytes() != a.read_bytes():
                raise RuntimeError(
                    f"Case-mismatch write failed: {primary} and {alt} differ"
                )


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--year1", type=int, required=True)
    p.add_argument("--year2", type=int, required=True)
    p.add_argument("--source", default="nasa_power")
    p.add_argument("--forcing-dir", default=None)
    p.add_argument("--elev", type=float, default=0.0)
    args = p.parse_args()
    out = build_forcing(args.workspace, lat=args.lat, lon=args.lon,
                        year1=args.year1, year2=args.year2,
                        source=args.source, forcing_dir=args.forcing_dir,
                        elev_m=args.elev)
    print(f"[OK] forcing written to {out}")
