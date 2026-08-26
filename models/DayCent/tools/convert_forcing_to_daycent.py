#!/usr/bin/env python3
"""
convert_forcing_to_daycent.py — Build a DayCent .wth weather file from
CMFD / MSWX / NASA-POWER / FLUXNET daily forcing.

DayCent .wth column layout (no header, whitespace-delimited):
    1: day-of-month   (int)
    2: month          (int 1..12)
    3: year           (int 4-digit)
    4: day-of-year    (int 1..366)
    5: Tmin           (°C)
    6: Tmax           (°C)
    7: precipitation  (cm/day)   <-- NOT mm/day; divide by 10

Optional columns 8/9 (only used when sitepar.in `usexdrvrs=1`):
    8: solar radiation (langleys/day = 41.84 kJ m-2)
    9: relative humidity (%)

Sources supported:
  cmfd       — CMFD 0.1°/3hr gridded forcing (China domain only — do NOT use
               outside China; DE-Tha, US sites etc. will silently produce
               FileNotFoundError or nonsense values)
  mswx       — MSWX 0.1°/3hr global (only if MSWX is actually deployed on this
               host; default path differs from CMFD)
  nasa_power — NASA POWER REST API (global; requires network reach to
               power.larc.nasa.gov — not available when host firewall blocks
               NASA, use fluxnet source instead)
  fluxnet    — FLUXNET2015 FULLSET_DD.csv (daily file for a single eddy-cov
               site; works offline; preferred when validating DayCent against
               eddy-covariance GPP/NEE at a FLUXNET tower)

Usage:
    # gridded sources
    python convert_forcing_to_daycent.py \
        --source cmfd --lat 40.78 --lon -81.93 \
        --year-start 1981 --year-end 2010 \
        --out wooster_prism.wth

    # FLUXNET site CSV (preferred for FLUXNET validation tasks)
    python convert_forcing_to_daycent.py \
        --source fluxnet \
        --fluxnet-csv KISSPATH_ROOT/.../sites/DE-Tha/FULLSET_DD.csv \
        --year-start 1996 --year-end 2014 \
        --out de_tha.wth
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

# Shared loader — handles CMFD, MSWX, NASA-POWER under one interface.
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
try:
    from ki_tools_common.load_forcing import load_daily_forcing
    from ki_tools_common.validation import validate_forcing_ranges
except ImportError as e:
    print(f"FATAL: could not import ki_tools_common: {e}", file=sys.stderr)
    print("       fix: pip install -e KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/ki_tools_common",
          file=sys.stderr)
    sys.exit(2)


CMFD_DEFAULT = "KISSPATH_FORCING/Data_forcing_03hr_010deg"
MSWX_DEFAULT = "KISSPATH_FORCING"


def validate_inputs(args):
    # lat/lon only required for gridded sources; FLUXNET CSV self-describes.
    if args.source != "fluxnet":
        if args.lat is None or args.lon is None:
            raise ValueError(f"--lat/--lon required for source={args.source}")
        if not (-90.0 <= args.lat <= 90.0):
            raise ValueError(f"lat out of range: {args.lat}")
        if not (-180.0 <= args.lon <= 180.0):
            raise ValueError(f"lon out of range: {args.lon}")
    if args.year_end < args.year_start:
        raise ValueError("year-end before year-start")
    if args.year_end - args.year_start > 200:
        raise ValueError("refusing to build > 200 years of forcing in one shot")
    if args.source == "fluxnet" and not args.fluxnet_csv:
        raise ValueError("--fluxnet-csv is required when --source fluxnet")
    if args.source == "cmfd":
        # CMFD only covers China. Sanity-fence on longitude to catch the
        # common DE-Tha / US-site mistake before we hit a FileNotFoundError.
        if args.lon is not None and not (70.0 <= args.lon <= 140.0):
            raise ValueError(
                f"CMFD domain is China only (roughly 70E-140E). "
                f"Requested lon={args.lon} is outside this window. "
                f"Use --source fluxnet (for FLUXNET towers) or --source nasa_power."
            )


def to_celsius(arr, var_name):
    # CMFD temperature is in K; NASA-POWER may already be in C. Detect by magnitude.
    import numpy as np
    a = np.asarray(arr, dtype=float)
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        raise RuntimeError(f"{var_name}: no finite values")
    if finite.mean() > 150.0:  # almost certainly Kelvin
        return a - 273.15
    return a


def to_cm_day(arr, var_name):
    import numpy as np
    a = np.asarray(arr, dtype=float)
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        raise RuntimeError(f"{var_name}: no finite values")
    # Heuristic: if mean > 0.6 the units are mm/day, divide by 10
    # (humid sites get ~3-5 mm/day mean, arid sites ~1-2 mm/day mean)
    if finite.mean() > 0.6:
        return a / 10.0
    return a  # already cm/day


def _resolve_forcing_keys(forcing):
    """load_daily_forcing returns {temp_min_c, temp_max_c, precip_mm, ...};
    older callers passed {tmin, tmax, prcp}. Accept either."""
    def pick(candidates):
        for k in candidates:
            if k in forcing:
                return forcing[k]
        raise KeyError(f"forcing dict missing any of {candidates} (got {list(forcing)})")

    tmin = pick(("temp_min_c", "tmin", "Tmin"))
    tmax = pick(("temp_max_c", "tmax", "Tmax"))
    prcp = pick(("precip_mm", "prcp", "Prcp", "P"))
    return tmin, tmax, prcp


def load_fluxnet_daily(csv_path, year_start, year_end):
    """Read a FLUXNET2015 FULLSET_DD.csv and return a dict compatible with
    `build_wth`. Uses TA_F (daily mean), with TA_F_NIGHT/TA_F_DAY as Tmin/Tmax
    proxies when available; otherwise falls back to TA_F ± small diurnal offset.
    P_F is mm/day, SW_IN_F is W m-2 daily mean."""
    import csv
    import numpy as np

    MISSING = -9999.0

    def val(row, key):
        v = row.get(key, "")
        if v == "" or v is None:
            return np.nan
        try:
            f = float(v)
        except ValueError:
            return np.nan
        return np.nan if f <= MISSING + 1e-6 else f

    rows_out = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        has_night_day = ("TA_F_NIGHT" in fieldnames) and ("TA_F_DAY" in fieldnames)
        for row in reader:
            ts = row.get("TIMESTAMP", "").strip()
            if len(ts) < 8:
                continue
            y = int(ts[0:4])
            if y < year_start or y > year_end:
                continue
            m = int(ts[4:6])
            d = int(ts[6:8])
            ta = val(row, "TA_F")
            p = val(row, "P_F")
            sw = val(row, "SW_IN_F")
            if has_night_day:
                tn = val(row, "TA_F_NIGHT")
                tx = val(row, "TA_F_DAY")
            else:
                tn = tx = np.nan
            # Fill any missing tmin/tmax from mean with a 4C offset — the
            # best we can do without HH data. If TA_F itself is missing,
            # drop the day (DayCent cannot tolerate NaN in .wth).
            if np.isnan(tn):
                tn = ta - 4.0 if not np.isnan(ta) else np.nan
            if np.isnan(tx):
                tx = ta + 4.0 if not np.isnan(ta) else np.nan
            if np.isnan(tn) or np.isnan(tx):
                # hopeless — skip
                continue
            if np.isnan(p):
                p = 0.0
            rows_out.append((date(y, m, d), tn, tx, p, sw))

    if not rows_out:
        raise RuntimeError(
            f"No usable rows in {csv_path} for {year_start}-{year_end}. "
            f"Check that the file is a FLUXNET2015 FULLSET_DD.csv and that "
            f"the year range overlaps the site record."
        )

    rows_out.sort(key=lambda r: r[0])

    # Fill calendar gaps so .wth is contiguous (DayCent requires contiguous days).
    first_d = rows_out[0][0]
    last_d = rows_out[-1][0]
    by_date = {r[0]: r for r in rows_out}
    filled = []
    cur = first_d
    while cur <= last_d:
        if cur in by_date:
            filled.append(by_date[cur])
        else:
            # carry-forward last good tmin/tmax, zero precip
            prev = filled[-1] if filled else (cur, 0.0, 0.0, 0.0, np.nan)
            filled.append((cur, prev[1], prev[2], 0.0, prev[4]))
        cur += timedelta(days=1)

    dates = np.array([r[0] for r in filled])
    tmin = np.array([r[1] for r in filled], dtype=float)
    tmax = np.array([r[2] for r in filled], dtype=float)
    prcp = np.array([r[3] for r in filled], dtype=float)  # mm/day
    srad = np.array([r[4] for r in filled], dtype=float)  # W/m2
    return {
        "dates": dates,
        "temp_min_c": tmin,
        "temp_max_c": tmax,
        "precip_mm": prcp,
        "srad_wm2": srad,
    }


def build_wth(forcing, year_start, year_end, use_fluxnet_dates=False):
    """Convert a loader-style dict to DayCent .wth rows.

    Accepts both the ki_tools_common.load_forcing dict format
    (temp_min_c / temp_max_c / precip_mm) and legacy (tmin / tmax / prcp)."""
    import numpy as np

    tmin_raw, tmax_raw, prcp_raw = _resolve_forcing_keys(forcing)
    tmin = to_celsius(tmin_raw, "tmin")
    tmax = to_celsius(tmax_raw, "tmax")
    prcp = to_cm_day(prcp_raw, "prcp")

    rows = []
    if use_fluxnet_dates and "dates" in forcing:
        dts = forcing["dates"]
        n = min(len(dts), len(tmin), len(tmax), len(prcp))
        for i in range(n):
            d = dts[i]
            doy = d.timetuple().tm_yday
            rows.append((d.day, d.month, d.year, doy,
                         float(tmin[i]), float(tmax[i]), float(prcp[i])))
        return rows

    n_days_expected = sum(366 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 365
                          for y in range(year_start, year_end + 1))
    if len(tmin) != n_days_expected:
        print(f"WARN: expected {n_days_expected} days, got {len(tmin)} — using min")
    n = min(len(tmin), len(tmax), len(prcp), n_days_expected)

    d = date(year_start, 1, 1)
    for i in range(n):
        doy = d.timetuple().tm_yday
        rows.append((d.day, d.month, d.year, doy,
                     float(tmin[i]), float(tmax[i]), float(prcp[i])))
        d += timedelta(days=1)
    return rows


def write_wth(rows, out_path):
    with open(out_path, "w") as f:
        for r in rows:
            # DayCent .wth is whitespace-aligned, not strict columns.
            f.write(f"{r[0]:>3d}\t{r[1]:>3d}\t{r[2]:>4d}\t{r[3]:>3d}"
                    f"\t{r[4]:.2f}\t{r[5]:.2f}\t{r[6]:.4f}\n")


def validate_outputs(rows):
    """Sanity check the .wth before declaring success."""
    if not rows:
        raise RuntimeError("no rows produced")
    n = len(rows)
    mean_tmin = sum(r[4] for r in rows) / n
    mean_tmax = sum(r[5] for r in rows) / n
    mean_prcp_cm = sum(r[6] for r in rows) / n
    annual_prcp_cm = mean_prcp_cm * 365.25

    print(f"  n_days        : {n}")
    print(f"  mean Tmin (C) : {mean_tmin:.2f}")
    print(f"  mean Tmax (C) : {mean_tmax:.2f}")
    print(f"  mean P (cm/d) : {mean_prcp_cm:.4f}")
    print(f"  annual P (cm) : {annual_prcp_cm:.1f}")

    if not (-30.0 < mean_tmin < 30.0):
        raise ValueError(f"mean Tmin {mean_tmin} out of plausible band — unit error?")
    if not (-20.0 < mean_tmax < 45.0):
        raise ValueError(f"mean Tmax {mean_tmax} out of plausible band — unit error?")
    if not (5.0 < annual_prcp_cm < 500.0):
        raise ValueError(
            f"annual precip {annual_prcp_cm:.1f} cm/yr is implausible. "
            f"Most basins are 20–250 cm/yr. Suspect mm vs cm error."
        )
    if mean_tmin > mean_tmax:
        raise ValueError("mean Tmin > mean Tmax — column swap?")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--source", choices=["cmfd", "mswx", "nasa_power", "fluxnet"],
                   default="cmfd")
    p.add_argument("--lat", type=float, default=None,
                   help="site latitude (required for gridded sources)")
    p.add_argument("--lon", type=float, default=None,
                   help="site longitude (required for gridded sources)")
    p.add_argument("--year-start", type=int, required=True)
    p.add_argument("--year-end", type=int, required=True)
    p.add_argument("--forcing-dir", default=None,
                   help="forcing dataset root (defaults to CMFD_DEFAULT for "
                        "cmfd, MSWX_DEFAULT for mswx)")
    p.add_argument("--fluxnet-csv", default=None,
                   help="path to FLUXNET2015 FULLSET_DD.csv "
                        "(required when --source fluxnet)")
    p.add_argument("--out", required=True, help="output .wth path")
    args = p.parse_args(argv)

    validate_inputs(args)

    use_fluxnet_dates = False
    if args.source == "fluxnet":
        print(f"Loading FLUXNET CSV: {args.fluxnet_csv} "
              f"[{args.year_start}-{args.year_end}]")
        forcing = load_fluxnet_daily(args.fluxnet_csv, args.year_start, args.year_end)
        use_fluxnet_dates = True
    elif args.source == "nasa_power":
        print(f"Loading nasa_power for ({args.lat}, {args.lon}) "
              f"{args.year_start}-{args.year_end}")
        forcing = load_daily_forcing("nasa_power", args.lat, args.lon,
                                     args.year_start, args.year_end)
    else:
        forcing_dir = args.forcing_dir
        if forcing_dir is None:
            forcing_dir = CMFD_DEFAULT if args.source == "cmfd" else MSWX_DEFAULT
        print(f"Loading {args.source} for ({args.lat}, {args.lon}) "
              f"{args.year_start}-{args.year_end} from {forcing_dir}")
        forcing = load_daily_forcing(args.source, args.lat, args.lon,
                                     args.year_start, args.year_end,
                                     forcing_dir=forcing_dir)

    try:
        validate_forcing_ranges(forcing)
    except Exception as e:
        print(f"  range-check warn: {e}")

    rows = build_wth(forcing, args.year_start, args.year_end,
                     use_fluxnet_dates=use_fluxnet_dates)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_wth(rows, out)
    print(f"Wrote {out} ({len(rows)} days)")
    validate_outputs(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
