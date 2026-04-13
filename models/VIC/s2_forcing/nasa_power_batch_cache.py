"""
⚠️ DEPRECATED — NASA POWER caching is disabled. All data fetching should use real-time API.
Set HYDROCRAFT_POWER_REALTIME=0 to re-enable cache if needed.

NASA POWER Batch Cache Downloader — pre-download hourly data for all GRDC + HYDAT basins.

Downloads NASA POWER hourly data for all unique 0.5° grid cells covering
GRDC (5,357 global) and HYDAT (5,751 Canadian) basin centroids, storing
as per-cell yearly NPZ files for instant reuse by forcing_nasa_power.py.

Cache structure:
    {CACHE_DIR}/{lat}_{lon}/     — one dir per 0.5° POWER cell
        2001.npz                 — hourly data for that year
        2002.npz
        ...

Each NPZ contains 7 arrays (8760 rows for non-leap, 8784 for leap):
    T2M, PRECTOTCORR, PS, ALLSKY_SFC_SW_DWN, ALLSKY_SFC_LW_DWN, QV2M, WS2M
    (raw NASA POWER values — unit conversion happens at read time)

Features:
    - Parallel workers (configurable, default 8)
    - Resume capability (skips already-downloaded cell/year combos)
    - Progress tracking with ETA
    - Rate-limit aware (backs off on HTTP 429)

Usage:
    # Full download (~25 hours with 8 workers)
    python nasa_power_batch_cache.py

    # Download specific year range
    python nasa_power_batch_cache.py --start_year 2005 --end_year 2020

    # More/fewer workers
    python nasa_power_batch_cache.py --workers 4

    # Dry run (count cells, estimate time)
    python nasa_power_batch_cache.py --dry_run
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import numpy as np

# ─── Configuration ───────────────────────────────────────────────
CACHE_DIR = Path("/mnt/disk3/nasa_power_cache/hourly")
GRDC_SHP = Path("/mnt/disk3/observed_data/dischargeandwatershed/GRDC-Caravan-extension-nc/shapefiles/grdc/grdc_basin_shapes.shp")
HYDAT_DIR = Path("/mnt/disk3/observed_data/dischargeandwatershed/National Water Data Archive HYDAT/HydrometricNetworkBasinPolygons/gpkg")

API_BASE = "https://power.larc.nasa.gov/api/temporal/hourly/point"
POWER_PARAMS = "T2M,PRECTOTCORR,PS,ALLSKY_SFC_SW_DWN,ALLSKY_SFC_LW_DWN,QV2M,WS2M"
PARAM_LIST = POWER_PARAMS.split(",")
COMMUNITY = "AG"

DEFAULT_START_YEAR = 2001
DEFAULT_END_YEAR = 2024
DEFAULT_WORKERS = 8
MAX_RETRIES = 3
BASE_DELAY = 2.0        # base delay between retries
WORKER_DELAY = 0.5      # delay between requests per worker

# ─── Logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("nasa_power_cache")

# ─── Progress tracking ──────────────────────────────────────────
progress_lock = Lock()
completed_count = 0
failed_count = 0
total_tasks = 0
start_time = 0.0

PROGRESS_FILE = CACHE_DIR / "_progress.json"


def save_progress(completed: int, failed: int, total: int):
    """Save progress to disk for resume."""
    try:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROGRESS_FILE, 'w') as f:
            json.dump({
                "completed": completed,
                "failed": failed,
                "total": total,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, f)
    except Exception:
        pass


# =====================================================================
# Cell discovery
# =====================================================================

def discover_cells() -> set[tuple[float, float]]:
    """
    Find all unique 0.5° POWER grid cells from GRDC + HYDAT basin centroids.
    """
    import geopandas as gpd

    cells = set()
    power_res = 0.5

    def snap(lat, lon):
        return (
            round(round(lat / power_res) * power_res, 1),
            round(round(lon / power_res) * power_res, 1),
        )

    # GRDC
    if GRDC_SHP.exists():
        logger.info("Reading GRDC basins...")
        grdc = gpd.read_file(GRDC_SHP)
        centroids = grdc.geometry.centroid
        for c in centroids:
            if c is not None and not c.is_empty:
                cells.add(snap(c.y, c.x))
        logger.info("  GRDC: %d basins → %d unique cells", len(grdc), len(cells))
    else:
        logger.warning("GRDC shapefile not found: %s", GRDC_SHP)

    # HYDAT
    n_before = len(cells)
    if HYDAT_DIR.exists():
        logger.info("Reading HYDAT basins...")
        import glob
        for gpkg in sorted(glob.glob(str(HYDAT_DIR / "*.gpkg"))):
            try:
                gdf = gpd.read_file(gpkg, layer="DrainageBasin_BassinDeDrainage")
                centroids = gdf.geometry.centroid
                for c in centroids:
                    if c is not None and not c.is_empty:
                        cells.add(snap(c.y, c.x))
            except Exception as e:
                logger.warning("  Failed to read %s: %s", os.path.basename(gpkg), e)
        logger.info("  HYDAT: added %d new unique cells", len(cells) - n_before)
    else:
        logger.warning("HYDAT directory not found: %s", HYDAT_DIR)

    logger.info("Total unique 0.5° cells: %d", len(cells))
    return cells


# =====================================================================
# Download a single cell/year
# =====================================================================

def download_cell_year(lat: float, lon: float, year: int) -> bool:
    """
    Download hourly data for one 0.5° cell for one year.
    Returns True on success, False on failure.
    """
    global completed_count, failed_count

    # Check if already cached
    cell_dir = CACHE_DIR / f"{lat:.1f}_{lon:.1f}"
    npz_path = cell_dir / f"{year}.npz"
    nodata_path = cell_dir / "_nodata"  # marker for cells with no POWER coverage
    if npz_path.exists():
        with progress_lock:
            completed_count += 1
        return True
    if nodata_path.exists():
        # Permanently marked as no-data (ocean, invalid coords) — skip
        with progress_lock:
            completed_count += 1
        return True

    # Fetch from API
    start_date = f"{year}0101"
    end_date = f"{year}1231"
    url = (
        f"{API_BASE}?"
        f"parameters={POWER_PARAMS}"
        f"&community={COMMUNITY}"
        f"&longitude={lon:.1f}"
        f"&latitude={lat:.1f}"
        f"&start={start_date}"
        f"&end={end_date}"
        f"&format=JSON"
        f"&time-standard=UTC"
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HydroCraft-Cache/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            params = data.get("properties", {}).get("parameter", {})
            if not params:
                logger.warning("Empty response for (%.1f, %.1f) %d — marking as no-data", lat, lon, year)
                cell_dir.mkdir(parents=True, exist_ok=True)
                nodata_path.write_text(f"empty_response:{year}\n")
                with progress_lock:
                    failed_count += 1
                return False

            # Parse into numpy arrays
            # Keys are YYYYMMDDHH format
            first_param = list(params.values())[0]
            n_hours = len(first_param)
            time_keys = sorted(first_param.keys())

            arrays = {}
            for pname in PARAM_LIST:
                if pname in params:
                    vals = [params[pname].get(tk, -999.0) for tk in time_keys]
                    arr = np.array(vals, dtype=np.float32)
                    arr[arr == -999.0] = np.nan
                    arrays[pname] = arr
                else:
                    arrays[pname] = np.full(n_hours, np.nan, dtype=np.float32)

            # Save as compressed NPZ
            cell_dir.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(npz_path, **arrays)

            with progress_lock:
                completed_count += 1
                if completed_count % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = completed_count / elapsed
                    remaining = (total_tasks - completed_count) / max(rate, 0.001)
                    logger.info(
                        "Progress: %d/%d (%.1f%%) | %.1f tasks/min | ETA: %.1f hrs | Failed: %d",
                        completed_count, total_tasks,
                        completed_count / total_tasks * 100,
                        rate * 60,
                        remaining / 3600,
                        failed_count,
                    )
                    save_progress(completed_count, failed_count, total_tasks)

            return True

        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = BASE_DELAY * (2 ** attempt) + np.random.uniform(0, 2)
                logger.warning("Rate limited (429) for (%.1f,%.1f) %d, waiting %.0fs (attempt %d)",
                               lat, lon, year, wait, attempt)
                time.sleep(wait)
            elif e.code == 422:
                logger.error("Invalid request (422) for (%.1f,%.1f) %d — marking as no-data", lat, lon, year)
                cell_dir.mkdir(parents=True, exist_ok=True)
                nodata_path.write_text(f"422:{year}\n")
                with progress_lock:
                    failed_count += 1
                return False
            else:
                time.sleep(BASE_DELAY * attempt)
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(BASE_DELAY * attempt)
            else:
                logger.warning("Failed (%.1f,%.1f) %d after %d retries: %s", lat, lon, year, MAX_RETRIES, e)

    with progress_lock:
        failed_count += 1
    return False


def download_worker(task: tuple[float, float, int]) -> bool:
    """Worker wrapper with inter-request delay."""
    lat, lon, year = task
    result = download_cell_year(lat, lon, year)
    time.sleep(WORKER_DELAY)  # be polite to NASA
    return result


# =====================================================================
# Main
# =====================================================================

def main():
    global completed_count, failed_count, total_tasks, start_time

    parser = argparse.ArgumentParser(description="NASA POWER Batch Cache Downloader")
    parser.add_argument("--start_year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end_year", type=int, default=DEFAULT_END_YEAR)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--dry_run", action="store_true", help="Just count cells and estimate time")
    parser.add_argument("--cache_dir", type=str, default=str(CACHE_DIR))
    args = parser.parse_args()

    # Override module globals so worker functions see the right paths
    _mod = sys.modules[__name__]
    _mod.CACHE_DIR = Path(args.cache_dir)
    _mod.PROGRESS_FILE = _mod.CACHE_DIR / "_progress.json"
    _mod.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Discover cells
    cells = discover_cells()
    if not cells:
        logger.error("No cells found!")
        sys.exit(1)

    years = list(range(args.start_year, args.end_year + 1))
    n_years = len(years)

    # Build task list (skip already cached)
    tasks = []
    cached = 0
    for lat, lon in sorted(cells):
        for year in years:
            npz_path = CACHE_DIR / f"{lat:.1f}_{lon:.1f}" / f"{year}.npz"
            if npz_path.exists():
                cached += 1
            else:
                tasks.append((lat, lon, year))

    total_all = len(cells) * n_years
    total_tasks = len(tasks)

    logger.info("=" * 60)
    logger.info("NASA POWER Batch Cache Downloader")
    logger.info("  Cells: %d unique 0.5° grid points", len(cells))
    logger.info("  Years: %d-%d (%d years)", args.start_year, args.end_year, n_years)
    logger.info("  Total cell-years: %d", total_all)
    logger.info("  Already cached: %d (%.1f%%)", cached, cached / max(total_all, 1) * 100)
    logger.info("  Remaining: %d", total_tasks)
    logger.info("  Workers: %d", args.workers)
    est_hours = total_tasks * (4.0 + WORKER_DELAY) / args.workers / 3600
    logger.info("  Est. time: %.1f hours", est_hours)
    logger.info("  Cache dir: %s", CACHE_DIR)
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("Dry run — exiting without downloading.")
        # Estimate storage
        est_gb = total_all * 0.3 / 1000  # ~300 KB per cell-year NPZ
        logger.info("  Est. total storage: %.1f GB", est_gb)
        return

    if total_tasks == 0:
        logger.info("All data already cached!")
        return

    # Download
    start_time = time.time()
    completed_count = cached  # count already-cached as completed
    total_tasks = total_all   # total including cached (for progress %)

    logger.info("Starting download with %d workers...", args.workers)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(download_worker, task): task for task in tasks}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                task = futures[future]
                logger.error("Unexpected error for %s: %s", task, e)

    elapsed = time.time() - start_time
    save_progress(completed_count, failed_count, total_tasks)

    logger.info("=" * 60)
    logger.info("Download complete!")
    logger.info("  Total time: %.1f hours", elapsed / 3600)
    logger.info("  Completed: %d / %d", completed_count, total_tasks)
    logger.info("  Failed: %d", failed_count)
    logger.info("  Cache dir: %s", CACHE_DIR)

    # Calculate actual storage used
    total_bytes = sum(
        f.stat().st_size
        for f in CACHE_DIR.rglob("*.npz")
    )
    logger.info("  Storage used: %.1f GB", total_bytes / 1e9)
    logger.info("=" * 60)

    # Count no-data markers
    nodata_count = sum(1 for f in CACHE_DIR.rglob("_nodata"))
    if nodata_count:
        logger.info("  No-data cells: %d (ocean/invalid — permanently skipped)", nodata_count)

    if failed_count > 0 and failed_count > nodata_count:
        logger.warning("Re-run this script to retry failed downloads (resume-safe).")
    elif failed_count > 0:
        logger.info("All failures are no-data cells — no retries needed.")


if __name__ == "__main__":
    main()
