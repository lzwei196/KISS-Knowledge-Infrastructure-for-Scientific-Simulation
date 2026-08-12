import os
"""
NASA POWER Forcing Generator for VIC — Online API fallback.

Fetches hourly meteorological data from NASA POWER API and converts
to VIC 3-hourly forcing files. No local datasets required — just
internet access and a basin_grid.nc.

╔══════════════════════════════════════════════════════════════════╗
║  ⚠️  COARSE RESOLUTION WARNING                                 ║
║                                                                  ║
║  NASA POWER provides data at 0.5° (~50 km) for meteorology      ║
║  and 1° (~100 km) for radiation — 5–10× coarser than CMFD/MSWX. ║
║                                                                  ║
║  Recommended ONLY for:                                           ║
║    • Large basins (>10,000 km²)                                  ║
║    • Quick exploratory / demo runs                               ║
║    • Regions with no local forcing data                          ║
║    • Teaching / workshops (zero setup)                           ║
║                                                                  ║
║  For production / publication runs, use CMFD or MSWX instead.   ║
║  Hourly data available from 2001-01-01 to near-real-time only.  ║
╚══════════════════════════════════════════════════════════════════╝

Priority cascade:
  1. CMFD  — China, 0.1°, 1979-2018 (best for Chinese basins)
  2. MSWX  — Global, 0.1°, 1979-2026 (best for global basins)
  3. NASA POWER — Global, 0.5°, 2001-NRT (this script, fallback)

Usage:
    python forcing_nasa_power.py \
        --grid_nc  outputs/<run>/vic_temp/grid/basin_grid.nc \
        --soil_param outputs/<run>/vic_temp/soil/SOIL_PARAM_COMPLETE.txt \
        --output_dir outputs/<run>/vic_temp/forcing/forcing_final \
        --start_year 2005 --end_year 2015 \
        --forcing_prefix "mybasin_0.25deg_"

    Or set paths below and run directly:
        python forcing_nasa_power.py
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
# KDT dt_vic_023: netCDF4 MUST be imported before xarray. See diagnostics/triplets.md.
import netCDF4  # noqa: F401  # isort:skip  -- must precede `import xarray`
import xarray as xr
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.units import celsius_to_kelvin, kelvin_to_celsius

# ─── Defaults (overridden by CLI args) ───────────────────────────
GRID_NC_PATH = Path("/mnt/disk1/Hydrocraft_server/outputs/blue_nile_ethiopia_2005_2015/vic_temp/grid/basin_grid.nc")
SOIL_PARAM_FILE = Path("/mnt/disk1/Hydrocraft_server/outputs/blue_nile_ethiopia_2005_2015/vic_temp/soil/SOIL_PARAM_COMPLETE.txt")
OUTPUT_DIR = Path("/mnt/disk1/Hydrocraft_server/outputs/blue_nile_ethiopia_2005_2015/vic_temp/forcing/forcing_final")
FORCING_PREFIX = "blue_nile_0.10deg_"
START_YEAR = 2005
END_YEAR = 2015

# ─── NASA POWER API config ───────────────────────────────────────
API_BASE = "https://power.larc.nasa.gov/api/temporal/hourly/point"
POWER_PARAMS = "T2M,PRECTOTCORR,PS,ALLSKY_SFC_SW_DWN,ALLSKY_SFC_LW_DWN,QV2M,WS2M"
PARAM_LIST = POWER_PARAMS.split(",")
COMMUNITY = "AG"
REQUEST_DELAY = 1.0        # seconds between API calls (be polite)

# ─── Local cache (pre-downloaded by nasa_power_batch_cache.py) ───
# Set HYDROCRAFT_POWER_REALTIME=1 to skip cache and always fetch from API
PREFER_REALTIME = os.environ.get("HYDROCRAFT_POWER_REALTIME", "1") == "1"
CACHE_DIR = Path(os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "data/nasa_power_cache/hourly"))
MAX_RETRIES = 3
RETRY_DELAY = 10           # seconds between retries on failure
MAX_DAYS_PER_REQUEST = 365 # split multi-year into yearly requests

# ─── Temporal resolution ─────────────────────────────────────────
# VIC supports any sub-daily timestep. NASA POWER provides hourly.
# Default: aggregate to 3-hourly (matches CMFD/MSWX convention).
# Option: output hourly directly (FORCE_STEPS_PER_DAY=24 in VIC).
SUPPORTED_TIMESTEPS = {
    "3hourly": {"hours": 3, "steps_per_day": 8},
    "hourly":  {"hours": 1, "steps_per_day": 24},
}

# ─── Basin size warning threshold ────────────────────────────────
MIN_RECOMMENDED_AREA_KM2 = 10_000  # warn if basin is smaller

# ─── Logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("forcing_nasa_power")


# =====================================================================
# Cache reading
# =====================================================================

def read_cache_year(lat: float, lon: float, year: int) -> Optional[pd.DataFrame]:
    """
    Read pre-downloaded data from local cache (created by nasa_power_batch_cache.py).
    Returns DataFrame with same format as API fetch, or None if not cached.
    """
    # Cache uses 1-decimal precision for directory names
    cell_dir = CACHE_DIR / f"{lat:.1f}_{lon:.1f}"
    npz_path = cell_dir / f"{year}.npz"
    if not npz_path.exists():
        return None

    try:
        data = np.load(npz_path)
        n_hours = len(data[PARAM_LIST[0]])

        # Build datetime index
        is_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
        expected = 8784 if is_leap else 8760
        dates = pd.date_range(f"{year}-01-01", periods=min(n_hours, expected), freq="h")

        df = pd.DataFrame({p: data[p][:len(dates)] for p in PARAM_LIST}, index=dates)
        return df
    except Exception as e:
        logger.warning("Cache read failed for (%.1f,%.1f) %d: %s", lat, lon, year, e)
        return None


# =====================================================================
# API fetching
# =====================================================================

def fetch_power_hourly(
    lat: float, lon: float,
    start_date: str, end_date: str,
) -> Optional[pd.DataFrame]:
    """
    Fetch hourly data from NASA POWER for a single point and date range.

    Parameters
    ----------
    lat, lon : float
        Point coordinates (WGS84).
    start_date, end_date : str
        Format YYYYMMDD, max ~365 days per request.

    Returns
    -------
    pd.DataFrame with columns [T2M, PRECTOTCORR, PS, ALLSKY_SFC_SW_DWN,
    ALLSKY_SFC_LW_DWN, QV2M, WS2M] indexed by datetime, or None on failure.
    """
    import urllib.request
    import urllib.error

    # NASA POWER must bypass the local egress proxy (127.0.0.1:7897): routing this PUBLIC
    # API through the proxy stalls the request indefinitely — it pinned a VIC run at
    # forcing 0/N for 80+ minutes. ProxyHandler({}) forces a DIRECT connection for THIS
    # opener regardless of any http_proxy/https_proxy env — the urllib equivalent of
    # requests' trust_env=False. (Bulk download APIs are the opposite; see the proxy notes.)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    url = (
        f"{API_BASE}?"
        f"parameters={POWER_PARAMS}"
        f"&community={COMMUNITY}"
        f"&longitude={lon:.4f}"
        f"&latitude={lat:.4f}"
        f"&start={start_date}"
        f"&end={end_date}"
        f"&format=JSON"
        f"&time-standard=UTC"
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HydroCraft/1.0"})
            with opener.open(req, timeout=120) as resp:  # direct, proxy-bypassed
                data = json.loads(resp.read().decode("utf-8"))

            params = data.get("properties", {}).get("parameter", {})
            if not params:
                logger.error("Empty response for (%.4f, %.4f) %s-%s", lat, lon, start_date, end_date)
                return None

            # Build DataFrame from the JSON parameter dict
            # Keys are like "20050101" with sub-keys "00","01",...,"23"
            # or flat keys like "2005010100", "2005010101", ...
            # NASA POWER hourly JSON: parameter -> {YYYYMMDDHH: value}
            first_param = list(params.values())[0]
            sample_key = list(first_param.keys())[0]

            records = {}
            for param_name, values in params.items():
                for time_key, val in values.items():
                    if time_key not in records:
                        records[time_key] = {}
                    # NASA POWER uses -999.0 for missing
                    records[time_key][param_name] = val if val != -999.0 else np.nan

            df = pd.DataFrame.from_dict(records, orient="index")
            # Parse time keys (YYYYMMDDHH format)
            df.index = pd.to_datetime(df.index, format="%Y%m%d%H")
            df.sort_index(inplace=True)
            return df

        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = RETRY_DELAY * attempt * 2
                logger.warning("Rate limited (429), waiting %ds... (attempt %d/%d)", wait, attempt, MAX_RETRIES)
                time.sleep(wait)
            elif e.code == 422:
                logger.error("Invalid request (422) for (%.4f, %.4f): %s", lat, lon, e.read().decode("utf-8", errors="replace")[:300])
                return None
            else:
                logger.warning("HTTP %d for (%.4f, %.4f), retry %d/%d", e.code, lat, lon, attempt, MAX_RETRIES)
                time.sleep(RETRY_DELAY)
        except Exception as e:
            logger.warning("Request failed for (%.4f, %.4f): %s, retry %d/%d", lat, lon, e, attempt, MAX_RETRIES)
            time.sleep(RETRY_DELAY)

    logger.error("All %d retries failed for (%.4f, %.4f) %s-%s", MAX_RETRIES, lat, lon, start_date, end_date)
    return None


def fetch_power_multi_year(
    lat: float, lon: float,
    start_year: int, end_year: int,
    use_cache: bool = None,
) -> Optional[pd.DataFrame]:
    """Fetch multi-year hourly data, using API by default (HYDROCRAFT_POWER_REALTIME=1).
    Set use_cache=True to override and use local cache when available."""
    if use_cache is None:
        use_cache = not PREFER_REALTIME
    frames = []
    for year in range(start_year, end_year + 1):
        # Try cache only if explicitly allowed
        if use_cache:
            df = read_cache_year(lat, lon, year)
            if df is not None:
                logger.info("  Cache hit: %d for (%.1f, %.1f)", year, lat, lon)
                frames.append(df)
                continue

        # Fetch from API (default when PREFER_REALTIME=True)
        start_date = f"{year}0101"
        end_date = f"{year}1231"
        logger.info("  Fetching %d from API for (%.4f, %.4f)...", year, lat, lon)
        df = fetch_power_hourly(lat, lon, start_date, end_date)
        if df is None:
            logger.error("  Failed to fetch %d — aborting this cell", year)
            return None
        frames.append(df)
        time.sleep(REQUEST_DELAY)

    return pd.concat(frames).sort_index()


# =====================================================================
# Hourly → 3-hourly aggregation
# =====================================================================

def aggregate_hourly_to_vic(
    df_hourly: pd.DataFrame,
    timestep: str = "3hourly",
) -> pd.DataFrame:
    """
    Aggregate hourly NASA POWER data to VIC timesteps.

    Supports two timesteps:
      - "3hourly" (default): 8 steps/day, matches CMFD/MSWX convention
      - "hourly": 24 steps/day, native NASA POWER resolution — finer temporal
        detail (diurnal cycle, storm events). Set FORCE_STEPS_PER_DAY=24 in
        the VIC global parameter file when using hourly.

    ⚠️ NASA POWER unit conventions (verified empirically):
      - Radiation (ALLSKY_SFC_*): Values are in MJ/m² per hour (energy
        received during that hour).  Hourly values SUM to the daily total.
        Convert to W/m²: value × 1e6 / 3600 = value × 277.78
      - Precipitation (PRECTOTCORR): Values are daily-equivalent rates
        in mm/day at each hour (NOT mm/hr!).  24 hourly values sum to
        24× the daily total.  To get actual mm in 1 hour: value / 24.
      - Temperature, pressure, humidity, wind: standard units, no scaling.
    """
    MJ_TO_W = 1e6 / 3600  # 277.78 — converts MJ/m²/hr → W/m²
    ts_cfg = SUPPORTED_TIMESTEPS[timestep]
    n_hours = ts_cfg["hours"]

    if timestep == "hourly":
        # No temporal aggregation — just apply unit corrections
        df_out = df_hourly.copy()
        df_out["PRECTOTCORR"] = df_out["PRECTOTCORR"] / 24.0         # mm/day rate → actual mm/hr
        df_out["ALLSKY_SFC_SW_DWN"] = df_out["ALLSKY_SFC_SW_DWN"] * MJ_TO_W  # MJ/m² → W/m²
        df_out["ALLSKY_SFC_LW_DWN"] = df_out["ALLSKY_SFC_LW_DWN"] * MJ_TO_W  # MJ/m² → W/m²
        return df_out

    # ─── 3-hourly aggregation ───
    agg_rules = {
        "T2M": "mean",
        "PRECTOTCORR": "sum",
        "PS": "mean",
        "ALLSKY_SFC_SW_DWN": "mean",
        "ALLSKY_SFC_LW_DWN": "mean",
        "QV2M": "mean",
        "WS2M": "mean",
    }

    df_out = df_hourly.resample("3h", closed="left", label="left").agg(agg_rules)

    # Unit corrections
    df_out["PRECTOTCORR"] = df_out["PRECTOTCORR"] / 24.0         # mm/day rate → actual mm/3hr
    df_out["ALLSKY_SFC_SW_DWN"] = df_out["ALLSKY_SFC_SW_DWN"] * MJ_TO_W  # MJ/m² → W/m²
    df_out["ALLSKY_SFC_LW_DWN"] = df_out["ALLSKY_SFC_LW_DWN"] * MJ_TO_W  # MJ/m² → W/m²

    return df_out


# =====================================================================
# Unit conversion → VIC format
# =====================================================================

def convert_to_vic_forcing(df_3h: pd.DataFrame) -> pd.DataFrame:
    """
    Convert NASA POWER 3-hourly data to VIC forcing columns.

    After aggregate_to_3hourly(), all units are already corrected:
      T2M (°C)                → AIR_TEMP (°C)        [direct]
      PRECTOTCORR (mm/3hr)    → PREC (mm/3hr)        [already corrected]
      PS (kPa)                → PRESSURE (kPa)       [direct]
      ALLSKY_SFC_SW_DWN (W/m²)→ SWDOWN (W/m²)        [already corrected]
      ALLSKY_SFC_LW_DWN (W/m²)→ LWDOWN (W/m²)        [already corrected]
      QV2M (g/kg) + PS (kPa)  → VP (kPa)             [derived]
      WS2M (m/s)              → WIND (m/s)            [direct]

    Vapor pressure derivation:
      q_kg = QV2M / 1000  (g/kg → kg/kg)
      VP = q_kg * PS / (0.622 + 0.378 * q_kg)   [kPa]
    """
    air_temp = df_3h["T2M"].copy()
    prec = df_3h["PRECTOTCORR"].clip(lower=0).copy()
    pressure = df_3h["PS"].copy()
    swdown = df_3h["ALLSKY_SFC_SW_DWN"].clip(lower=0).copy()
    lwdown = df_3h["ALLSKY_SFC_LW_DWN"].copy()
    wind = df_3h["WS2M"].clip(lower=0).copy()

    # Vapor pressure from specific humidity
    q_kg = df_3h["QV2M"] / 1000.0  # g/kg → kg/kg
    vp = q_kg * pressure / (0.622 + 0.378 * q_kg)

    # ─── Fill NaNs with physically reasonable defaults ───
    air_temp.fillna(15.0, inplace=True)
    prec.fillna(0.0, inplace=True)
    pressure.fillna(101.3, inplace=True)
    swdown.fillna(150.0, inplace=True)
    # Longwave fallback: Stefan-Boltzmann estimate
    lw_default = 5.67e-8 * ((celsius_to_kelvin(air_temp)) ** 4) * 0.8  # emissivity ~0.8
    lwdown = lwdown.fillna(lw_default)
    vp.fillna(0.5, inplace=True)
    wind.fillna(2.0, inplace=True)

    # Assemble in VIC column order
    vic_df = pd.DataFrame({
        "AIR_TEMP": air_temp,
        "PREC": prec,
        "PRESSURE": pressure,
        "SWDOWN": swdown,
        "LWDOWN": lwdown,
        "VP": vp,
        "WIND": wind,
    })

    return vic_df


# =====================================================================
# Grid cell extraction
# =====================================================================

def read_grid_cells(
    grid_nc_path: Path,
    soil_param_path: Path,
) -> list[tuple[float, float]]:
    """
    Read grid cell coordinates from the soil parameter file.
    Returns list of (lat, lon) tuples — one per VIC grid cell.
    """
    cells = []
    with open(soil_param_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 4:
                # Format: run_cell grid_id lat lon ...
                run_cell = int(parts[0])
                if run_cell == 1:
                    lat = float(parts[2])
                    lon = float(parts[3])
                    cells.append((lat, lon))

    if not cells:
        raise ValueError(f"No active grid cells found in {soil_param_path}")

    logger.info("Found %d active VIC grid cells", len(cells))
    return cells


def estimate_basin_area(grid_nc_path: Path) -> float:
    """Rough basin area estimate from grid cell count × cell area."""
    # dt_vic_023: pin the engine; a bare open_dataset() probes every backend
    # entrypoint and SIGSEGVs at interpreter exit.
    ds = xr.open_dataset(grid_nc_path, engine="netcdf4")
    mask = ds["mask"] if "mask" in ds else None
    if mask is not None:
        n_cells = int((mask > 0).sum())
    else:
        n_cells = ds.dims.get("y", 1) * ds.dims.get("x", 1)

    # Get resolution
    y_coords = ds["y"].values if "y" in ds else ds["lat"].values
    if len(y_coords) > 1:
        res = abs(float(y_coords[1] - y_coords[0]))
    else:
        res = 0.25

    ds.close()

    # Approximate cell area at mid-latitude
    mid_lat = float(np.mean(y_coords))
    cell_km2 = (res * 111.0) * (res * 111.0 * np.cos(np.radians(mid_lat)))
    area_km2 = n_cells * cell_km2
    return area_km2


def group_cells_by_power_grid(
    cells: list[tuple[float, float]],
) -> dict[tuple[float, float], list[tuple[float, float]]]:
    """
    Group VIC cells by their nearest NASA POWER grid point.

    POWER resolution is ~0.5° — multiple VIC cells (at 0.25° or 0.1°)
    will map to the same POWER point. We fetch once per unique POWER
    point, then write the same data to all VIC cells in that group.

    This deduplication dramatically reduces API calls.
    """
    groups: dict[tuple[float, float], list[tuple[float, float]]] = {}
    power_res = 0.5  # POWER meteorology resolution

    for lat, lon in cells:
        # Snap to nearest POWER grid center
        power_lat = round(round(lat / power_res) * power_res, 4)
        power_lon = round(round(lon / power_res) * power_res, 4)
        key = (power_lat, power_lon)
        if key not in groups:
            groups[key] = []
        groups[key].append((lat, lon))

    logger.info(
        "%d VIC cells → %d unique NASA POWER points (%.0f%% fewer API calls)",
        len(cells), len(groups),
        (1 - len(groups) / max(len(cells), 1)) * 100,
    )
    return groups


# =====================================================================
# Main pipeline
# =====================================================================

def run(
    grid_nc_path: Path,
    soil_param_path: Path,
    output_dir: Path,
    forcing_prefix: str,
    start_year: int,
    end_year: int,
    timestep: str = "3hourly",
):
    """
    Main entry point: fetch NASA POWER data → VIC forcing files.

    timestep: "3hourly" (default, 8 steps/day) or "hourly" (24 steps/day).
              Hourly gives finer temporal detail of the diurnal cycle and
              storm events directly from NASA POWER's native resolution.
              Remember to set FORCE_STEPS_PER_DAY accordingly in global_param.
    """
    # ─── Validate time range ───
    if start_year < 2001:
        logger.error(
            "NASA POWER hourly data starts at 2001-01-01. "
            "Requested start_year=%d is too early. Use CMFD or MSWX for pre-2001.",
            start_year,
        )
        sys.exit(1)

    # ─── Basin size check ───
    try:
        area_km2 = estimate_basin_area(grid_nc_path)
        logger.info("Estimated basin area: %.0f km²", area_km2)
        if area_km2 < MIN_RECOMMENDED_AREA_KM2:
            logger.warning(
                "═" * 60 + "\n"
                "  ⚠️  SMALL BASIN WARNING\n"
                "  Basin area ~%.0f km² is below the recommended minimum\n"
                "  of %d km² for NASA POWER forcing (0.5° resolution).\n"
                "  Many grid cells will receive IDENTICAL forcing data.\n"
                "  For small basins, use CMFD (China) or MSWX (global) instead.\n" +
                "═" * 60,
                area_km2, MIN_RECOMMENDED_AREA_KM2,
            )
    except Exception as e:
        logger.warning("Could not estimate basin area: %s", e)

    # ─── Read grid cells ───
    cells = read_grid_cells(grid_nc_path, soil_param_path)

    # ─── Group by POWER grid to deduplicate API calls ───
    power_groups = group_cells_by_power_grid(cells)

    # ─── Create output directory ───
    output_dir.mkdir(parents=True, exist_ok=True)

    # ─── Validate timestep ───
    if timestep not in SUPPORTED_TIMESTEPS:
        logger.error("Unsupported timestep '%s'. Choose: %s", timestep, list(SUPPORTED_TIMESTEPS.keys()))
        sys.exit(1)

    ts_cfg = SUPPORTED_TIMESTEPS[timestep]
    steps_per_day = ts_cfg["steps_per_day"]

    if timestep == "hourly":
        logger.info(
            "Outputting HOURLY forcing (24 steps/day). "
            "Set FORCE_STEPS_PER_DAY 24 in VIC global_param."
        )

    # ─── Fetch and write ───
    n_years = end_year - start_year + 1
    expected_rows = 0
    for yr in range(start_year, end_year + 1):
        days = 366 if (yr % 4 == 0 and (yr % 100 != 0 or yr % 400 == 0)) else 365
        expected_rows += days * steps_per_day

    total_power_points = len(power_groups)
    total_vic_cells = len(cells)
    logger.info(
        "Fetching %d years (%d-%d) for %d POWER points → %d VIC cells",
        n_years, start_year, end_year, total_power_points, total_vic_cells,
    )
    logger.info("Expected rows per cell: %d (%s timesteps)", expected_rows, timestep)
    logger.info(
        "Estimated time: ~%d minutes (%d API calls × %d years × %.0fs delay)",
        int(total_power_points * n_years * (REQUEST_DELAY + 3) / 60),
        total_power_points, n_years, REQUEST_DELAY,
    )

    success_count = 0
    fail_count = 0

    for i, (power_coord, vic_cells) in enumerate(power_groups.items(), 1):
        power_lat, power_lon = power_coord
        logger.info(
            "[%d/%d] POWER point (%.4f, %.4f) → %d VIC cell(s)",
            i, total_power_points, power_lat, power_lon, len(vic_cells),
        )

        # ─── Resume: skip this POWER point if every VIC cell it feeds is already
        # written AND has the exact expected row count. A short/truncated file
        # (killed mid-write on a previous launch) fails the check and is refetched.
        already = 0
        for cell_lat, cell_lon in vic_cells:
            p = output_dir / f"{forcing_prefix}{cell_lat:.4f}_{cell_lon:.4f}"
            if p.exists():
                with open(p) as fh:
                    if sum(1 for _ in fh) == expected_rows:
                        already += 1
        if already == len(vic_cells):
            logger.info("  resume: %d cell file(s) already complete — skipping fetch", already)
            success_count += len(vic_cells)
            continue

        # Fetch multi-year hourly data
        df_hourly = fetch_power_multi_year(power_lat, power_lon, start_year, end_year)
        if df_hourly is None:
            logger.error("  FAILED — skipping %d VIC cells", len(vic_cells))
            fail_count += len(vic_cells)
            continue

        # Aggregate to target timestep
        df_3h = aggregate_hourly_to_vic(df_hourly, timestep=timestep)

        # Convert to VIC units
        vic_df = convert_to_vic_forcing(df_3h)

        # Validate row count
        actual_rows = len(vic_df)
        if actual_rows != expected_rows:
            logger.warning(
                "  Row count mismatch: expected %d, got %d (%.1f%% diff). "
                "Padding or trimming to match.",
                expected_rows, actual_rows,
                abs(actual_rows - expected_rows) / expected_rows * 100,
            )
            if actual_rows < expected_rows:
                # Pad with last-row values (edge case: API returned partial data)
                pad = pd.DataFrame(
                    [vic_df.iloc[-1].values] * (expected_rows - actual_rows),
                    columns=vic_df.columns,
                )
                vic_df = pd.concat([vic_df, pad], ignore_index=True)
            else:
                vic_df = vic_df.iloc[:expected_rows]

        # Write to all VIC cells in this group
        for cell_lat, cell_lon in vic_cells:
            filename = f"{forcing_prefix}{cell_lat:.4f}_{cell_lon:.4f}"
            output_path = output_dir / filename
            vic_df.to_csv(
                output_path,
                sep="\t",
                header=False,
                index=False,
                float_format="%.4f",
            )
            success_count += 1

        logger.info("  ✓ Wrote %d file(s)", len(vic_cells))

    # ─── Summary ───
    logger.info("=" * 60)
    logger.info("NASA POWER forcing generation complete")
    logger.info("  Success: %d / %d cells", success_count, total_vic_cells)
    if fail_count:
        logger.warning("  Failed:  %d / %d cells", fail_count, total_vic_cells)
    logger.info("  Output:  %s", output_dir)
    logger.info("  Prefix:  %s", forcing_prefix)
    logger.info("  Period:  %d-%d (%d years)", start_year, end_year, n_years)
    logger.info("  Timestep: %s (%d steps/day)", timestep, steps_per_day)
    logger.info(
        "  ⚠️  Resolution: 0.5° (NASA POWER) — coarser than CMFD/MSWX (0.1°)"
    )
    if timestep == "hourly":
        logger.info(
            "  ℹ️  Remember to set FORCE_STEPS_PER_DAY 24 in VIC global_param"
        )
    logger.info("=" * 60)

    if fail_count:
        sys.exit(1)


# =====================================================================
# CLI
# =====================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "NASA POWER Forcing Generator for VIC — online API fallback.\n\n"
            "⚠️  COARSE RESOLUTION (0.5°): Recommended only for large basins\n"
            "(>10,000 km²), demos, or regions without local forcing data.\n"
            "For production runs, use CMFD (China) or MSWX (global)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--grid_nc", type=Path, default=GRID_NC_PATH,
                        help="Path to basin_grid.nc")
    parser.add_argument("--soil_param", type=Path, default=SOIL_PARAM_FILE,
                        help="Path to SOIL_PARAM_COMPLETE.txt")
    parser.add_argument("--output_dir", type=Path, default=OUTPUT_DIR,
                        help="Output directory for VIC forcing files")
    parser.add_argument("--forcing_prefix", type=str, default=FORCING_PREFIX,
                        help="Forcing file prefix (e.g. 'mybasin_0.25deg_')")
    parser.add_argument("--start_year", type=int, default=START_YEAR,
                        help="Start year (>= 2001)")
    parser.add_argument("--end_year", type=int, default=END_YEAR,
                        help="End year")
    parser.add_argument("--timestep", type=str, default="3hourly",
                        choices=["3hourly", "hourly"],
                        help="Temporal resolution: '3hourly' (default, 8/day, "
                             "matches CMFD/MSWX) or 'hourly' (24/day, native "
                             "NASA POWER resolution — finer storm/diurnal detail). "
                             "If hourly, set FORCE_STEPS_PER_DAY=24 in VIC global_param.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(
        grid_nc_path=args.grid_nc,
        soil_param_path=args.soil_param,
        output_dir=args.output_dir,
        forcing_prefix=args.forcing_prefix,
        start_year=args.start_year,
        end_year=args.end_year,
        timestep=args.timestep,
    )
