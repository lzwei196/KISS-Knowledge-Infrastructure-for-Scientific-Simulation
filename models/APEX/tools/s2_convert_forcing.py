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

import importlib.util

import numpy as np
import pandas as pd

# Make ki_tools_common importable
_KDT = Path("/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent")
if str(_KDT) not in sys.path:
    sys.path.insert(0, str(_KDT))

try:
    from ki_tools_common.load_forcing import load_daily_forcing  # noqa: E402
    from ki_tools_common.humidity import specific_humidity_to_rh  # noqa: E402
    _KI_AVAILABLE = True
except Exception:
    _KI_AVAILABLE = False
    load_daily_forcing = None
    specific_humidity_to_rh = None


def _load_cmfd_direct(lat: float, lon: float, year1: int, year2: int,
                       forcing_dir: str | None = None) -> dict:
    """Load CMFD 3-hourly data for a single point via direct netcdf_utils import.

    Bypasses ki_tools_common/__init__.py (which has a numpy ABI incompatibility)
    by loading netcdf_utils.py directly with importlib.util.
    """
    _netcdf_path = _KDT / "ki_tools_common" / "netcdf_utils.py"
    spec = importlib.util.spec_from_file_location("_nc_utils_direct", str(_netcdf_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _CMFD_3HR = "/media/server/hc_ssd/forcing/Data_forcing_03hr_010deg"
    fdir = forcing_dir or _CMFD_3HR
    return mod.load_cmfd_daily_all(fdir, lat, lon, year1, year2)


def _shum_to_rh(q: np.ndarray, temp_k: np.ndarray, pres_pa: np.ndarray) -> np.ndarray:
    """Inline specific humidity → RH conversion (fraction 0-1)."""
    _eps = 0.622
    temp_c = temp_k - 273.15
    # Tetens saturation vapour pressure (hPa)
    es_hpa = 6.1078 * np.exp(17.269 * temp_c / (temp_c + 237.3))
    es_pa = es_hpa * 100.0
    e_pa = q * pres_pa / (_eps + q * (1.0 - _eps))
    return np.clip(e_pa / es_pa, 0.0, 1.0)  # already fraction 0-1

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


# --- Weather-file target resolution ------------------------------------------
# The shipped APEX0806 ex1_RiselTX template selects weather stations by EXPLICIT
# ID, not by the WEATHER01/WPM01/WIND01 names the legacy (Marena/v1501) tooling
# assumed:
#   * daily  : SUB file (first subarea) line 2, column 8  -> WDLSTCOM.DAT id -> *.DLY
#   * monthly: APEXRUN.DAT first run row, IWP1 token       -> WPM1.DAT id     -> *.WP1
#   * wind   : APEXRUN.DAT first run row, IWND token       -> WIND.DAT id     -> *.WND
# We must OVERWRITE those referenced files in place (SKILL.md: "modify the
# template in place, never write from scratch") rather than emit WEATHER01.* the
# model never reads. _resolve_weather_targets returns the real filenames; a
# legacy fallback keeps the old WEATHER01 layout working.

def _read_list_map(path: Path) -> dict:
    """Parse an APEX list file -> {station_id: filename}."""
    m = {}
    if not path.is_file():
        return m
    for ln in path.read_text(errors="ignore").splitlines():
        toks = ln.split()
        if len(toks) >= 2 and toks[0].lstrip("-").isdigit():
            m[int(toks[0])] = toks[1]
    return m


def _first_run_tokens(run_path: Path):
    """Return whitespace tokens of the first real (non-XXXX) APEXRUN.DAT row."""
    if not run_path.is_file():
        return None
    for ln in run_path.read_text(errors="ignore").splitlines():
        t = ln.split()
        if len(t) >= 4 and not t[0].startswith("XXXX"):
            return t
    return None


def _resolve_weather_targets(ws: Path) -> dict:
    """Resolve the daily/WP1/WND filenames APEX will actually read for run 1.

    Returns {'daily': str, 'wp1': str, 'wnd': str, 'mode': 'com'|'legacy'}.
    """
    run = ws / "APEXRUN.DAT"
    wpm1, wind, wdls = ws / "WPM1.DAT", ws / "WIND.DAT", ws / "WDLSTCOM.DAT"
    suba = ws / "SUBACOM.DAT"
    toks = _first_run_tokens(run)
    if toks and wpm1.is_file() and wind.is_file():
        try:
            iwp1, iwnd = int(toks[2]), int(toks[3])
            wp1_file = _read_list_map(wpm1).get(iwp1)
            wnd_file = _read_list_map(wind).get(iwnd)
            daily_file = None
            if suba.is_file() and wdls.is_file():
                first_sub = None
                for ln in suba.read_text(errors="ignore").splitlines():
                    s = ln.split()
                    if len(s) >= 2 and s[0].isdigit():
                        first_sub = s[1]
                        break
                if first_sub and (ws / first_sub).is_file():
                    sub_lines = (ws / first_sub).read_text(errors="ignore").splitlines()
                    if len(sub_lines) >= 2:
                        s2toks = sub_lines[1].split()
                        if len(s2toks) >= 8 and s2toks[7].lstrip("-").isdigit():
                            daily_file = _read_list_map(wdls).get(int(s2toks[7]))
            if wp1_file and wnd_file and daily_file:
                return {"daily": daily_file, "wp1": wp1_file,
                        "wnd": wnd_file, "mode": "com"}
        except (ValueError, IndexError):
            pass
    return {"daily": DLY_NAME, "wp1": WP1_NAME, "wnd": WND_NAME, "mode": "legacy"}


def _case_variants(ws: Path, fname: str) -> list:
    """Workspace paths for a filename in original, UPPER-ext and lower-ext case."""
    stem, _dot, ext = fname.rpartition(".")
    if not stem:  # no extension
        return [ws / fname]
    names = {fname, f"{stem}.{ext.upper()}", f"{stem}.{ext.lower()}"}
    return [ws / n for n in names]


def validate_inputs(workspace: Path, lat: float, lon: float, year1: int, year2: int) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace does not exist: {workspace}")
    tgt = _resolve_weather_targets(workspace)
    # The WP1 and WND skeletons must exist (we read them for the fixed-width
    # format); the daily file is fully regenerated so it need not pre-exist.
    for key in ("wp1", "wnd"):
        if not (workspace / tgt[key]).is_file():
            raise FileNotFoundError(
                f"Required weather template file missing in workspace: "
                f"{tgt[key]} (resolved {key}, mode={tgt['mode']})"
            )
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
        if specific_humidity_to_rh is not None:
            rh_pct = specific_humidity_to_rh(_to_array(q), tmean_c + 273.15, _to_array(pres))
            rh_frac = np.clip(_to_array(rh_pct) / 100.0, 0.0, 1.0)
        else:
            rh_frac = _shum_to_rh(_to_array(q), tmean_c + 273.15, _to_array(pres))
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
    # F6.1 (not F6.2): values ≤ 999.9 always have ≥1 leading space, preventing
    # concatenation in Fortran list-directed reads (e.g. "46.63101.92" → " 46.6 101.9")
    return "".join(f"{v:6.1f}" for v in values) + "\n"


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

    # Rainfall statistics APEX expects in the *.WP1 rows (Manual §2.13):
    #   RMO  monthly precip (mm)          SDRF std-dev of daily rain (wet days)
    #   SKRF skew coef of daily rain      PRW1 P(wet | previous day dry)
    #   PRW2 P(wet | previous day wet)    WI   mean number of rain days / month
    # Pre-2026-08-09 this function wrote ZEROS into the SDRF and SKRF rows and
    # put the rain-day COUNT (5-20) into the PRW1 row, whose valid range is
    # [0,1] — the rows were shifted two slots relative to the file spec.
    wet = prcp >= 0.1
    prev_wet = np.concatenate(([False], wet[:-1]))
    prcp_total = np.zeros(12)
    rain_days = np.zeros(12)
    rain_sd = np.zeros(12)
    rain_skew = np.zeros(12)
    prw1 = np.zeros(12)
    prw2 = np.zeros(12)
    for m in range(1, 13):
        msel = months == m
        sel = prcp[msel]
        if not sel.size:
            continue
        n_years = max(1, len(set(int(y) for y in years[msel])))
        prcp_total[m - 1] = float(np.nansum(sel)) / n_years
        w = wet[msel]
        rain_days[m - 1] = float(np.sum(w)) / n_years
        wetvals = sel[w]
        if wetvals.size > 1:
            sd = float(np.nanstd(wetvals, ddof=1))
            rain_sd[m - 1] = sd
            if sd > 0:
                rain_skew[m - 1] = float(
                    np.nanmean(((wetvals - np.nanmean(wetvals)) / sd) ** 3))
        pw = prev_wet[msel]
        n_after_dry = int(np.sum(~pw))
        n_after_wet = int(np.sum(pw))
        if n_after_dry:
            prw1[m - 1] = float(np.sum(w & ~pw)) / n_after_dry
        if n_after_wet:
            prw2[m - 1] = float(np.sum(w & pw)) / n_after_wet

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
    template[6] = _format_12(prcp_total).rstrip("\n")           # RMO
    template[7] = _format_12(rain_sd).rstrip("\n")              # SDRF
    template[8] = _format_12(rain_skew).rstrip("\n")            # SKRF
    template[9] = _format_12(np.clip(prw1, 0.0, 1.0)).rstrip("\n")   # PRW1
    template[10] = _format_12(np.clip(prw2, 0.0, 1.0)).rstrip("\n")  # PRW2
    template[11] = _format_12(np.maximum(rain_days, 0.1)).rstrip("\n")  # WI
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
        # Always write both cases — APEX on Linux is case-sensitive
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


def _load_year_cached(source: str, lat: float, lon: float, year: int,
                      cache_dir: Path, forcing_dir: str | None,
                      loader) -> dict:
    """Load ONE year of forcing, memoised to ``cache_dir`` as a .npz.

    A multi-decade point build off the CMFD 3-hourly store costs ~150 s/year
    (12 monthly NetCDFs x 7 variables), i.e. ~2.5 h for 1961-2016.  Without a
    per-year cache any crash, timeout, or relaunch of a long detached run
    re-reads the whole archive from scratch.  Dates are stored as ISO strings,
    which ``_norm_dates`` already accepts.
    """
    import numpy as np
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / f"{source}_{lat:.4f}_{lon:.4f}_{year}.npz"
    if f.is_file():
        try:
            z = np.load(f, allow_pickle=False)
            return {k: z[k] for k in z.files}
        except Exception as exc:  # corrupt/partial cache -> refetch
            print(f"  WARN: forcing cache {f.name} unreadable ({exc!r}); refetching")
    d = loader(source, lat, lon, year, year, forcing_dir=forcing_dir)
    if not d or "dates" not in d or len(d["dates"]) == 0:
        raise RuntimeError(f"empty forcing for {source} {lat},{lon} {year}")
    store = {}
    for k, v in d.items():
        if k == "dates":
            store[k] = np.array([str(x)[:10] for x in v])
        else:
            store[k] = np.asarray(v, dtype=float)
    # NOTE: np.savez_compressed(path) appends ".npz" unless the name already
    # ends in it, so write through a file handle to keep the temp name exact.
    tmp = f.with_name(f.name + ".tmp")
    with open(tmp, "wb") as fh:
        np.savez_compressed(fh, **store)
    os.replace(tmp, f)          # atomic: never leave a half-written cache file
    return store


def build_forcing(workspace, *, lat: float, lon: float,
                  year1: int, year2: int,
                  source: str = "nasa_power",
                  forcing_dir: str | None = None,
                  elev_m: float = 0.0,
                  cache_dir: str | None = None) -> Path:
    ws = Path(workspace).expanduser().resolve()
    validate_inputs(ws, lat, lon, year1, year2)

    if cache_dir is not None:
        import numpy as np
        loader = load_daily_forcing if _KI_AVAILABLE else None
        if loader is None:
            raise RuntimeError("cache_dir requires ki_tools_common.load_forcing")
        per_year = []
        for y in range(year1, year2 + 1):
            per_year.append(_load_year_cached(source, lat, lon, y,
                                              Path(cache_dir), forcing_dir, loader))
            print(f"  forcing {y} ready ({len(per_year[-1]['dates'])} days)", flush=True)
        keys = set(per_year[0])
        for d in per_year[1:]:
            keys &= set(d)
        data = {k: np.concatenate([d[k] for d in per_year]) for k in keys}
    elif source == "cmfd" and not _KI_AVAILABLE:
        print(f"  INFO: ki_tools_common unavailable — using direct CMFD loader")
        data = _load_cmfd_direct(lat, lon, year1, year2, forcing_dir=forcing_dir)
    elif not _KI_AVAILABLE:
        raise RuntimeError(
            f"ki_tools_common is not importable and source='{source}' requires it. "
            f"Switch to --source cmfd (China) or ensure ki_tools_common works."
        )
    else:
        try:
            data = load_daily_forcing(source, lat, lon, year1, year2, forcing_dir=forcing_dir)
        except (ImportError, Exception) as exc:
            if source == "cmfd":
                print(f"  WARN: ki_tools_common CMFD loader failed ({exc!r}); using direct loader")
                data = _load_cmfd_direct(lat, lon, year1, year2, forcing_dir=forcing_dir)
            else:
                raise
    if not data or "dates" not in data or len(data["dates"]) == 0:
        raise RuntimeError(
            f"load_daily_forcing returned empty result for source={source} "
            f"lat={lat} lon={lon} {year1}-{year2}"
        )

    tgt = _resolve_weather_targets(ws)

    # DLY is fully regenerated from forcing; WP1/WND reuse the resolved file as
    # the fixed-width skeleton and overwrite the monthly-statistic rows.
    dly_text = _write_dly_text(data)
    for p in _case_variants(ws, tgt["daily"]):
        p.write_text(dly_text)

    wp1_text = _build_wp1_text(ws / tgt["wp1"], data, lat, lon, elev_m)
    for p in _case_variants(ws, tgt["wp1"]):
        p.write_text(wp1_text)

    wnd_text = _build_wnd_text(ws / tgt["wnd"], data)
    for p in _case_variants(ws, tgt["wnd"]):
        p.write_text(wnd_text)

    if tgt["mode"] == "legacy":
        # Legacy (Marena/v1501) template selects stations by nearest-neighbour,
        # so point the LIST files at our single freshly-written station.
        _rewrite_station_lists(ws, lat, lon, elev_m)
    # COM mode (APEX0806) selects by explicit ID in APEXRUN.DAT / SUB col 8, so
    # the in-place file overwrite above is sufficient — no list rewrite needed.

    validate_outputs(ws, year1, year2, daily_name=tgt["daily"])
    return ws / tgt["daily"]


def validate_outputs(ws: Path, year1: int, year2: int, daily_name: str = DLY_NAME) -> None:
    dly = ws / daily_name
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
    # All case variants of each weather file must match byte-for-byte
    # (otherwise APEX may read a stale alternate-case copy).
    for fname in (daily_name,):
        variants = [p for p in _case_variants(ws, fname) if p.is_file()]
        for v in variants[1:]:
            if v.read_bytes() != variants[0].read_bytes():
                raise RuntimeError(
                    f"Case-mismatch write failed: {variants[0].name} and {v.name} differ"
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
    p.add_argument("--cache-dir", default=None,
                   help="Memoise each year of forcing as a .npz here so a long "
                        "multi-decade build resumes instead of restarting")
    args = p.parse_args()
    out = build_forcing(args.workspace, lat=args.lat, lon=args.lon,
                        year1=args.year1, year2=args.year2,
                        source=args.source, forcing_dir=args.forcing_dir,
                        elev_m=args.elev, cache_dir=args.cache_dir)
    print(f"[OK] forcing written to {out}")
