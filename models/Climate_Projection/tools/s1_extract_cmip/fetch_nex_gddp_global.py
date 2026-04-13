"""
Global CMIP6 Data Fetcher — NASA NEX-GDDP-CMIP6 via THREDDS.

Fetches bias-corrected, downscaled CMIP6 daily data for any basin worldwide.
Drop-in replacement for extract_cmip6_basin.py (which only works for China).

Data source: NASA NEX-GDDP-CMIP6 (0.25°, daily, 1950-2100, bias-corrected BCSD)
  - 34 GCMs, 4 SSPs (ssp126, ssp245, ssp370, ssp585) + historical
  - Variables: pr, tasmax, tasmin (+ hurs, rlds, rsds where available)

Usage:
    python fetch_nex_gddp_global.py \
        --grid_nc outputs/<basin>/vic_temp/grid/basin_grid.nc \
        --model ACCESS-CM2 \
        --scenario historical \
        --years 1981-2010 \
        --output_dir outputs/<basin>/climate_projection/cmip6_extracted \
        --basin_name mybas

    # Future scenario
    python fetch_nex_gddp_global.py \
        --grid_nc outputs/<basin>/vic_temp/grid/basin_grid.nc \
        --model ACCESS-CM2 \
        --scenario ssp245 \
        --years 2041-2070 \
        --output_dir outputs/<basin>/climate_projection/cmip6_extracted \
        --basin_name mybas

    # Multiple models in one call
    python fetch_nex_gddp_global.py \
        --grid_nc outputs/<basin>/vic_temp/grid/basin_grid.nc \
        --models ACCESS-CM2,BCC-CSM2-MR,MIROC6,MRI-ESM2-0,EC-Earth3 \
        --scenario ssp245 \
        --years 2041-2070 \
        --output_dir outputs/<basin>/climate_projection/cmip6_extracted \
        --basin_name mybas
"""

import argparse
import logging
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

import numpy as np
import xarray as xr
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.units import CMFD_PRECIP_KGM2S_TO_MMDAY

# ─── Configuration ───────────────────────────────────────────────
THREDDS_BASE = "https://ds.nccs.nasa.gov/thredds/ncss/grid/AMES/NEX/GDDP-CMIP6"
ENSEMBLE = "r1i1p1f1"
VERSION = "v2.0"

# Core variables (available for all models)
CORE_VARIABLES = ["pr", "tasmax", "tasmin"]
# Extended variables (available for most models)
EXTENDED_VARIABLES = ["hurs", "rlds", "rsds"]

# Available models (NEX-GDDP-CMIP6 v2.0)
AVAILABLE_MODELS = [
    "ACCESS-CM2", "ACCESS-ESM1-5", "BCC-CSM2-MR", "CanESM5",
    "CESM2", "CESM2-WACCM", "CMCC-CM2-SR5", "CMCC-ESM2",
    "CNRM-CM6-1", "CNRM-ESM2-1", "EC-Earth3", "EC-Earth3-Veg-LR",
    "FGOALS-g3", "GFDL-CM4", "GFDL-ESM4", "GISS-E2-1-G",
    "HadGEM3-GC31-LL", "HadGEM3-GC31-MM", "IITM-ESM",
    "INM-CM4-8", "INM-CM5-0", "IPSL-CM6A-LR", "KACE-1-0-G",
    "KIOST-ESM", "MIROC-ES2L", "MIROC6", "MPI-ESM1-2-HR",
    "MPI-ESM1-2-LR", "MRI-ESM2-0", "NESM3", "NorESM2-LM",
    "NorESM2-MM", "TaiESM1", "UKESM1-0-LL",
]

# Recommended 5-model ensemble (covers diverse climate sensitivities)
RECOMMENDED_MODELS = [
    "ACCESS-CM2",     # Australia, ~3.7°C ECS
    "BCC-CSM2-MR",    # China, ~3.0°C ECS
    "EC-Earth3",      # Europe, ~4.3°C ECS
    "MIROC6",         # Japan, ~2.6°C ECS
    "MRI-ESM2-0",     # Japan, ~3.2°C ECS
]

SCENARIOS = ["historical", "ssp126", "ssp245", "ssp370", "ssp585"]
SCENARIO_YEARS = {
    "historical": (1950, 2014),
    "ssp126": (2015, 2100),
    "ssp245": (2015, 2100),
    "ssp370": (2015, 2100),
    "ssp585": (2015, 2100),
}

REQUEST_DELAY = 1.0
MAX_RETRIES = 3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("fetch_nex_gddp")


# =====================================================================
# THREDDS fetching
# =====================================================================

def fetch_year(
    model: str, scenario: str, variable: str, year: int,
    lat_min: float, lat_max: float, lon_min: float, lon_max: float,
) -> Optional[xr.Dataset]:
    """Fetch one variable for one year from THREDDS with spatial subsetting."""

    filename = f"{variable}_day_{model}_{scenario}_{ENSEMBLE}_gn_{year}_{VERSION}.nc"
    dataset_path = f"{model}/{scenario}/{ENSEMBLE}/{variable}/{filename}"
    url = (
        f"{THREDDS_BASE}/{dataset_path}"
        f"?var={variable}"
        f"&north={lat_max + 0.13:.4f}&south={lat_min - 0.13:.4f}"
        f"&west={lon_min - 0.13:.4f}&east={lon_max + 0.13:.4f}"
        f"&time_start={year}-01-01T12:00:00Z&time_end={year}-12-31T12:00:00Z"
        f"&accept=netcdf&addLatLon=true"
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HydroCraft/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()

            # Write to temp file and open with xarray
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            ds = xr.open_dataset(tmp_path)
            Path(tmp_path).unlink(missing_ok=True)
            return ds

        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.warning("  File not found: %s/%d (may not exist for this model)", variable, year)
                return None
            elif e.code == 429:
                wait = REQUEST_DELAY * (2 ** attempt)
                logger.warning("  Rate limited, waiting %ds (attempt %d/%d)", wait, attempt, MAX_RETRIES)
                time.sleep(wait)
            else:
                logger.warning("  HTTP %d for %s/%d, retry %d/%d", e.code, variable, year, attempt, MAX_RETRIES)
                time.sleep(REQUEST_DELAY * attempt)
        except Exception as e:
            logger.warning("  Error fetching %s/%d: %s, retry %d/%d", variable, year, e, attempt, MAX_RETRIES)
            time.sleep(REQUEST_DELAY * attempt)

    logger.error("  Failed after %d retries: %s/%d", MAX_RETRIES, variable, year)
    return None


# =====================================================================
# Main pipeline
# =====================================================================

def extract_basin_cmip6(
    grid_nc_path: Path,
    model: str,
    scenario: str,
    start_year: int,
    end_year: int,
    output_dir: Path,
    basin_name: str,
    variables: list[str] = None,
):
    """
    Fetch NEX-GDDP-CMIP6 data for a basin and save as NetCDF.

    Output format matches extract_cmip6_basin.py so downstream tools
    (compute_climate_deltas.py, apply_deltas_forcing.py) work unchanged.
    """
    if variables is None:
        variables = list(CORE_VARIABLES)

    # Validate
    if model not in AVAILABLE_MODELS:
        logger.error("Unknown model '%s'. Available: %s", model, ", ".join(AVAILABLE_MODELS))
        sys.exit(1)
    if scenario not in SCENARIOS:
        logger.error("Unknown scenario '%s'. Available: %s", scenario, ", ".join(SCENARIOS))
        sys.exit(1)

    valid_range = SCENARIO_YEARS[scenario]
    if start_year < valid_range[0] or end_year > valid_range[1]:
        logger.error("Year range %d-%d outside %s range (%d-%d)",
                      start_year, end_year, scenario, *valid_range)
        sys.exit(1)

    # Read basin extent from grid
    ds_grid = xr.open_dataset(grid_nc_path)
    lat_key = 'y' if 'y' in ds_grid else 'lat'
    lon_key = 'x' if 'x' in ds_grid else 'lon'
    lats = ds_grid[lat_key].values
    lons = ds_grid[lon_key].values
    lat_min, lat_max = float(lats.min()), float(lats.max())
    lon_min, lon_max = float(lons.min()), float(lons.max())
    ds_grid.close()

    logger.info("Basin extent: lat [%.2f, %.2f], lon [%.2f, %.2f]", lat_min, lat_max, lon_min, lon_max)
    logger.info("Model: %s, Scenario: %s, Years: %d-%d", model, scenario, start_year, end_year)
    logger.info("Variables: %s", ", ".join(variables))

    n_years = end_year - start_year + 1
    n_requests = n_years * len(variables)
    logger.info("Total requests: %d (%d years × %d variables), est. time: ~%d min",
                n_requests, n_years, len(variables),
                int(n_requests * 8 / 60))  # ~8s per request

    output_dir.mkdir(parents=True, exist_ok=True)

    # Fetch each variable
    for var in variables:
        logger.info("Fetching %s...", var)
        yearly_datasets = []

        for year in range(start_year, end_year + 1):
            # Check if already cached
            out_file = output_dir / f"{model}_{scenario}_{var}_{basin_name}_{year}.nc"
            if out_file.exists():
                logger.info("  %d: cached", year)
                yearly_datasets.append(xr.open_dataset(out_file))
                continue

            logger.info("  %d: fetching...", year)
            ds = fetch_year(model, scenario, var, year, lat_min, lat_max, lon_min, lon_max)
            if ds is None:
                logger.warning("  %d: skipped (not available)", year)
                continue

            yearly_datasets.append(ds)
            time.sleep(REQUEST_DELAY)

        if not yearly_datasets:
            logger.error("No data retrieved for %s/%s/%s", model, scenario, var)
            continue

        # Concatenate all years
        combined = xr.concat(yearly_datasets, dim="time")
        for ds in yearly_datasets:
            ds.close()

        # Save combined file
        out_path = output_dir / f"{model}_{scenario}_{var}_{basin_name}.nc"
        combined.to_netcdf(out_path)
        combined.close()

        # Validate
        ds_check = xr.open_dataset(out_path)
        n_time = ds_check.sizes.get('time', 0)
        logger.info("  Saved: %s (%d days, %.1f MB)",
                     out_path.name, n_time, out_path.stat().st_size / 1e6)

        # Quick sanity check
        vals = ds_check[var].values.flatten()
        vals = vals[~np.isnan(vals)]
        if var == 'pr':
            annual_mm = float(vals.mean()) * CMFD_PRECIP_KGM2S_TO_MMDAY * 365
            logger.info("  Sanity: mean precip = %.1f mm/year", annual_mm)
        elif var in ('tasmax', 'tasmin'):
            mean_c = float(vals.mean()) - 273.15
            logger.info("  Sanity: mean %s = %.1f°C", var, mean_c)
        ds_check.close()

    logger.info("Done! Output: %s", output_dir)


# =====================================================================
# CLI
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Global CMIP6 data fetcher — NASA NEX-GDDP-CMIP6 via THREDDS.\n\n"
            "Fetches bias-corrected, downscaled CMIP6 daily data (0.25°) for any\n"
            "basin worldwide. Drop-in replacement for extract_cmip6_basin.py.\n\n"
            f"Available models ({len(AVAILABLE_MODELS)}): {', '.join(AVAILABLE_MODELS[:10])}...\n"
            f"Recommended 5-model ensemble: {', '.join(RECOMMENDED_MODELS)}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--grid_nc", type=Path, required=True, help="Basin grid NetCDF")
    parser.add_argument("--model", type=str, default=None, help="Single CMIP6 model name")
    parser.add_argument("--models", type=str, default=None,
                        help="Comma-separated model names (or 'recommended' for 5-model ensemble)")
    parser.add_argument("--scenario", type=str, required=True,
                        choices=SCENARIOS, help="SSP scenario or 'historical'")
    parser.add_argument("--years", type=str, required=True,
                        help="Year range, e.g., '1981-2010' or '2041-2070'")
    parser.add_argument("--output_dir", type=Path, required=True, help="Output directory")
    parser.add_argument("--basin_name", type=str, required=True, help="Basin identifier for filenames")
    parser.add_argument("--variables", type=str, default="pr,tasmax,tasmin",
                        help="Variables to fetch (default: pr,tasmax,tasmin)")
    parser.add_argument("--list_models", action="store_true", help="List all available models and exit")
    args = parser.parse_args()

    if args.list_models:
        print(f"Available models ({len(AVAILABLE_MODELS)}):")
        for m in AVAILABLE_MODELS:
            tag = " (recommended)" if m in RECOMMENDED_MODELS else ""
            print(f"  {m}{tag}")
        return

    # Parse years
    start_year, end_year = map(int, args.years.split("-"))

    # Parse models
    if args.models:
        if args.models.lower() == "recommended":
            models = list(RECOMMENDED_MODELS)
        else:
            models = [m.strip() for m in args.models.split(",")]
    elif args.model:
        models = [args.model]
    else:
        parser.error("Provide --model or --models")
        return

    variables = [v.strip() for v in args.variables.split(",")]

    # Run for each model
    for i, model in enumerate(models, 1):
        logger.info("=" * 60)
        logger.info("[%d/%d] Model: %s", i, len(models), model)
        logger.info("=" * 60)
        extract_basin_cmip6(
            grid_nc_path=args.grid_nc,
            model=model,
            scenario=args.scenario,
            start_year=start_year,
            end_year=end_year,
            output_dir=args.output_dir,
            basin_name=args.basin_name,
            variables=variables,
        )

    logger.info("All %d models complete.", len(models))


if __name__ == "__main__":
    main()
